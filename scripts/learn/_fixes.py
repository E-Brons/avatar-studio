"""LLM fix engine — reason about benchmark failures, produce structured asset patches.

Two-step pipeline (REASON/mid-iteration):
  1. reasoning()  (claude-opus) — free-form exploration of failures; higher temperature
  2. general()    (claude-sonnet) — format reasoning into structured JSON

One-step pipeline (FINAL/post-loop):
  1. general()    (claude-sonnet) — consolidation only; lower temperature; selects from
     existing solutions rather than proposing new ones

Applies fixes to:
  - assets/persona/phenotype_settings.json
  - assets/persona/presentation_settings.json
  - assets/expressions/expressions.yml (synonyms)
  - src/pipeline/render/llm/persona_sanitizer.py (prompt patches)
"""

from __future__ import annotations

import json
import logging
import re
import textwrap
from pathlib import Path

import yaml
from ruamel.yaml import YAML


def _yaml_rt() -> YAML:
    """Return a ruamel YAML instance configured for round-trip writes that preserve formatting."""
    y = YAML()
    y.preserve_quotes = True
    y.indent(mapping=2, sequence=4, offset=2)
    y.width = 2**16
    y.Representer.add_representer(
        type(None), lambda self, _: self.represent_scalar("tag:yaml.org,2002:null", "null")
    )
    return y


logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]

PHENOTYPE_PATH = ROOT / "assets" / "persona" / "phenotype_settings.json"
PRESENTATION_PATH = ROOT / "assets" / "persona" / "presentation_settings.json"
EXPRESSIONS_PATH = ROOT / "assets" / "expressions" / "expressions.yml"
PERSONA_SANITIZER_PATH = ROOT / "src" / "pipeline" / "render" / "llm" / "persona_sanitizer.py"

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
# Asset loaders
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def _atomic_write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp.rename(path)


def _load_synonyms_section() -> str:
    with open(EXPRESSIONS_PATH) as f:
        data = yaml.safe_load(f)
    lines = []
    for expr in data.get("expressions", []):
        name = expr.get("expression", "")
        synonyms = expr.get("synonyms", [])
        lines.append(f"  {name}: {synonyms}")
    return "\n".join(lines)


def _compact_phenotype() -> str:
    data = _load_json(PHENOTYPE_PATH)
    data = {k: v for k, v in data.items() if k != "palette"}
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


def _compact_presentation() -> str:
    return json.dumps(_load_json(PRESENTATION_PATH), separators=(",", ":"), ensure_ascii=False)


def _sanitizer_dicts_only() -> str:
    lines = PERSONA_SANITIZER_PATH.read_text().splitlines()
    cutoff = next(
        (i for i, line in enumerate(lines) if "def _enrich_skin_tone" in line),
        len(lines),
    )
    return "\n".join(lines[:cutoff]).strip()


# ---------------------------------------------------------------------------
# Patch application (shared between REASON and FINAL)
# ---------------------------------------------------------------------------


def _apply_patches(fixes: dict) -> tuple[list[str], list[str]]:
    """Apply all patches in *fixes* to asset files. Returns (applied, skipped) lists."""
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
    _atomic_write_json(PHENOTYPE_PATH, phenotype)

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
    _atomic_write_json(PRESENTATION_PATH, presentation)

    # ── expression_synonym_additions ─────────────────────────────────────
    yaml_rt = _yaml_rt()
    with open(EXPRESSIONS_PATH) as f:
        expressions_data = yaml_rt.load(f)
    expr_map = {e["expression"]: e for e in expressions_data.get("expressions", [])}
    for expr_name, new_synonyms in fixes.get("expression_synonym_additions", {}).items():
        if not new_synonyms:
            continue
        if expr_name not in expr_map:
            skipped.append(f"expression not found: {expr_name}")
            logger.warning("expression not found: %s — skipping", expr_name)
            continue
        existing_syns = set(expr_map[expr_name].get("synonyms", []))
        added_syns = [s for s in new_synonyms if s not in existing_syns]
        expr_map[expr_name].setdefault("synonyms", []).extend(added_syns)
        if added_syns:
            applied.append(f"expression.{expr_name}.synonyms: +{len(added_syns)}")
    tmp = EXPRESSIONS_PATH.with_suffix(".tmp")
    with open(tmp, "w") as f:
        yaml_rt.dump(expressions_data, f)
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

    logger.info("Fixes applied: %d  Skipped: %d", len(applied), len(skipped))
    for a in applied:
        logger.info("  + %s", a)
    for s in skipped:
        logger.warning("  ! %s", s)

    return applied, skipped


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------


def _build_reasoning_prompt(analysis: dict) -> str:
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


def _format_iteration_history(iteration_history: list[dict]) -> str:
    """Format iteration history for inclusion in the FINAL prompt."""
    if not iteration_history:
        return "(no iterations completed)"
    lines = []
    for h in iteration_history:
        impr = h.get("improvement")
        impr_str = f"+{impr:.1%}" if impr is not None else "n/a (first)"
        applied = h.get("applied", [])
        reasoning_snippet = (h.get("reasoning") or "")[:400]
        lines.append(
            f"Iter {h['iteration']}: score={h['score']:.1%}  delta={impr_str}  "
            f"applied={applied}\n  reasoning: {reasoning_snippet}"
        )
    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------


