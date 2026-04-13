#! .venv/bin/python3
"""Learn: Reexpress — iterative improvement loop for the reexpress (IP-Adapter) pipeline.

Pipeline flow: source avatar + target expression → ipadapter_faceid → scored candidate.

For each iteration:
  1. Sample examples (--samples / --range / full set)
  2. For each (example, expression) pair, call ipadapter_faceid with the target expression prompt
  3. Score: identity preservation (compare_side_by_side) + expression match (classify_image_expression)
  4. Decide: good improvement → grow N + REASON; below threshold → check plateau or REASON;
     max iterations or plateau reached → FINAL
  5. Repeat until plateau or max-iterations

REASON (mid-iteration): uses client.reasoning() to explore new FACS/synonym fixes.
FINAL (post-loop): uses client.general() to consolidate the best solution from existing ones.

The source image for each example is resolved via --from-source (default: images/photorealistic.png).
If --from-source resolves to a non-PNG file, it is converted to PNG in memory.
Examples missing the from-source file are silently dropped from the candidate pool.

Usage:
    python scripts/learn/learn_reexpress.py --samples 20
    python scripts/learn/learn_reexpress.py --range 0 49 --max-iterations 5 --optimize fast
    python scripts/learn/learn_reexpress.py  # full set — prompts for confirmation
"""

from __future__ import annotations

import argparse
import base64
import io
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
from PIL import Image
from ruamel.yaml import YAML
from tqdm import tqdm


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


# ── project root on sys.path ──────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "examples"))

from _cli import add_common_args, confirm_full_set  # noqa: E402
from _example_utils import EXAMPLES_DIR, REPORTS_DIR, load_all_personas  # noqa: E402
from _logger import make_logger  # noqa: E402
from _sampler import initial_sample, next_sample, score_sample  # noqa: E402

from config.gateway import GatewayClient  # noqa: E402
from pipeline.render.expression_resolver import resolve_expression  # noqa: E402
from pipeline.render.ipadapter.prompt_gen import build_reexpress_params  # noqa: E402
from pipeline.render.style_resolver import STYLES_YML  # noqa: E402
from tuning.classify_expression import classify_image_expression  # noqa: E402
from tuning.classify_style import classify_image_style  # noqa: E402
from tuning.compare_side_by_side import compare_side_by_side  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

EXPRESSIONS_PATH = ROOT / "assets" / "expressions" / "expressions.yml"
IDENTITY_PASS_THRESHOLD = 0.60
EXPRESSION_PASS_THRESHOLD = 0.60
PLATEAU_PATIENCE = 2
MAX_N = 512

DEFAULT_FROM_SOURCE = "images/photorealistic.png"


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


def _check_plateau(score_history: list[float], improve_threshold: float) -> bool:
    """Return True if the last PLATEAU_PATIENCE deltas are all small positive (0 < d < threshold)."""
    if len(score_history) < PLATEAU_PATIENCE + 1:
        return False
    deltas = [score_history[-i] - score_history[-i - 1] for i in range(1, PLATEAU_PATIENCE + 1)]
    return all(0 < d < improve_threshold for d in deltas)


def _load_source_image(example_dir: Path, from_source: str) -> bytes | None:
    """Load the source image for a given example, converting to PNG in memory if needed.

    Returns None if the file does not exist (example will be silently dropped).
    """
    p = example_dir / from_source
    if not p.exists():
        return None
    raw = p.read_bytes()
    if p.suffix.lower() == ".png":
        return raw
    # Convert non-PNG to PNG in memory — no file written to disk
    buf = io.BytesIO()
    Image.open(io.BytesIO(raw)).convert("RGBA").save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Generate + score one (example, expression) pair
# ---------------------------------------------------------------------------


