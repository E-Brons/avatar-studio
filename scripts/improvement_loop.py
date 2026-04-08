"""Automated improvement loop — benchmark → analyze → LLM fixes → repeat.

Runs the benchmark on a range of examples, analyzes results, asks an LLM to
suggest pool / synonym / prompt improvements, applies them, and re-benchmarks.
Stops when the persona pass-rate reaches the target or the iteration cap is hit.

Usage:
    python scripts/improvement_loop.py --range 0 10 --style photorealistic
    python scripts/improvement_loop.py --range 0 10 --target 0.85 --max-iterations 5
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import textwrap
from datetime import datetime
from pathlib import Path

import yaml

# ── project root on sys.path ──────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from _example_utils import EXAMPLES_DIR, REPORTS_DIR  # noqa: E402
from analyze_benchmark import run_analysis  # noqa: E402
from example_benchmark import run_benchmark  # noqa: E402

from config.gateway import GatewayClient  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

GATEWAY_URL = "http://127.0.0.1:4096"

PHENOTYPE_PATH = ROOT / "assets" / "persona" / "phenotype_settings.json"
PRESENTATION_PATH = ROOT / "assets" / "persona" / "presentation_settings.json"
EXPRESSIONS_PATH = ROOT / "assets" / "expressions" / "expressions.yml"
PERSONA_SANITIZER_PATH = ROOT / "src" / "pipeline" / "render" / "llm" / "persona_sanitizer.py"

# ---------------------------------------------------------------------------
# JSON schema for LLM fix output
# ---------------------------------------------------------------------------

_FIX_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "phenotype_additions": {
            "type": "object",
            "additionalProperties": {"type": "array", "items": {"type": "string"}},
        },
        "presentation_additions": {
            "type": "object",
            "additionalProperties": {"type": "array", "items": {"type": "string"}},
        },
        "expression_synonym_additions": {
            "type": "object",
            "additionalProperties": {"type": "array", "items": {"type": "string"}},
        },
        "prompt_patches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "find": {"type": "string"},
                    "replace": {"type": "string"},
                },
                "required": ["find", "replace"],
                "additionalProperties": False,
            },
        },
        "rationale": {"type": "string"},
    },
    "required": [
        "phenotype_additions",
        "presentation_additions",
        "expression_synonym_additions",
        "prompt_patches",
        "rationale",
    ],
    "additionalProperties": False,
}

_FIX_OUTPUT_CONFIG: dict = {"format": {"type": "json_schema", "schema": _FIX_SCHEMA}}


# ---------------------------------------------------------------------------
# Atomic write helper
# ---------------------------------------------------------------------------


def _atomic_write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp.rename(path)


# ---------------------------------------------------------------------------
# Asset loaders
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def _load_synonyms_section() -> str:
    """Return the synonyms portion of expressions.yml as a compact string."""
    with open(EXPRESSIONS_PATH) as f:
        data = yaml.safe_load(f)
    lines = []
    for expr in data.get("expressions", []):
        name = expr.get("expression", "")
        synonyms = expr.get("synonyms", [])
        lines.append(f"  {name}: {synonyms}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM fix step
# ---------------------------------------------------------------------------


def _compact_phenotype() -> str:
    """Compact representation of phenotype — excludes palette (100 hex colors, not useful)."""
    data = _load_json(PHENOTYPE_PATH)
    data = {k: v for k, v in data.items() if k != "palette"}
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


def _compact_presentation() -> str:
    """Compact representation of presentation settings."""
    return json.dumps(_load_json(PRESENTATION_PATH), separators=(",", ":"), ensure_ascii=False)


def _sanitizer_dicts_only() -> str:
    """Return only the lookup dict section of persona_sanitizer.py (skip function bodies)."""
    lines = PERSONA_SANITIZER_PATH.read_text().splitlines()
    # Include everything up to (not including) the enrichment engine functions
    cutoff = next(
        (i for i, line in enumerate(lines) if "def _enrich_skin_tone" in line),
        len(lines),
    )
    return "\n".join(lines[:cutoff]).strip()


def _build_reasoning_prompt(analysis: dict) -> str:
    """Free-form prompt for the reasoning model — no schema constraints, think creatively."""
    recommendations = analysis.get("recommendations", [])
    by_property = analysis.get("by_property", {})
    systematic = analysis.get("systematic_failures", [])
    sbs = analysis.get("sbs", {})

    recs_text = "\n".join(
        f"  [{r['severity'].upper()}] {r['detail']} → {r.get('action', '')}"
        for r in recommendations
    )

    by_prop_text = "\n".join(
        f"  {p}: failure_rate={info['failure_rate']:.0%} "
        f"top_notes={[n['note'] for n in info.get('top_failure_notes', [])[:3]]}"
        for p, info in by_property.items()
        if info.get("failure_rate", 0) > 0.10
    )

    systematic_text = "\n".join(
        f"  {sf['property']} × {sf['gender']} × {sf['style']}: "
        f"{sf['failure_rate']:.0%} fail — {sf.get('top_notes', [])[:2]}"
        for sf in systematic[:10]
    )

    sbs_text = ""
    if sbs.get("sample_size", 0) > 0:
        sbs_text = (
            f"identity={sbs['avg_identity']:.0%}  goal={sbs['avg_goal']:.0%}  "
            f"quality={sbs['avg_quality']:.0%}  compound={sbs['avg_compound']:.0%}  "
            f"({sbs['sample_size']} images)"
        )
        if sbs.get("worst"):
            worst_lines = "\n".join(
                f"  {w['example']}: compound={w['compound']:.0%} id={w['identity']:.0%} "
                f'goal={w["goal"]:.0%} — "{w["reasoning"][:120]}"'
                for w in sbs["worst"][:3]
            )
            sbs_text += f"\n  Worst performers:\n{worst_lines}"

    phenotype_json = _compact_phenotype()
    presentation_json = _compact_presentation()
    synonyms_text = _load_synonyms_section()
    sanitizer_content = _sanitizer_dicts_only()

    return textwrap.dedent(f"""
        You are an expert avatar-studio improvement agent. Analyze these benchmark results
        and reason deeply about what fixes will genuinely improve the scores.

        Think creatively and critically. Don't just make obvious small tweaks — consider
        whether the whole approach is right. If SBS identity is low, the persona prompt may
        be fighting the reference photo; maybe descriptions should be shorter, not longer.
        If a property fails consistently, ask WHY — is the pool value missing, the visual
        description wrong, or the image model ignoring it entirely?

        ## Benchmark recommendations
        {recs_text or "(none)"}

        ## Property failure rates (>10%)
        {by_prop_text or "(none)"}

        ## Systematic failures (property × gender × style > 50%)
        {systematic_text or "(none)"}

        ## Side-by-side identity scores (§4.5)
        {sbs_text or "(none — SBS not yet measured)"}
        IMPORTANT: SBS measures whether the output actually looks like the reference person.
        If SBS compound < 50%, verbose persona descriptions are likely overriding the photo.
        In that case, the fix is LESS detail in prompts, not more.

        ## Current phenotype_settings.json (palette excluded)
        {phenotype_json}

        ## Current presentation_settings.json
        {presentation_json}

        ## Current expression synonyms
        {synonyms_text}

        ## Current persona_sanitizer.py (lookup dicts only)
        {sanitizer_content}

        ---
        Reason step by step:
        1. What are the root causes of the failures?
        2. What specific changes would address each root cause?
        3. For prompt_patches — quote the exact find/replace strings from persona_sanitizer.py.
        4. For pool additions — which keys and which values are genuinely missing?
        5. Are there any changes that could HURT? Avoid them.

        Be specific and concrete. Your reasoning will be used to generate precise code changes.
    """).strip()


def _build_format_prompt(reasoning: str) -> str:
    """Short formatting prompt — turns reasoning output into the structured JSON fix spec."""
    schema_json = json.dumps(_FIX_SCHEMA, indent=2)
    return textwrap.dedent(f"""
        Based on the following analysis, produce a JSON fix specification.

        ANALYSIS:
        {reasoning}

        OUTPUT SCHEMA (output ONLY a single valid JSON object matching this schema — no markdown, no prose):
        {schema_json}

        Rules:
        - phenotype_additions: {{pool_key: [new_values]}} — use exact top-level key from phenotype_settings.json
        - presentation_additions: {{"key.gender": [new_values]}} — gender must be "male", "female", or "neutral"
        - expression_synonym_additions: {{expression_name: [new_synonyms]}} — exact expression name (e.g. "Sadness")
        - prompt_patches: [{{"find": "...", "replace": "..."}}] — strings taken verbatim from persona_sanitizer.py
        - rationale: one-sentence summary of what was changed and why
        - Leave any array empty [] if no changes are needed for that category.
    """).strip()


def apply_llm_fixes(
    client: GatewayClient,
    analysis: dict,
    fixes_path: Path,
) -> dict:
    """Two-step LLM fix: reasoning model thinks creatively, general model formats to JSON."""
    import re

    # ── Step 1: Reasoning model — creative free-form analysis ────────────
    reasoning_prompt = _build_reasoning_prompt(analysis)
    logger.info("Step 1: reasoning model (claude-opus) analyzing failures…")
    try:
        reasoning_output = client.reasoning(
            messages=[{"role": "user", "content": reasoning_prompt}],
            timeout=600,
        )
        logger.info("Reasoning complete (%d chars)", len(reasoning_output))
    except Exception as exc:
        logger.error("Reasoning model failed (%s) — skipping LLM fixes this iteration", exc)
        return {"_error": str(exc), "_applied": [], "_skipped": []}

    # ── Step 2: General model — format reasoning into structured JSON ─────
    format_prompt = _build_format_prompt(reasoning_output)
    logger.info("Step 2: general model (claude-sonnet) formatting fixes as JSON…")
    try:
        raw = client.general(
            messages=[{"role": "user", "content": format_prompt}],
            timeout=120,
        )
    except Exception as exc:
        logger.error("Formatting model failed (%s) — skipping LLM fixes this iteration", exc)
        return {
            "_error": str(exc),
            "_reasoning": reasoning_output[:2000],
            "_applied": [],
            "_skipped": [],
        }

    try:
        text = raw.strip()
        fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if fence:
            text = fence.group(1).strip()
        fixes: dict = json.loads(text)
    except Exception as exc:
        logger.error("Failed to parse LLM JSON output (%s) — skipping fixes this iteration", exc)
        logger.debug("Raw output: %s", raw[:500])
        return {
            "_error": str(exc),
            "_reasoning": reasoning_output[:2000],
            "_applied": [],
            "_skipped": [],
        }

    fixes["_reasoning"] = reasoning_output[:2000]  # preserve first 2K of reasoning for audit

    applied: list[str] = []
    skipped: list[str] = []

    # ── phenotype_additions ──────────────────────────────────────────────
    phenotype = _load_json(PHENOTYPE_PATH)
    for pool_key, new_values in fixes.get("phenotype_additions", {}).items():
        if not new_values:
            continue
        if pool_key not in phenotype:
            skipped.append(f"phenotype key not found: {pool_key}")
            logger.warning("phenotype key not found: %s — skipping", pool_key)
            continue
        if isinstance(phenotype[pool_key], list):
            existing = set(str(v) for v in phenotype[pool_key])
            added = [v for v in new_values if str(v) not in existing]
            phenotype[pool_key].extend(added)
            if added:
                applied.append(f"phenotype.{pool_key}: +{len(added)} values")
        else:
            skipped.append(f"phenotype.{pool_key} is not a list")
    _atomic_write(PHENOTYPE_PATH, phenotype)

    # ── presentation_additions ───────────────────────────────────────────
    presentation = _load_json(PRESENTATION_PATH)
    for dotted_key, new_values in fixes.get("presentation_additions", {}).items():
        if not new_values:
            continue
        parts = dotted_key.split(".", 1)
        if len(parts) != 2:
            skipped.append(f"presentation key malformed: {dotted_key}")
            logger.warning("presentation key malformed (expected key.gender): %s", dotted_key)
            continue
        pool_key, gender = parts
        if pool_key not in presentation:
            skipped.append(f"presentation key not found: {pool_key}")
            logger.warning("presentation key not found: %s — skipping", pool_key)
            continue
        gender_pool = presentation[pool_key]
        if not isinstance(gender_pool, dict) or gender not in gender_pool:
            skipped.append(f"presentation.{pool_key} has no gender={gender}")
            logger.warning("presentation.%s has no gender=%s — skipping", pool_key, gender)
            continue
        existing = set(str(v) for v in gender_pool[gender])
        added = [v for v in new_values if str(v) not in existing]
        gender_pool[gender].extend(added)
        if added:
            applied.append(f"presentation.{pool_key}.{gender}: +{len(added)} values")
    _atomic_write(PRESENTATION_PATH, presentation)

    # ── expression_synonym_additions ─────────────────────────────────────
    with open(EXPRESSIONS_PATH) as f:
        expressions_data = yaml.safe_load(f)
    expr_map = {e["expression"]: e for e in expressions_data.get("expressions", [])}
    for expr_name, new_synonyms in fixes.get("expression_synonym_additions", {}).items():
        if not new_synonyms:
            continue
        if expr_name not in expr_map:
            skipped.append(f"expression not found: {expr_name}")
            logger.warning("expression not found: %s — skipping", expr_name)
            continue
        existing = set(expr_map[expr_name].get("synonyms", []))
        added = [s for s in new_synonyms if s not in existing]
        expr_map[expr_name].setdefault("synonyms", []).extend(added)
        if added:
            applied.append(f"expression.{expr_name}.synonyms: +{len(added)}")
    tmp = EXPRESSIONS_PATH.with_suffix(".tmp")
    with open(tmp, "w") as f:
        yaml.dump(
            expressions_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False
        )
    tmp.rename(EXPRESSIONS_PATH)

    # ── prompt_patches ───────────────────────────────────────────────────
    for patch in fixes.get("prompt_patches", []):
        find_str = patch.get("find", "")
        replace_str = patch.get("replace", "")
        if not find_str:
            skipped.append(f"prompt_patch missing find string: {patch}")
            continue
        content = PERSONA_SANITIZER_PATH.read_text()
        if find_str not in content:
            skipped.append("patch find-string not in persona_sanitizer.py")
            logger.warning("patch find-string not found in persona_sanitizer.py — skipping")
            continue
        PERSONA_SANITIZER_PATH.write_text(content.replace(find_str, replace_str, 1))
        applied.append("prompt_patch: persona_sanitizer.py")

    fixes["_applied"] = applied
    fixes["_skipped"] = skipped
    _atomic_write(fixes_path, fixes)

    logger.info("Fixes applied: %d  Skipped: %d", len(applied), len(skipped))
    for a in applied:
        logger.info("  + %s", a)
    for s in skipped:
        logger.warning("  ! %s", s)

    return fixes


# ---------------------------------------------------------------------------
# Convergence / plateau helpers
# ---------------------------------------------------------------------------


def _extract_scores(
    summary: dict,
) -> tuple[float, float, float, float, float, float, float]:
    """Return (avg_persona, persona_pass_rate, avg_style, sbs_identity, sbs_goal, sbs_quality, sbs_compound)."""
    return (
        summary.get("avg_persona_score", 0.0),
        summary.get("persona_pass_rate", 0.0),
        summary.get("avg_style_score", 0.0),
        summary.get("avg_sbs_identity", 0.0),
        summary.get("avg_sbs_goal", 0.0),
        summary.get("avg_sbs_quality", 0.0),
        summary.get("avg_sbs_compound", 0.0),
    )


def _print_iteration_status(
    iteration: int,
    max_iterations: int,
    start: int,
    end: int,
    style: str,
    prev: tuple[float, float, float, float, float, float, float] | None,
    curr: tuple[float, float, float, float, float, float, float],
    fixes: dict,
) -> None:
    avg_p, ppr, avg_s, sbs_id, sbs_goal, sbs_qual, sbs_compound = curr
    header = f"=== Iter {iteration}/{max_iterations} | Range {start}-{end} | {style} ==="
    print(f"\n{header}")
    if prev:
        ap_prev, pp_prev, _, sid_prev, sg_prev, sq_prev, sc_prev = prev
        ap_delta = avg_p - ap_prev
        pp_delta = ppr - pp_prev
        print(f"  Avg persona:  {ap_prev:.3f} → {avg_p:.3f} ({ap_delta:+.3f})")
        print(f"  Persona pass: {pp_prev:.0%} → {ppr:.0%} ({pp_delta:+.0%})")
        print(
            f"  SBS:          identity={sid_prev:.0%}→{sbs_id:.0%}  "
            f"goal={sg_prev:.0%}→{sbs_goal:.0%}  quality={sq_prev:.0%}→{sbs_qual:.0%}  "
            f"compound={sc_prev:.0%}→{sbs_compound:.0%}"
        )
    else:
        print(f"  Avg persona:  {avg_p:.3f}")
        print(f"  Persona pass: {ppr:.0%}")
        print(
            f"  SBS:          identity={sbs_id:.0%}  goal={sbs_goal:.0%}  "
            f"quality={sbs_qual:.0%}  compound={sbs_compound:.0%}"
        )

    applied = fixes.get("_applied", [])
    pool_adds = sum(1 for a in applied if "phenotype" in a or "presentation" in a)
    syn_adds = sum(1 for a in applied if "synonyms" in a)
    patch_adds = sum(1 for a in applied if "prompt_patch" in a)
    print(
        f"  Fixes applied: {len(applied)} (pool: {pool_adds}, synonyms: {syn_adds}, patches: {patch_adds})"
    )


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def run_improvement_loop(
    example_range: tuple[int, int],
    style: str,
    target: float,
    max_iterations: int,
    stop_on_plateau: bool,
    gateway_url: str,
    examples_dir: Path,
    workers: int = 3,
    resume_dir: Path | None = None,
    component_threshold: float = 0.80,
    total_threshold: float = 0.90,
) -> None:
    start, end = example_range

    if resume_dir is not None:
        loop_dir = resume_dir.resolve()
        state_path = loop_dir / "state.json"
        if not state_path.exists():
            logger.error("No state.json found in %s", loop_dir)
            sys.exit(1)
        with open(state_path) as f:
            state = json.load(f)
        completed = len(state["iterations"])
        logger.info("Resuming %s — %d iterations already done", loop_dir.name, completed)
        # Restore prev_scores from last completed iteration
        if state["iterations"]:
            last = state["iterations"][-1]
            prev_scores: tuple[float, float, float, float, float, float, float] | None = (
                last["avg_persona"],
                last["persona_pass_rate"],
                last["avg_style"],
                last.get("sbs_identity", 0.0),
                last.get("sbs_goal", 0.0),
                last.get("sbs_quality", 0.0),
                last.get("sbs_compound", 0.0),
            )
        else:
            prev_scores = None
        start_iter = completed + 1
    else:
        ts = datetime.now().strftime("%y-%m-%d-%H-%M")
        loop_dir = REPORTS_DIR / f"loop_{ts}_r{start}-{end}"
        loop_dir.mkdir(parents=True, exist_ok=True)
        state = {
            "range": [start, end],
            "style": style,
            "target": target,
            "loop_dir": str(loop_dir),
            "iterations": [],
        }
        prev_scores = None
        start_iter = 1

    logger.info("Loop dir: %s", loop_dir)
    client = GatewayClient(gateway_url)
    plateau_count = 0
    PLATEAU_DELTA = 0.01

    for iteration in range(start_iter, start_iter + max_iterations):
        prefix = f"iter_{iteration:02d}"

        # ── 1. Benchmark ─────────────────────────────────────────────────
        bench_path = loop_dir / f"{prefix}_benchmark.json"
        logger.info("[iter %d] Running benchmark → %s", iteration, bench_path.name)
        summary = run_benchmark(
            examples_dir=examples_dir,
            gateway_url=gateway_url,
            style_filter=style,
            example_range=example_range,
            runs=1,
            resume=False,
            output_path=bench_path,
            workers=workers,
            component_threshold=component_threshold,
            total_threshold=total_threshold,
        )

        # ── 2. Analysis ──────────────────────────────────────────────────
        analysis_path = loop_dir / f"{prefix}_analysis.json"
        logger.info("[iter %d] Running analysis → %s", iteration, analysis_path.name)
        analysis = run_analysis(
            input_path=bench_path,
            coverage_path=None,
            output_path=analysis_path,
            bottom_n=10,
        )

        curr_scores = _extract_scores(summary)
        avg_p, ppr, avg_s, sbs_id, sbs_goal, sbs_qual, sbs_compound = curr_scores

        # ── 3. Convergence check ─────────────────────────────────────────
        if avg_p >= target and sbs_compound >= target:
            print(f"\n{'=' * 60}")
            print(
                f"SATISFACTORY — persona={avg_p:.3f} >= {target:.2f}  "
                f"sbs_compound={sbs_compound:.3f} >= {target:.2f}"
            )
            print(f"Consider expanding range beyond {start}-{end}.")
            print(f"{'=' * 60}")
            state["iterations"].append(
                {
                    "iter": iteration,
                    "avg_persona": avg_p,
                    "persona_pass_rate": ppr,
                    "avg_style": avg_s,
                    "fixes_applied": 0,
                    "status": "SATISFACTORY",
                }
            )
            _atomic_write(loop_dir / "state.json", state)
            break

        # ── 4. Plateau check ─────────────────────────────────────────────
        if prev_scores is not None:
            delta = avg_p - prev_scores[0]
            if abs(delta) < PLATEAU_DELTA:
                plateau_count += 1
                if plateau_count >= 2:
                    msg = f"PLATEAU — delta={delta:+.3f} for {plateau_count} consecutive iterations"
                    if stop_on_plateau:
                        print(f"\n{msg} — stopping (--stop-on-plateau)")
                        state["iterations"].append(
                            {
                                "iter": iteration,
                                "avg_persona": avg_p,
                                "persona_pass_rate": ppr,
                                "avg_style": avg_s,
                                "fixes_applied": 0,
                                "status": "PLATEAU_STOP",
                            }
                        )
                        _atomic_write(loop_dir / "state.json", state)
                        break
                    else:
                        print(f"\nWARNING: {msg}")
            else:
                plateau_count = 0

        # ── 5. Apply LLM fixes ───────────────────────────────────────────
        fixes_path = loop_dir / f"{prefix}_fixes.json"
        fixes = apply_llm_fixes(client, analysis, fixes_path)

        _print_iteration_status(
            iteration, max_iterations, start, end, style, prev_scores, curr_scores, fixes
        )
        applied_count = len(fixes.get("_applied", []))

        status = "IMPROVING" if (prev_scores is None or avg_p > prev_scores[0]) else "REGRESSING"
        last_iter = iteration == start_iter + max_iterations - 1
        print(f"  Status: {status} — continuing" if not last_iter else f"  Status: {status}")

        state["iterations"].append(
            {
                "iter": iteration,
                "avg_persona": avg_p,
                "persona_pass_rate": ppr,
                "avg_style": avg_s,
                "sbs_identity": sbs_id,
                "sbs_goal": sbs_goal,
                "sbs_quality": sbs_qual,
                "sbs_compound": sbs_compound,
                "fixes_applied": applied_count,
                "status": status,
            }
        )
        _atomic_write(loop_dir / "state.json", state)

        prev_scores = curr_scores
    else:
        # Hit max iterations
        print(f"\nReached max iterations ({max_iterations}).")

    # ── Final summary ────────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print(f"Loop complete — {len(state['iterations'])} iterations")
    print(f"State: {loop_dir / 'state.json'}")
    if state["iterations"]:
        first = state["iterations"][0]["avg_persona"]
        last = state["iterations"][-1]["avg_persona"]
        print(f"Avg persona: {first:.3f} → {last:.3f} ({last - first:+.3f})")

    # Git diff summary of asset changes
    import subprocess

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
    parser = argparse.ArgumentParser(description="Automated improvement loop")
    parser.add_argument(
        "--range",
        type=int,
        nargs=2,
        metavar=("START", "END"),
        required=True,
        help="Inclusive index range of examples (e.g. --range 0 10)",
    )
    parser.add_argument("--style", default="photorealistic", help="Style ID")
    parser.add_argument(
        "--target", type=float, default=0.90, help="Avg persona score target (default 0.90)"
    )
    parser.add_argument(
        "--max-iterations", type=int, default=10, help="Safety cap on iterations (default 10)"
    )
    parser.add_argument(
        "--stop-on-plateau",
        action="store_true",
        help="Stop if improvement delta < 0.01 for 2 consecutive iterations",
    )
    parser.add_argument(
        "--workers", type=int, default=3, help="Parallel benchmark workers (default 3)"
    )
    parser.add_argument(
        "--resume",
        type=Path,
        default=None,
        metavar="LOOP_DIR",
        help="Resume from an existing loop dir (e.g. reports/loop_26-04-07-08-22_r0-10)",
    )
    parser.add_argument("--gateway", default=GATEWAY_URL, help="LLM gateway URL")
    parser.add_argument("--examples-dir", type=Path, default=EXAMPLES_DIR)
    parser.add_argument(
        "--component-threshold",
        type=float,
        default=0.80,
        help="Min per-property and SBS quality score to pass component check (default 0.80)",
    )
    parser.add_argument(
        "--total-threshold",
        type=float,
        default=0.90,
        help="Min persona score and SBS compound score to pass total check (default 0.90)",
    )
    args = parser.parse_args()

    run_improvement_loop(
        example_range=tuple(args.range),  # type: ignore[arg-type]
        style=args.style,
        target=args.target,
        max_iterations=args.max_iterations,
        stop_on_plateau=args.stop_on_plateau,
        gateway_url=args.gateway,
        examples_dir=args.examples_dir,
        workers=args.workers,
        resume_dir=args.resume,
        component_threshold=args.component_threshold,
        total_threshold=args.total_threshold,
    )