def apply_llm_fixes(
    client: object,  # GatewayClient
    analysis: dict,
    fixes_path: Path,
) -> dict:
    """Two-step LLM fix (REASON/mid-iteration): reasoning model explores, general model formats.

    Uses client.reasoning() for free-form exploration (higher temperature) followed by
    client.general() to format the output into a structured JSON patch.
    """
    # ── Step 1: reasoning model ───────────────────────────────────────────
    reasoning_prompt = _build_reasoning_prompt(analysis)
    logger.info("Step 1: reasoning model (claude-opus) analyzing failures…")
    try:
        reasoning_output = client.reasoning(  # type: ignore[attr-defined]
            messages=[{"role": "user", "content": reasoning_prompt}],
            timeout=600,
        )
        logger.info("Reasoning complete (%d chars)", len(reasoning_output))
    except Exception as exc:
        logger.error("Reasoning model failed (%s) — skipping LLM fixes this iteration", exc)
        return {"_error": str(exc), "_applied": [], "_skipped": []}

    # ── Step 2: general model ─────────────────────────────────────────────
    format_prompt = _build_format_prompt(reasoning_output)
    logger.info("Step 2: general model (claude-sonnet) formatting fixes as JSON…")
    try:
        raw = client.general(  # type: ignore[attr-defined]
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
        return {
            "_error": str(exc),
            "_reasoning": reasoning_output[:2000],
            "_applied": [],
            "_skipped": [],
        }

    fixes["_reasoning"] = reasoning_output[:2000]

    applied, skipped = _apply_patches(fixes)
    fixes["_applied"] = applied
    fixes["_skipped"] = skipped
    _atomic_write_json(fixes_path, fixes)

    return fixes


def apply_llm_final(
    client: object,  # GatewayClient
    iteration_history: list[dict],
    fixes_path: Path,
) -> dict:
    """Final consolidation pass (FINAL/post-loop): uses client.general() only.

    Does NOT call client.reasoning() — this step selects from solutions already produced
    rather than exploring new ones. Lower temperature / deterministic by design.

    Parameters
    ----------
    iteration_history:
        List of dicts from previous REASON iterations, each containing:
        ``iteration``, ``score``, ``improvement``, ``reasoning``, ``applied``.
    fixes_path:
        Path to write the final fixes JSON.
    """
    history_text = _format_iteration_history(iteration_history)
    phenotype_json = _compact_phenotype()
    presentation_json = _compact_presentation()
    synonyms_text = _load_synonyms_section()
    sanitizer_content = _sanitizer_dicts_only()
    schema_json = json.dumps(_FIX_SCHEMA, indent=2)

    prompt = textwrap.dedent(f"""
        You are finalizing the avatar-studio create pipeline after
        {len(iteration_history)} improvement iteration(s).

        ## Iteration history (all REASON steps applied so far)
        {history_text}

        ## Current state of config files (after all iterations)
        phenotype_settings.json (palette excluded): {phenotype_json}
        presentation_settings.json: {presentation_json}
        expression synonyms: {synonyms_text}
        persona_sanitizer.py (dicts only): {sanitizer_content}

        ## Your task: CONSOLIDATE — do NOT explore new ideas
        Review the trajectory above. Your job is to select and lock in the best configuration
        from what has already been tested, not to propose new experimental changes.

        - If scores improved consistently across iterations: the current state is correct.
          Leave ALL arrays empty and write a rationale confirming the final state.
        - If a specific iteration caused regression (score went down after its changes):
          suggest reverting ONLY those exact changes using find/replace patches.
        - Do NOT add phenotype values, synonyms, or prompt patches that were not already
          proposed in the iteration history above.

        OUTPUT SCHEMA (single valid JSON object, no prose):
        {schema_json}
    """).strip()

    logger.info("FINAL: general model consolidating %d iteration(s)…", len(iteration_history))
    try:
        raw = client.general(  # type: ignore[attr-defined]
            messages=[{"role": "user", "content": prompt}],
            output_config=_FIX_OUTPUT_CONFIG,
            timeout=180,
        )
    except Exception as exc:
        logger.error("FINAL general model failed (%s)", exc)
        result = {"_error": str(exc), "_applied": [], "_skipped": []}
        _atomic_write_json(fixes_path, result)
        return result

    try:
        text = raw.strip()
        fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if fence:
            text = fence.group(1).strip()
        fixes: dict = json.loads(text)
    except Exception as exc:
        logger.error("FINAL failed to parse JSON (%s)", exc)
        result = {"_error": str(exc), "_applied": [], "_skipped": []}
        _atomic_write_json(fixes_path, result)
        return result

    applied, skipped = _apply_patches(fixes)
    fixes["_applied"] = applied
    fixes["_skipped"] = skipped
    _atomic_write_json(fixes_path, fixes)

    logger.info("FINAL complete — applied: %d  skipped: %d", len(applied), len(skipped))
    return fixes