def _process_one(
    client: GatewayClient,
    name: str,
    expression_id: str,
    example_dir: Path,
    from_source: str,
    all_styles: list[dict],
    *,
    optimize: str,
) -> dict:
    result: dict = {"example": name, "expression_id": expression_id, "error": None}

    source_bytes = _load_source_image(example_dir, from_source)
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
    pg = build_reexpress_params(expr_entry)

    # Generate via IP-Adapter
    t0 = time.time()
    try:
        candidate_bytes = client.ipadapter_faceid(
            pg.prompt,
            source_b64,
            negative_prompt=pg.negative_prompt,
            width=pg.width,
            height=pg.height,
            num_inference_steps=pg.num_inference_steps,
            cfg_scale=pg.cfg_scale,
            ip_adapter_scale=pg.ip_adapter_scale,
            lora=pg.lora,
            lora_weight=pg.lora_weight,
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
# LLM fix schemas
# ---------------------------------------------------------------------------

_FIX_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "prompt_gen_patches": {
            "description": "Updates to the reexpress.llm_params section in expressions.yml — the diffusion generation params.",
            "type": "object",
            "properties": {
                "prompt_template": {"type": ["string", "null"]},
                "negative_prompt": {"type": ["string", "null"]},
                "num_inference_steps": {"type": ["integer", "null"]},
                "cfg_scale": {"type": ["number", "null"]},
                "ip_adapter_scale": {"type": ["number", "null"]},
                "lora": {"type": ["string", "null"]},
                "lora_weight": {"type": ["number", "null"]},
            },
            "additionalProperties": False,
        },
        "expression_synonym_additions": {
            "description": "New classifier synonyms per expression name.",
            "type": "object",
            "additionalProperties": {"type": "array", "items": {"type": "string"}},
        },
        "facs_patches": {
            "description": "Find/replace patches to facs_action_units strings in expressions.yml.",
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
        "rationale": {"type": "string"},
    },
    "required": ["prompt_gen_patches", "expression_synonym_additions", "facs_patches", "rationale"],
    "additionalProperties": False,
}


def _apply_expression_patches(fixes: dict) -> tuple[list[str], list[str]]:
    """Apply expression synonym additions and FACS patches. Returns (applied, skipped)."""
    applied: list[str] = []
    skipped: list[str] = []

    yaml_rt = _yaml_rt()
    with open(EXPRESSIONS_PATH) as f:
        expressions_data = yaml_rt.load(f)
    expr_map = {e["expression"]: e for e in expressions_data.get("expressions", [])}

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
        yaml_rt.dump(expressions_data, f)
    tmp.rename(EXPRESSIONS_PATH)

    return applied, skipped


def _parse_fixes_json(raw: str) -> dict:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    return json.loads(text)


_REEXPRESS_YML_PARAMS_KEY = ("reexpress", "llm_params")  # path into each expression entry

# CLIP hard limit is 77 tokens. Target for both prompt_template and negative_prompt is 70
# tokens; 75 is the absolute ceiling (the tokeniser used at runtime may differ slightly from
# the word-count approximation here). For prompt_template we check the template text only —
# {expression_name} and {facs_au_codes} add tokens at runtime. Approximation: word_count * 1.3.
_CLIP_HARD_LIMIT = 77
_CLIP_TARGET = 70
_CLIP_MAX = 75  # reject patches that exceed this


def _clip_tokens_approx(text: str) -> int:
    """Approximate CLIP token count: word_count * 1.3, rounded up."""
    return int(len(text.split()) * 1.3) + 1


def _apply_prompt_gen_patches(patches: dict) -> list[str]:
    """Apply prompt_gen_patches to reexpress.llm_params for ALL expressions in expressions.yml."""
    if not patches:
        return []
    yaml_rt = _yaml_rt()
    with open(EXPRESSIONS_PATH) as f:
        data = yaml_rt.load(f)
    applied: list[str] = []
    for expr in data.get("expressions", []):
        expr_name = expr.get("expression", "?")
        llm_params = (expr.get("reexpress") or {}).get("llm_params")
        if llm_params is None:
            continue
        for key, value in patches.items():
            if value is None:
                continue
            # Validate CLIP token budget for text fields before writing
            if key in ("prompt_template", "negative_prompt") and isinstance(value, str):
                approx = _clip_tokens_approx(value)
                if approx > _CLIP_MAX:
                    logger.warning(
                        "Skipping %s patch — estimated %d tokens exceeds hard limit %d "
                        "(target is %d). Shorten and retry.",
                        key,
                        approx,
                        _CLIP_MAX,
                        _CLIP_TARGET,
                    )
                    continue
            old = llm_params.get(key)
            llm_params[key] = value
            applied.append(
                f"expressions.yml[{expr_name}].reexpress.llm_params.{key}: {old!r} → {value!r}"
            )
    if applied:
        tmp = EXPRESSIONS_PATH.with_suffix(".tmp")
        with open(tmp, "w") as f:
            yaml_rt.dump(data, f)
        try:
            yaml.safe_load(tmp.read_text())
        except yaml.YAMLError as exc:
            tmp.unlink(missing_ok=True)
            logger.warning("Skipping prompt_gen patches — YAML validation failed: %s", exc)
            return []
        tmp.rename(EXPRESSIONS_PATH)
    return applied


