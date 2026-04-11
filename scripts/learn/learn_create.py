#! .venv/bin/python3
"""Learn: Create from Persona — iterative improvement loop for the create pipeline.

Pipeline flow: persona → neutral portrait (image_gen) → score → fix → repeat.

For each iteration:
  1. Sample examples (--samples / --range / full set)
  2. Generate neutral portraits via image_gen (persona + reference photo)
  3. Score: persona match + style match + SBS identity
  4. Analyze failures, ask reasoning LLM for fixes, apply to asset files
  5. Repeat with worst-half + fresh examples until target, plateau, or max-iterations

Usage:
    python scripts/learn/learn_create.py --samples 20 --style photorealistic
    python scripts/learn/learn_create.py --range 0 49 --max-iterations 5 --optimize fast
    python scripts/learn/learn_create.py  # full set — prompts for confirmation
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ── project root on sys.path ──────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "examples"))

from _analyze import run_analysis  # noqa: E402
from _benchmark import REPORTS_DIR, run_benchmark  # noqa: E402
from _cli import add_common_args, confirm_full_set  # noqa: E402
from _example_utils import EXAMPLES_DIR, load_all_personas  # noqa: E402
from _fixes import apply_llm_fixes  # noqa: E402
from _logger import make_logger  # noqa: E402
from _sampler import initial_sample, iteration_schedule, next_sample, score_sample  # noqa: E402

from config.gateway import GatewayClient  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PLATEAU_DELTA = 0.01
PLATEAU_PATIENCE = 2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _atomic_write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp.rename(path)


def _check_plateau(score_history: list[float]) -> bool:
    """Return True if the last PLATEAU_PATIENCE score deltas are all < PLATEAU_DELTA."""
    if len(score_history) < PLATEAU_PATIENCE + 1:
        return False
    deltas = [
        abs(score_history[-i] - score_history[-i - 1]) for i in range(1, PLATEAU_PATIENCE + 1)
    ]
    return all(d < PLATEAU_DELTA for d in deltas)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def run_learn_create(
    *,
    style: str,
    target: float,
    max_iterations: int,
    stop_on_plateau: bool,
    gateway_url: str,
    examples_dir: Path,
    workers: int,
    optimize: str,
    log_dir: Path,
    samples: int | None,
    range_: tuple[int, int] | None,
    component_threshold: float = 0.75,
    compound_threshold: float = 0.90,
) -> None:
    log = make_logger("learn_create", log_dir)

    # Load all examples
    all_examples = load_all_personas(examples_dir)
    if not all_examples:
        logger.error("No examples found in %s", examples_dir)
        sys.exit(1)

    if samples is None and range_ is None:
        confirm_full_set(len(all_examples))

    current_sample = initial_sample(all_examples, n=samples, range_=range_)
    target_n = len(current_sample)
    schedule = iteration_schedule(target_n, max_n=512, max_iterations=max_iterations)

    ts = datetime.now().strftime("%y-%m-%d-%H-%M")
    loop_dir = REPORTS_DIR / f"learn_create_{ts}"
    loop_dir.mkdir(parents=True, exist_ok=True)

    log.config(
        script="learn_create",
        style=style,
        target=target,
        max_iterations=max_iterations,
        stop_on_plateau=stop_on_plateau,
        workers=workers,
        optimize=optimize,
        samples=target_n,
        loop_dir=str(loop_dir),
    )

    logger.info(
        "learn_create: style=%s  samples=%d  max_iter=%d  optimize=%s",
        style,
        target_n,
        max_iterations,
        optimize,
    )

    client = GatewayClient(gateway_url)
    score_history: list[float] = []
    prev_scored: list[tuple[tuple[str, dict], float]] = []

    state: dict = {
        "style": style,
        "target": target,
        "loop_dir": str(loop_dir),
        "iterations": [],
    }

    for iteration in range(1, max_iterations + 1):
        prefix = f"iter_{iteration:02d}"
        sample_names = {name for name, _ in current_sample}
        iter_target = schedule[iteration - 1]

        bench_path = loop_dir / f"{prefix}_benchmark.json"
        logger.info(
            "[iter %d/%d] Benchmarking %d examples…", iteration, max_iterations, iter_target
        )

        summary = run_benchmark(
            examples_dir=examples_dir,
            gateway_url=gateway_url,
            style_filter=style,
            example_range=None,
            runs=1,
            resume=False,
            output_path=bench_path,
            workers=workers,
            component_threshold=component_threshold,
            total_threshold=compound_threshold,
            optimize=optimize,
            example_names=sample_names,
        )

        avg_p = summary.get("avg_persona_score", 0.0)
        sbs_compound = summary.get("avg_sbs_compound", 0.0)
        score_history.append(avg_p)

        log.summary(
            iteration=iteration,
            avg_persona=avg_p,
            persona_pass_rate=summary.get("persona_pass_rate", 0.0),
            avg_style=summary.get("avg_style_score", 0.0),
            sbs_compound=sbs_compound,
            examples=target_n,
        )

        logger.info(
            "[iter %d] persona=%.0f%%  sbs_compound=%.0f%%",
            iteration,
            avg_p * 100,
            sbs_compound * 100,
        )

        # Convergence check
        if avg_p >= target and sbs_compound >= target:
            logger.info("Target reached — persona=%.2f  sbs_compound=%.2f", avg_p, sbs_compound)
            log.done(reason="target_reached", iteration=iteration, avg_persona=avg_p)
            state["iterations"].append(
                {"iter": iteration, "avg_persona": avg_p, "status": "SATISFACTORY"}
            )
            _atomic_write(loop_dir / "state.json", state)
            break

        # Plateau check
        if stop_on_plateau and _check_plateau(score_history):
            logger.info("Plateau detected — stopping after %d iterations", iteration)
            log.plateau(iteration=iteration, score_history=score_history)
            log.done(reason="plateau", iteration=iteration, avg_persona=avg_p)
            state["iterations"].append(
                {"iter": iteration, "avg_persona": avg_p, "status": "PLATEAU_STOP"}
            )
            _atomic_write(loop_dir / "state.json", state)
            break

        # Analysis
        analysis_path = loop_dir / f"{prefix}_analysis.json"
        logger.info("[iter %d] Analyzing…", iteration)
        analysis = run_analysis(
            input_path=bench_path,
            coverage_path=None,
            output_path=analysis_path,
            bottom_n=10,
        )

        # LLM fixes
        fixes_path = loop_dir / f"{prefix}_fixes.json"
        logger.info("[iter %d] Applying LLM fixes…", iteration)
        fixes = apply_llm_fixes(client, analysis, fixes_path)
        applied = fixes.get("_applied", [])
        for fix_desc in applied:
            log.fix(iteration=iteration, description=fix_desc)

        state["iterations"].append(
            {
                "iter": iteration,
                "avg_persona": avg_p,
                "fixes_applied": len(applied),
                "status": "IMPROVING",
            }
        )
        _atomic_write(loop_dir / "state.json", state)

        # Build next sample from bench results
        try:
            with open(bench_path) as f:
                bench_data = json.load(f)
            entry_scores = {
                e["example"]: e.get("persona_score", 0.0) for e in bench_data.get("entries", [])
            }
        except Exception:
            entry_scores = {}

        prev_scored = score_sample(current_sample, entry_scores)

        if iteration < max_iterations:
            next_target = schedule[iteration]
            current_sample = next_sample(
                all_examples, prev_scored=prev_scored, target_n=next_target
            )
            logger.info("[iter %d] Next sample: %d examples", iteration, len(current_sample))

    else:
        logger.info("Reached max iterations (%d).", max_iterations)
        log.done(reason="max_iterations", iterations=max_iterations)

    # Final summary
    print(f"\n{'=' * 60}")
    print(f"learn_create complete — {len(state['iterations'])} iterations")
    print(f"State: {loop_dir / 'state.json'}")
    print(f"Log:   {log._path}")

    diff = subprocess.run(
        ["git", "diff", "--stat", "assets/", "src/"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    if diff.stdout.strip():
        print("\n--- git diff --stat (assets/ src/) ---")
        print(diff.stdout.strip())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Learn: iterative improvement for the create-from-persona pipeline"
    )
    add_common_args(parser)
    parser.add_argument(
        "--style",
        default="photorealistic",
        help="Style ID to benchmark (default: photorealistic)",
    )
    parser.add_argument(
        "--target",
        type=float,
        default=0.90,
        help="Avg persona score target to stop early (default: 0.90)",
    )
    parser.add_argument("--examples-dir", type=Path, default=EXAMPLES_DIR)
    args = parser.parse_args()

    run_learn_create(
        style=args.style,
        target=args.target,
        max_iterations=args.max_iterations,
        stop_on_plateau=args.stop_on_plateau,
        gateway_url=args.gateway,
        examples_dir=args.examples_dir,
        workers=args.workers,
        optimize=args.optimize,
        log_dir=args.log_dir,
        samples=args.samples,
        range_=tuple(args.range) if args.range else None,
        component_threshold=args.component_threshold / 100,
        compound_threshold=args.compound_threshold / 100,
    )
