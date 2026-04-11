#! .venv/bin/python3
"""Learn: Reexpress — iterative improvement loop for the reexpress (IP-Adapter) pipeline.

Pipeline flow: source avatar + target expression → ipadapter_faceid → scored candidate.

For each iteration:
  1. Sample examples (--samples / --range / full set)
  2. For each (example, expression) pair, call ipadapter_faceid with the target expression prompt
  3. Score: identity preservation (compare_side_by_side) + expression match (classify_image_expression)
  4. Analyze failures, ask reasoning LLM for fixes (expression FACS, synonyms, IP-Adapter weight)
  5. Repeat with worst-half + fresh examples until plateau or max-iterations

The source image for each example is taken from assets/examples/<name>/photorealistic.png.

Usage:
    python scripts/learn/learn_reexpress.py --samples 20
    python scripts/learn/learn_reexpress.py --range 0 49 --max-iterations 5 --optimize fast
    python scripts/learn/learn_reexpress.py  # full set — prompts for confirmation
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import re
import subprocess
import sys
import textwrap
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import yaml
from tqdm import tqdm

# ── project root on sys.path ──────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "examples"))

from _cli import add_common_args, confirm_full_set  # noqa: E402
from _example_utils import EXAMPLES_DIR, REPORTS_DIR, load_all_personas  # noqa: E402
from _logger import make_logger  # noqa: E402
from _sampler import initial_sample, iteration_schedule, next_sample, score_sample  # noqa: E402

from config.gateway import GatewayClient  # noqa: E402
from pipeline.render.expression_resolver import resolve_expression  # noqa: E402
from pipeline.render.llm.prompt_builder import build_clip_prompt_reexpress  # noqa: E402
from pipeline.render.style_resolver import STYLES_YML  # noqa: E402
from tuning.classify_expression import classify_image_expression  # noqa: E402
from tuning.classify_style import classify_image_style  # noqa: E402
from tuning.compare_side_by_side import compare_side_by_side  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

EXPRESSIONS_PATH = ROOT / "assets" / "expressions" / "expressions.yml"
IDENTITY_PASS_THRESHOLD = 0.60
EXPRESSION_PASS_THRESHOLD = 0.60
PLATEAU_DELTA = 0.01
PLATEAU_PATIENCE = 2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_expressions() -> list[dict]:
    with open(EXPRESSIONS_PATH) as f:
        data = yaml.safe_load(f)
    return data.get("expressions", [])


def _load_styles() -> list[dict]:
    with open(STYLES_YML) as f:
        data = yaml.safe_load(f)
    return data.get("styles", [])


def _atomic_write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp.rename(path)


def _check_plateau(score_history: list[float]) -> bool:
    if len(score_history) < PLATEAU_PATIENCE + 1:
        return False
    deltas = [
        abs(score_history[-i] - score_history[-i - 1]) for i in range(1, PLATEAU_PATIENCE + 1)
    ]
    return all(d < PLATEAU_DELTA for d in deltas)


def _source_image(example_dir: Path) -> bytes | None:
    for fname in ("photorealistic.png", "photorealistic_benchmark_1.png"):
        p = example_dir / fname
        if p.exists():
            with open(p, "rb") as f:
                return f.read()
    return None


# ---------------------------------------------------------------------------
# Generate + score one (example, expression) pair
# ---------------------------------------------------------------------------


def _process_one(
    client: GatewayClient,
    name: str,
    expression_id: str,
    example_dir: Path,
    all_styles: list[dict],
    *,
    optimize: str,
) -> dict:
    result: dict = {"example": name, "expression_id": expression_id, "error": None}

    source_bytes = _source_image(example_dir)
    if source_bytes is None:
        result["error"] = "no source image"
        return result

    source_b64 = base64.b64encode(source_bytes).decode()

    # Detect source style
    try:
        style_result = classify_image_style(source_bytes, all_styles, gateway_url=client.base_url)
        style_id = style_result.top_style_id or "photorealistic"
    except Exception:
        style_id = "photorealistic"
    result["style_id"] = style_id

    # Build CLIP prompt
    expr_entry = resolve_expression(expression_id)
    clip_prompt = build_clip_prompt_reexpress(expr_entry)

    # Generate via IP-Adapter
    t0 = time.time()
    try:
        candidate_bytes = client.ipadapter_faceid(
            clip_prompt,
            [source_b64],
            width=512,
            height=512,
            optimize=optimize,
        )
    except Exception as exc:
        result["error"] = f"generation: {exc}"
        return result
    result["generation_time_s"] = round(time.time() - t0, 1)

    # Score: expression match
    try:
        expr_result = classify_image_expression(
            candidate_bytes, [expression_id], gateway_url=client.base_url
        )
        result["expression_score"] = round(expr_result.top_score(), 3)
        result["expression_top"] = (
            expr_result.top_label() if hasattr(expr_result, "top_label") else ""
        )
    except Exception as exc:
        logger.warning("expression classification failed %s: %s", name, exc)
        result["expression_score"] = 0.0

    # Score: identity (SBS)
    try:
        sbs = compare_side_by_side(
            source_bytes,
            candidate_bytes,
            goal=f"apply {expression_id} expression while preserving identity and style",
            reference_label="source",
            generated_label="reexpressed",
            gateway_url=client.base_url,
        )
        result["identity_score"] = round(sbs.identity_score, 3)
        result["compound_score"] = round(sbs.compound_score, 3)
        result["sbs_reasoning"] = (sbs.reasoning or "")[:200]
    except Exception as exc:
        logger.warning("SBS failed %s: %s", name, exc)
        result["identity_score"] = 0.0
        result["compound_score"] = 0.0

    return result


# ---------------------------------------------------------------------------
# LLM fix for reexpress
# ---------------------------------------------------------------------------

_FIX_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "expression_synonym_additions": {
            "type": "object",
            "additionalProperties": {"type": "array", "items": {"type": "string"}},
        },
        "facs_patches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string"},
                    "find": {"type": "string"},
                    "replace": {"type": "string"},
                },
                "required": ["expression", "find", "replace"],
                "additionalProperties": False,
            },
        },
        "weight_suggestion": {"type": "number"},
        "rationale": {"type": "string"},
    },
    "required": ["expression_synonym_additions", "facs_patches", "weight_suggestion", "rationale"],
    "additionalProperties": False,
}


def _apply_reexpress_fixes(
    client: GatewayClient,
    entries: list[dict],
    fixes_path: Path,
    component_threshold: float = 0.75,
) -> dict:
    """Ask reasoning LLM for reexpress improvements, apply expression FACS / synonym patches."""
    failures = [
        e
        for e in entries
        if not e.get("error")
        and (
            e.get("expression_score", 0) < component_threshold
            or e.get("identity_score", 0) < component_threshold
        )
    ]

    failure_summary = "\n".join(
        f"  {e['example']} x {e['expression_id']}: "
        f"expr={e.get('expression_score', 0):.0%}  "
        f"identity={e.get('identity_score', 0):.0%}  "
        f"top={e.get('expression_top', '?')}  "
        f'"{e.get("sbs_reasoning", "")[:100]}"'
        for e in failures[:20]
    )

    with open(EXPRESSIONS_PATH) as f:
        expressions_content = f.read()

    reasoning_prompt = textwrap.dedent(f"""
        You are improving the avatar-studio reexpress pipeline (IP-Adapter FaceID based).
        The reexpress pipeline changes the expression of an existing avatar.

        ## Failures (expr score < {component_threshold:.0%} or identity score < {component_threshold:.0%})
        {failure_summary or "(none)"}

        ## Current expressions.yml
        {expressions_content}

        Analyze:
        1. Which expressions consistently fail? What top label does the classifier return instead?
        2. Are there synonyms missing that would help the classifier recognize the expression?
        3. Should any FACS action_units be adjusted for better visual signal?
        4. What IP-Adapter weight (0.0–1.0) balances identity vs expression better?

        Be specific and reference exact strings from expressions.yml.
    """).strip()

    schema_json = json.dumps(_FIX_SCHEMA, indent=2)
    format_prompt = textwrap.dedent(f"""
        Based on the analysis below, produce a JSON fix specification.

        ANALYSIS:
        {{reasoning}}

        OUTPUT SCHEMA (single valid JSON object, no prose):
        {schema_json}

        Rules:
        - expression_synonym_additions: {{expression_name: [new_synonyms]}} — exact name from expressions.yml
        - facs_patches: patches to facs_action_units strings in expressions.yml
        - weight_suggestion: null if no change needed
        - Leave arrays empty if no changes needed.
    """).strip()

    applied: list[str] = []
    skipped: list[str] = []
    fixes: dict = {
        "expression_synonym_additions": {},
        "facs_patches": [],
        "weight_suggestion": None,
        "rationale": "",
    }

    try:
        reasoning_output = client.reasoning(
            messages=[{"role": "user", "content": reasoning_prompt}], timeout=600
        )
    except Exception as exc:
        logger.error("Reasoning model failed: %s", exc)
        fixes["_error"] = str(exc)
        fixes["_applied"] = applied
        fixes["_skipped"] = skipped
        _atomic_write(fixes_path, fixes)
        return fixes

    logger.info("Reasoning: %s", reasoning_output[:500])

    try:
        raw = client.general(
            messages=[
                {"role": "user", "content": format_prompt.replace("{reasoning}", reasoning_output)}
            ],
            timeout=120,
        )
        text = raw.strip()
        fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if fence:
            text = fence.group(1).strip()
        fixes = json.loads(text)
    except Exception as exc:
        logger.error("Format model failed: %s", exc)
        fixes["_error"] = str(exc)
        fixes["_applied"] = applied
        fixes["_skipped"] = skipped
        _atomic_write(fixes_path, fixes)
        return fixes

    fixes["_reasoning"] = reasoning_output[:2000]

    # Apply to expressions.yml
    with open(EXPRESSIONS_PATH) as f:
        expressions_data = yaml.safe_load(f)
    expr_map = {e["expression"]: e for e in expressions_data.get("expressions", [])}

    # Synonym additions
    for expr_name, new_synonyms in fixes.get("expression_synonym_additions", {}).items():
        if not new_synonyms:
            continue
        if expr_name not in expr_map:
            skipped.append(f"expression not found: {expr_name}")
            continue
        existing = set(expr_map[expr_name].get("synonyms", []))
        added = [s for s in new_synonyms if s not in existing]
        expr_map[expr_name].setdefault("synonyms", []).extend(added)
        if added:
            applied.append(f"expression.{expr_name}.synonyms: +{len(added)}")

    # FACS patches
    for patch in fixes.get("facs_patches", []):
        expr_name = patch.get("expression", "")
        find_str = patch.get("find", "")
        replace_str = patch.get("replace", "")
        if not find_str or expr_name not in expr_map:
            skipped.append(f"facs_patch skipped: expression={expr_name}")
            continue
        current_facs = expr_map[expr_name].get("facs_action_units", "")
        if find_str not in current_facs:
            skipped.append(f"facs_patch find not found for {expr_name}")
            continue
        expr_map[expr_name]["facs_action_units"] = current_facs.replace(find_str, replace_str, 1)
        applied.append(f"expression.{expr_name}.facs_action_units patched")

    tmp = EXPRESSIONS_PATH.with_suffix(".tmp")
    with open(tmp, "w") as f:
        yaml.dump(
            expressions_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False
        )
    tmp.rename(EXPRESSIONS_PATH)

    fixes["_applied"] = applied
    fixes["_skipped"] = skipped
    _atomic_write(fixes_path, fixes)

    logger.info("Reexpress fixes applied: %d  Skipped: %d", len(applied), len(skipped))
    return fixes


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def run_learn_reexpress(
    *,
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
    log = make_logger("learn_reexpress", log_dir)

    all_examples = load_all_personas(examples_dir)
    all_examples = [(n, p) for n, p in all_examples if _source_image(examples_dir / n) is not None]
    if not all_examples:
        logger.error("No examples with source avatar image found in %s", examples_dir)
        sys.exit(1)

    if samples is None and range_ is None:
        confirm_full_set(len(all_examples))

    current_sample = initial_sample(all_examples, n=samples, range_=range_)
    target_n = len(current_sample)
    schedule = iteration_schedule(target_n, max_n=512, max_iterations=max_iterations)

    all_expressions = [e["expression"].lower() for e in _load_expressions()]
    all_styles = _load_styles()

    ts = datetime.now().strftime("%y-%m-%d-%H-%M")
    loop_dir = REPORTS_DIR / f"learn_reexpress_{ts}"
    loop_dir.mkdir(parents=True, exist_ok=True)

    log.config(
        script="learn_reexpress",
        max_iterations=max_iterations,
        stop_on_plateau=stop_on_plateau,
        workers=workers,
        optimize=optimize,
        samples=target_n,
        expressions=all_expressions,
        loop_dir=str(loop_dir),
    )

    logger.info(
        "learn_reexpress: samples=%d  expressions=%s  max_iter=%d  optimize=%s  schedule=%s = total %d",
        target_n,
        all_expressions,
        max_iterations,
        optimize,
        " → ".join(str(x) for x in schedule),
        sum(schedule) * len(all_expressions),
    )

    client = GatewayClient(gateway_url)
    score_history: list[float] = []
    state: dict = {"loop_dir": str(loop_dir), "iterations": []}

    for iteration in range(1, max_iterations + 1):
        prefix = f"iter_{iteration:02d}"
        work = [
            (name, persona, expr_id)
            for name, persona in current_sample
            for expr_id in all_expressions
        ]
        entries: list[dict] = []

        logger.info("[iter %d/%d] Generating %d images…", iteration, max_iterations, len(work))

        running_expr = 0.0
        running_identity = 0.0
        n_ok = 0
        n_errors = 0
        pbar_desc = f"iter {iteration}/{max_iterations}"

        def _on_entry(entry: dict, name: str, expr_id: str) -> None:
            nonlocal running_expr, running_identity, n_ok, n_errors
            entries.append(entry)
            log.render(
                iteration=iteration, example=name, expression=expr_id, error=entry.get("error")
            )
            if entry.get("error"):
                n_errors += 1
                logger.warning("  failed: %s x %s — %s", name, expr_id, entry["error"])
            else:
                n_ok += 1
                running_expr += entry.get("expression_score", 0.0)
                running_identity += entry.get("identity_score", 0.0)
                log.score(
                    iteration=iteration,
                    example=name,
                    expression=expr_id,
                    expression_score=entry.get("expression_score"),
                    identity_score=entry.get("identity_score"),
                )

        if workers <= 1:
            pbar = tqdm(work, desc=pbar_desc, unit="img")
            for name, persona, expr_id in pbar:
                pbar.set_postfix_str(f"{name} x {expr_id}")
                entry = _process_one(
                    client, name, expr_id, examples_dir / name, all_styles, optimize=optimize
                )
                _on_entry(entry, name, expr_id)
                if n_ok:
                    pbar.set_postfix_str(
                        f"expr={running_expr / n_ok:.0%} id={running_identity / n_ok:.0%}"
                        + (f" err={n_errors}" if n_errors else "")
                    )
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {
                    pool.submit(
                        _process_one,
                        client,
                        name,
                        expr_id,
                        examples_dir / name,
                        all_styles,
                        optimize=optimize,
                    ): (name, expr_id)
                    for name, persona, expr_id in work
                }
                pbar = tqdm(as_completed(futures), total=len(futures), desc=pbar_desc, unit="img")
                for future in pbar:
                    name, expr_id = futures[future]
                    try:
                        entry = future.result()
                    except Exception as exc:
                        entry = {"example": name, "expression_id": expr_id, "error": str(exc)}
                    _on_entry(entry, name, expr_id)
                    if n_ok:
                        pbar.set_postfix_str(
                            f"expr={running_expr / n_ok:.0%} id={running_identity / n_ok:.0%}"
                            + (f" err={n_errors}" if n_errors else "")
                        )

        # Summarize
        successful = [e for e in entries if not e.get("error")]
        avg_expr = (
            sum(e.get("expression_score", 0) for e in successful) / len(successful)
            if successful
            else 0.0
        )
        avg_identity = (
            sum(e.get("identity_score", 0) for e in successful) / len(successful)
            if successful
            else 0.0
        )
        combined = (avg_expr + avg_identity) / 2
        score_history.append(combined)

        # Per-expression breakdown
        by_expr: dict[str, list[float]] = {}
        for e in successful:
            by_expr.setdefault(e["expression_id"], []).append(e.get("expression_score", 0))
        expr_breakdown = {k: round(sum(v) / len(v), 3) for k, v in by_expr.items()}

        log.summary(
            iteration=iteration,
            avg_expression=round(avg_expr, 3),
            avg_identity=round(avg_identity, 3),
            combined=round(combined, 3),
            by_expression=expr_breakdown,
            n_successful=len(successful),
            n_failed=len(entries) - len(successful),
        )
        logger.info(
            "[iter %d] expr=%.0f%%  identity=%.0f%%  combined=%.0f%%",
            iteration,
            avg_expr * 100,
            avg_identity * 100,
            combined * 100,
        )
        for expr_id, avg in sorted(expr_breakdown.items()):
            logger.info("  %s: %.0f%%", expr_id, avg * 100)

        # Log worst examples to surface persistent failures
        if successful:
            worst = sorted(successful, key=lambda e: e.get("identity_score", 0))[:5]
            for w in worst:
                logger.info(
                    "  low: %-24s  expr=%.0f%%  id=%.0f%%  %s",
                    w["example"],
                    w.get("expression_score", 0) * 100,
                    w.get("identity_score", 0) * 100,
                    w.get("sbs_reasoning", "")[:80],
                )

        # Plateau check
        if stop_on_plateau and _check_plateau(score_history):
            logger.info("Plateau detected — stopping")
            log.plateau(iteration=iteration, score_history=score_history)
            log.done(reason="plateau", iteration=iteration)
            state["iterations"].append(
                {"iter": iteration, "combined": combined, "status": "PLATEAU_STOP"}
            )
            _atomic_write(loop_dir / "state.json", state)
            break

        # LLM fixes
        fixes_path = loop_dir / f"{prefix}_fixes.json"
        fixes = _apply_reexpress_fixes(
            client, entries, fixes_path, component_threshold=component_threshold
        )
        for fix_desc in fixes.get("_applied", []):
            log.fix(iteration=iteration, description=fix_desc)

        state["iterations"].append(
            {
                "iter": iteration,
                "avg_expression": round(avg_expr, 3),
                "avg_identity": round(avg_identity, 3),
                "fixes_applied": len(fixes.get("_applied", [])),
                "status": "IMPROVING",
            }
        )
        _atomic_write(loop_dir / "state.json", state)

        # Next sample
        if iteration < max_iterations:
            example_scores = {e["example"]: e.get("expression_score", 0.0) for e in successful}
            prev_scored = score_sample(current_sample, example_scores)
            next_target = schedule[iteration]
            current_sample = next_sample(
                all_examples, prev_scored=prev_scored, target_n=next_target
            )

    else:
        logger.info("Reached max iterations (%d).", max_iterations)
        log.done(reason="max_iterations", iterations=max_iterations)

    print(f"\n{'=' * 60}")
    print(f"learn_reexpress complete — {len(state['iterations'])} iterations")
    print(f"State: {loop_dir / 'state.json'}")
    print(f"Log:   {log._path}")

    diff = subprocess.run(
        ["git", "diff", "--stat", "assets/"], capture_output=True, text=True, cwd=ROOT
    )
    if diff.stdout.strip():
        print("\n--- git diff --stat (assets/) ---")
        print(diff.stdout.strip())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Learn: iterative improvement for the reexpress (IP-Adapter) pipeline"
    )
    add_common_args(parser)
    parser.add_argument("--examples-dir", type=Path, default=EXAMPLES_DIR)
    args = parser.parse_args()

    run_learn_reexpress(
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