# ---------------------------------------------------------------------------
# REASON: LLM fix for reexpress (mid-iteration — explore new solutions)
# ---------------------------------------------------------------------------


def _apply_reexpress_fixes(
    client: GatewayClient,
    entries: list[dict],
    fixes_path: Path,
    component_threshold: float = 0.75,
    max_reason_changes: int = 3,
) -> dict:
    """REASON step: uses client.reasoning() to explore new FACS/synonym fixes."""
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

    # Show the current reexpress.llm_params (shared across all expressions — first entry is representative)
    exprs_data = yaml.safe_load(expressions_content)
    first_expr = (exprs_data.get("expressions") or [{}])[0]
    reexpress_lp = (first_expr.get("reexpress") or {}).get("llm_params") or {}
    prompt_gen_content = yaml.dump(
        reexpress_lp, default_flow_style=False, sort_keys=False, allow_unicode=True
    )

    reasoning_prompt = textwrap.dedent(f"""
        You are improving the avatar-studio reexpress pipeline (IP-Adapter FaceID based).
        The reexpress pipeline changes the expression of an existing avatar.

        ## Failures (expr score < {component_threshold:.0%} or identity score < {component_threshold:.0%})
        {failure_summary or "(none)"}

        ## Current reexpress.llm_params (diffusion generation params — shared across all expressions)
        {prompt_gen_content}

        ## Current expressions.yml
        {expressions_content}

        Diffusion parameter effects:
        - ip_adapter_scale: 0.4–0.9 — higher = stronger face identity, lower = more expression freedom
        - cfg_scale: 5–12 — higher = more prompt-adherent, lower = more natural variation
        - num_inference_steps: 15–50 — more steps = higher quality/detail but slower
        - negative_prompt: what to suppress — directly reduces artifact rate
        - prompt_template: CLIP text; {{expression_name}} and {{facs_au_codes}} filled per expression

        CLIP 77-token hard limit (CRITICAL): each prompt (positive and negative) must be
        ≤ 70 tokens — 75 is the absolute ceiling but the runtime tokeniser may differ.
        For prompt_template, this is the RENDERED length (template + filled {{expression_name}}
        and {{facs_au_codes}}); keep the template text to ~45 tokens so the variables have room.
        Use comma-separated keywords for negative_prompt; avoid full sentences.

        Analyze:
        1. Which expressions consistently fail? What top label does the classifier return instead?
        2. Are there synonyms missing that would help the classifier recognize the expression?
        3. Should any FACS action_units be adjusted for better visual signal?
        4. Which reexpress.yml param changes would most improve expression accuracy or identity?

        Be specific and reference exact strings from the configs shown above.
    """).strip()

    schema_json = json.dumps(_FIX_SCHEMA, indent=2)
    format_prompt = textwrap.dedent(f"""
        Based on the analysis below, produce a JSON fix specification.

        ANALYSIS:
        {{reasoning}}

        OUTPUT SCHEMA (single valid JSON object, no prose):
        {schema_json}

        Rules:
        - prompt_gen_patches: fields to update in reexpress.llm_params (in expressions.yml); set a field to null to leave it unchanged
        - expression_synonym_additions: {{expression_name: [new_synonyms]}} — exact name from expressions.yml
        - facs_patches: find/replace patches to facs_action_units strings in expressions.yml
        - Leave prompt_gen_patches fields null and arrays empty if no changes needed.
        - CLIP token limit: each prompt (positive and negative) must be ≤ 70 tokens.
            75 is the absolute hard crash limit; the runtime tokeniser may differ slightly.
            For prompt_template: count the rendered text (template + filled {{expression_name}}
            and {{facs_au_codes}}); keep template text ≤ ~45 tokens so the variables have room.
            For negative_prompt: ≤ 70 tokens. Use comma-separated keywords, not sentences.
            A 10-word phrase ≈ 13 tokens. If in doubt, cut.
        - IMPORTANT: propose changes to AT MOST {max_reason_changes} properties in total across
          prompt_gen_patches, expression_synonym_additions, and facs_patches combined. Choose the
          single most impactful change first; leave all other fields null or empty. Changing many
          parameters at once makes it impossible to know which change caused any improvement or
          regression.
    """).strip()

    applied: list[str] = []
    skipped: list[str] = []
    fixes: dict = {
        "prompt_gen_patches": {},
        "expression_synonym_additions": {},
        "facs_patches": [],
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
        fixes = _parse_fixes_json(raw)
    except Exception as exc:
        logger.error("Format model failed: %s", exc)
        fixes["_error"] = str(exc)
        fixes["_applied"] = applied
        fixes["_skipped"] = skipped
        _atomic_write(fixes_path, fixes)
        return fixes

    fixes["_reasoning"] = reasoning_output[:2000]

    # Enforce max_reason_changes: count total proposed changes and warn if over limit.
    pg_patches = fixes.get("prompt_gen_patches") or {}
    synonym_adds = fixes.get("expression_synonym_additions") or {}
    facs_patches = fixes.get("facs_patches") or []
    non_null_pg = [(k, v) for k, v in pg_patches.items() if v is not None]
    n_synonym_exprs = sum(1 for synonyms in synonym_adds.values() if synonyms)
    total_proposed = len(non_null_pg) + n_synonym_exprs + len(facs_patches)
    if total_proposed > max_reason_changes:
        logger.warning(
            "REASON proposed %d changes (limit=%d) — truncating to %d most important",
            total_proposed,
            max_reason_changes,
            max_reason_changes,
        )
        budget = max_reason_changes
        allowed_pg = dict(non_null_pg[:budget])
        budget -= len(allowed_pg)
        for k in pg_patches:
            if k not in allowed_pg:
                pg_patches[k] = None
        fixes["prompt_gen_patches"] = pg_patches
        # Trim synonym additions
        allowed_synonyms: dict[str, list[str]] = {}
        for expr_name, syns in synonym_adds.items():
            if budget <= 0:
                break
            if syns:
                allowed_synonyms[expr_name] = syns
                budget -= 1
        fixes["expression_synonym_additions"] = allowed_synonyms
        fixes["facs_patches"] = facs_patches[:budget]

    pg_applied = _apply_prompt_gen_patches(fixes.get("prompt_gen_patches") or {})
    expr_applied, skipped = _apply_expression_patches(fixes)
    applied = pg_applied + expr_applied
    fixes["_applied"] = applied
    fixes["_skipped"] = skipped
    _atomic_write(fixes_path, fixes)

    logger.info("Reexpress fixes applied: %d  Skipped: %d", len(applied), len(skipped))
    for change in applied:
        logger.info("  applied: %s", change)
    return fixes


# ---------------------------------------------------------------------------
# FINAL: consolidation pass (post-loop — select from existing solutions)
# ---------------------------------------------------------------------------


def _apply_reexpress_final(
    client: GatewayClient,
    iteration_history: list[dict],
    fixes_path: Path,
) -> dict:
    """FINAL step: uses client.general() only — consolidates best solution, does not explore."""
    history_lines = []
    for h in iteration_history:
        impr = h.get("improvement")
        impr_str = f"+{impr:.1%}" if impr is not None else "n/a (first)"
        history_lines.append(
            f"Iter {h['iteration']}: combined={h['score']:.1%}  delta={impr_str}  "
            f"applied={h.get('applied', [])}\n  reasoning: {(h.get('reasoning') or '')[:400]}"
        )
    history_text = "\n\n".join(history_lines) if history_lines else "(no iterations completed)"

    with open(EXPRESSIONS_PATH) as f:
        expressions_content = f.read()

    schema_json = json.dumps(_FIX_SCHEMA, indent=2)
    prompt = textwrap.dedent(f"""
        You are finalizing the avatar-studio reexpress pipeline after
        {len(iteration_history)} improvement iteration(s).

        ## Iteration history (all REASON steps applied so far)
        {history_text}

        ## Current expressions.yml (after all iterations)
        {expressions_content}

        ## Your task: CONSOLIDATE — do NOT explore new ideas
        Review the trajectory. Your job is to select and lock in the best configuration
        from what has already been tested.

        - If combined scores improved consistently: current state is correct.
          Leave ALL arrays empty and confirm the final state in rationale.
        - If a specific iteration caused regression: suggest reverting ONLY those exact
          FACS changes or synonym additions using the patch fields.
        - Do NOT propose new FACS codes, synonyms, or weight values not already tested.

        OUTPUT SCHEMA (single valid JSON object, no prose):
        {schema_json}
    """).strip()

    logger.info(
        "FINAL: general model consolidating %d iteration(s) for reexpress…",
        len(iteration_history),
    )

    fixes: dict = {
        "prompt_gen_patches": {},
        "expression_synonym_additions": {},
        "facs_patches": [],
        "rationale": "",
    }

    try:
        raw = client.general(
            messages=[{"role": "user", "content": prompt}],
            timeout=180,
        )
        fixes = _parse_fixes_json(raw)
    except Exception as exc:
        logger.error("FINAL general model failed: %s", exc)
        fixes["_error"] = str(exc)
        fixes["_applied"] = []
        fixes["_skipped"] = []
        _atomic_write(fixes_path, fixes)
        return fixes

    pg_applied = _apply_prompt_gen_patches(fixes.get("prompt_gen_patches") or {})
    expr_applied, skipped = _apply_expression_patches(fixes)
    applied = pg_applied + expr_applied
    fixes["_applied"] = applied
    fixes["_skipped"] = skipped
    _atomic_write(fixes_path, fixes)

    logger.info("FINAL complete — applied: %d  skipped: %d", len(applied), len(skipped))
    for change in applied:
        logger.info("  applied: %s", change)
    return fixes


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def run_learn_reexpress(
    *,
    max_iterations: int,
    stop_on_plateau: bool,
    improve_threshold: float,
    gateway_url: str,
    examples_dir: Path,
    workers: int,
    optimize: str,
    log_dir: Path,
    samples: int | None,
    range_: tuple[int, int] | None,
    from_source: str = DEFAULT_FROM_SOURCE,
    component_threshold: float = 0.75,
    compound_threshold: float = 0.90,
    max_reason_changes: int = 3,
) -> None:
    log = make_logger("learn_reexpress", log_dir)

    all_examples = load_all_personas(examples_dir)
    # Filter to examples that have the from_source file
    all_examples = [(n, p) for n, p in all_examples if (examples_dir / n / from_source).exists()]
    if not all_examples:
        logger.error("No examples with '%s' found in %s", from_source, examples_dir)
        sys.exit(1)

    if samples is None and range_ is None:
        confirm_full_set(len(all_examples))

    current_sample = initial_sample(all_examples, n=samples, range_=range_)
    current_n = len(current_sample)

    all_expressions = [e["expression"].lower() for e in _load_expressions()]
    all_styles = _load_styles()

    ts = datetime.now().strftime("%y-%m-%d-%H-%M")
    loop_dir = REPORTS_DIR / f"learn_reexpress_{ts}"
    loop_dir.mkdir(parents=True, exist_ok=True)

    log.config(
        script="learn_reexpress",
        max_iterations=max_iterations,
        stop_on_plateau=stop_on_plateau,
        improve_threshold=improve_threshold,
        workers=workers,
        optimize=optimize,
        from_source=from_source,
        samples=current_n,
        expressions=all_expressions,
        loop_dir=str(loop_dir),
        max_reason_changes=max_reason_changes,
    )

    logger.info(
        "learn_reexpress: samples=%d  expressions=%s  max_iter=%d"
        "  improve_threshold=%.0f%%  optimize=%s",
        current_n,
        all_expressions,
        max_iterations,
        improve_threshold * 100,
        optimize,
    )
    for expr_id in all_expressions:
        expr_entry = resolve_expression(expr_id)
        pg = build_reexpress_params(expr_entry)
        logger.info("  [%s] prompt_gen params:", expr_id)
        for line in pg.log_lines():
            logger.info(line)

    client = GatewayClient(gateway_url)
    score_history: list[float] = []
    iteration_history: list[dict] = []
    state: dict = {"loop_dir": str(loop_dir), "iterations": []}
    prev_pg: dict | None = None  # previous iteration's prompt_gen params for diff

    for iteration in range(1, max_iterations + 1):
        prefix = f"iter_{iteration:02d}"
        work = [
            (name, persona, expr_id)
            for name, persona in current_sample
            for expr_id in all_expressions
        ]
        entries: list[dict] = []

        logger.info("[iter %d/%d] Generating %d images…", iteration, max_iterations, len(work))
        for expr_id in all_expressions:
            expr_entry = resolve_expression(expr_id)
            pg = build_reexpress_params(expr_entry)
            pg_dict = {
                "prompt_template": pg.prompt,
                "negative_prompt": pg.negative_prompt,
                "num_inference_steps": pg.num_inference_steps,
                "cfg_scale": pg.cfg_scale,
                "ip_adapter_scale": pg.ip_adapter_scale,
                "lora": pg.lora,
                "lora_weight": pg.lora_weight,
            }
            if prev_pg is None:
                logger.info("  [%s] prompt_gen params:", expr_id)
                for line in pg.log_lines():
                    logger.info(line)
            else:
                changed = {
                    k: (prev_pg.get(k), v) for k, v in pg_dict.items() if prev_pg.get(k) != v
                }
                if changed:
                    logger.info("  [%s] prompt_gen CHANGED:", expr_id)
                    for k, (old, new) in changed.items():
                        logger.info("    %s: %r → %r", k, old, new)
                else:
                    logger.info("  [%s] prompt_gen unchanged", expr_id)
            prev_pg = pg_dict

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
                    client,
                    name,
                    expr_id,
                    examples_dir / name,
                    from_source,
                    all_styles,
                    optimize=optimize,
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
                        from_source,
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

        # Scored sample for next iteration
        example_scores = {e["example"]: e.get("expression_score", 0.0) for e in successful}
        prev_scored = score_sample(current_sample, example_scores)

        improvement = (
            score_history[-1] - score_history[-2] if len(score_history) >= 2 else float("inf")
        )

        # ── FINAL: max iterations reached ────────────────────────────────
        if iteration == max_iterations:
            logger.info("[iter %d] Max iterations reached — running FINAL", iteration)
            final_path = loop_dir / f"{prefix}_final.json"
            final = _apply_reexpress_final(client, iteration_history, final_path)
            for fix_desc in final.get("_applied", []):
                log.fix(iteration=iteration, description=f"[FINAL] {fix_desc}")
            log.done(reason="max_iterations", iteration=iteration)
            state["iterations"].append(
                {"iter": iteration, "combined": combined, "status": "MAX_ITERATIONS"}
            )
            _atomic_write(loop_dir / "state.json", state)
            break

        # ── FINAL: plateau reached ────────────────────────────────────────
        if (
            improvement < improve_threshold
            and stop_on_plateau
            and _check_plateau(score_history, improve_threshold)
        ):
            logger.info(
                "[iter %d] Plateau detected (delta=%.1f%%) — running FINAL",
                iteration,
                improvement * 100,
            )
            final_path = loop_dir / f"{prefix}_final.json"
            final = _apply_reexpress_final(client, iteration_history, final_path)
            for fix_desc in final.get("_applied", []):
                log.fix(iteration=iteration, description=f"[FINAL] {fix_desc}")
            log.plateau(iteration=iteration, score_history=score_history)
            log.done(reason="plateau", iteration=iteration)
            state["iterations"].append(
                {"iter": iteration, "combined": combined, "status": "PLATEAU_STOP"}
            )
            _atomic_write(loop_dir / "state.json", state)
            break

        # ── REASON ───────────────────────────────────────────────────────
        fixes_path = loop_dir / f"{prefix}_fixes.json"
        fixes = _apply_reexpress_fixes(
            client,
            entries,
            fixes_path,
            component_threshold=component_threshold,
            max_reason_changes=max_reason_changes,
        )
        for fix_desc in fixes.get("_applied", []):
            log.fix(iteration=iteration, description=fix_desc)

        iteration_history.append(
            {
                "iteration": iteration,
                "score": combined,
                "improvement": improvement if improvement != float("inf") else None,
                "reasoning": fixes.get("_reasoning", ""),
                "applied": fixes.get("_applied", []),
            }
        )

        # ── Next sample: grow N on good improvement, keep N otherwise ────
        if improvement >= improve_threshold:
            next_n = min(MAX_N, current_n * 2)
            logger.info(
                "[iter %d] Good improvement (%.1f%%) — growing N: %d → %d",
                iteration,
                improvement * 100,
                current_n,
                next_n,
            )
        else:
            next_n = current_n
            logger.info(
                "[iter %d] Below threshold (%.1f%%) — keeping N=%d",
                iteration,
                improvement * 100,
                current_n,
            )

        current_sample = next_sample(all_examples, prev_scored=prev_scored, target_n=next_n)
        current_n = next_n

        state["iterations"].append(
            {
                "iter": iteration,
                "avg_expression": round(avg_expr, 3),
                "avg_identity": round(avg_identity, 3),
                "combined": round(combined, 3),
                "improvement": round(improvement, 4) if improvement != float("inf") else None,
                "fixes_applied": len(fixes.get("_applied", [])),
                "next_n": next_n,
                "status": "IMPROVING",
            }
        )
        _atomic_write(loop_dir / "state.json", state)

    print(f"\n{'=' * 60}")
    print(f"learn_reexpress complete — {len(state['iterations'])} iterations")
    print(f"State: {loop_dir / 'state.json'}")
    print(f"Log:   {log._path}")

    print(f"\n{'=' * 60}")
    print(f"learn_reexpress complete — {len(state['iterations'])} iterations")
    print(f"State: {loop_dir / 'state.json'}")
    print(f"Log:   {log._path}")

    # Per-iteration applied-changes summary — shows exactly what the LLM changed and why
    if iteration_history:
        print(f"\n{'─' * 60}")
        print("Applied changes per iteration:")
        for h in iteration_history:
            impr = h.get("improvement")
            impr_str = f"+{impr:.1%}" if impr is not None else "(first)"
            print(f"  Iter {h['iteration']:2d}: combined={h['score']:.0%}  delta={impr_str}")
            for change in h.get("applied", []):
                print(f"    + {change}")
            if not h.get("applied"):
                print("    (no changes applied)")
            rationale = (h.get("reasoning") or "")[:200].strip()
            if rationale:
                print(f"    rationale: {rationale}")

    # Full diff of asset files so the user can decide what to keep
    diff = subprocess.run(["git", "diff", "assets/"], capture_output=True, text=True, cwd=ROOT)
    if diff.stdout.strip():
        print(f"\n{'─' * 60}")
        print("Asset changes to review (git diff assets/):")
        print(diff.stdout.strip())
        print(f"\n{'─' * 60}")
        print("Commit all:      git add assets/ && git commit")
        print("Cherry-pick:     git add -p assets/")
        print("Discard all:     git checkout assets/")
    else:
        print("\n(no asset changes — nothing to commit)")


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
        improve_threshold=args.improve_threshold,
        gateway_url=args.gateway,
        examples_dir=args.examples_dir,
        workers=args.workers,
        optimize=args.optimize,
        log_dir=args.log_dir,
        samples=args.samples,
        range_=tuple(args.range) if args.range else None,
        from_source=args.from_source or DEFAULT_FROM_SOURCE,
        component_threshold=args.component_threshold,
        compound_threshold=args.compound_threshold,
        max_reason_changes=args.max_reason_changes,
    )
