#! .venv/bin/python3
"""Learn: Restyle — iterative improvement loop for the restyle (IP-Adapter) pipeline.

Pipeline flow: source avatar + target style → ipadapter_faceid → scored candidate.

For each iteration:
  1. Sample examples (--samples / --range / full set)
  2. For each example, call ipadapter_faceid to generate a restyled image
  3. Score: identity preservation (compare_side_by_side) + style match (classify_image_style)
  4. Decide: good improvement → grow N + REASON; below threshold → check plateau or REASON;
     max iterations or plateau reached → FINAL
  5. Repeat until plateau or max-iterations

REASON (mid-iteration): uses client.reasoning() to explore new style prompt fixes.
FINAL (post-loop): uses client.general() to consolidate the best solution from existing ones.

The source image for each example is resolved via --from-source (default: images/photorealistic.png).
If --from-source resolves to a non-PNG file, it is converted to PNG in memory.
Examples missing the from-source file are silently dropped from the candidate pool.

Usage:
    python scripts/learn/learn_restyle.py --samples 20
    python scripts/learn/learn_restyle.py --range 0 49 --max-iterations 5 --optimize fast
    python scripts/learn/learn_restyle.py  # full set — prompts for confirmation
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
from tqdm import tqdm

# ── project root on sys.path ──────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "examples"))

from _cli import add_common_args, confirm_full_set  # noqa: E402
from _example_utils import EXAMPLES_DIR, REPORTS_DIR, load_all_personas  # noqa: E402
from _logger import make_logger  # noqa: E402
from _sampler import initial_sample, next_sample, score_sample  # noqa: E402

from config.gateway import GatewayClient  # noqa: E402
from pipeline.render.ipadapter.prompt_gen import build_restyle_params  # noqa: E402
from pipeline.render.style_resolver import resolve_style  # noqa: E402
from tuning.classify_style import classify_image_style  # noqa: E402
from tuning.compare_side_by_side import compare_side_by_side  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

STYLES_YML = ROOT / "assets" / "styles" / "styles.yml"
STYLE_PASS_THRESHOLD = 0.66
IDENTITY_PASS_THRESHOLD = 0.60
PLATEAU_PATIENCE = 2
MAX_N = 512

DEFAULT_FROM_SOURCE = "images/photorealistic.png"

_NEUTRAL_EXPR = {
    "expression": "Neutral",
    "facs_action_units": "",
    "description": "Resting face, relaxed muscles, eyes looking directly forward, mouth closed.",
}

_FIX_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "prompt_gen_patches": {
            "description": "Updates to assets/prompt_gen/restyle.yml — the diffusion generation params.",
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
        "style_prompt_patches": {
            "description": "Updates to system_prompt strings in styles.yml (affects classifier, not generation).",
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "style_id": {"type": "string"},
                    "find": {"type": "string"},
                    "replace": {"type": "string"},
                },
                "required": ["style_id", "find", "replace"],
                "additionalProperties": False,
            },
        },
        "rationale": {"type": "string"},
    },
    "required": ["prompt_gen_patches", "style_prompt_patches", "rationale"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_styles() -> list[dict]:
    with open(STYLES_YML) as f:
        data = yaml.safe_load(f)
    return [s for s in data["styles"] if s.get("engine") == "llm" and s.get("id") != "random"]


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


def _parse_fixes_json(raw: str) -> dict:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    return json.loads(text)


def _apply_style_patches(fixes: dict) -> tuple[list[str], list[str]]:
    """Apply style prompt patches to styles.yml. Returns (applied, skipped)."""
    applied: list[str] = []
    skipped: list[str] = []

    with open(STYLES_YML) as f:
        styles_text = f.read()
    original = styles_text

    for patch in fixes.get("style_prompt_patches", []):
        find_str = patch.get("find", "")
        replace_str = patch.get("replace", "")
        if not find_str:
            skipped.append(f"empty find string for style {patch.get('style_id')}")
            continue
        if find_str not in styles_text:
            skipped.append(f"find string not found in styles.yml for {patch.get('style_id')}")
            continue
        candidate = styles_text.replace(find_str, replace_str, 1)
        try:
            yaml.safe_load(candidate)
        except yaml.YAMLError as exc:
            skipped.append(f"patch for {patch.get('style_id')} would corrupt YAML: {exc} — skipped")
            logger.warning(
                "Skipping patch for %s — result would be invalid YAML: %s",
                patch.get("style_id"),
                exc,
            )
            continue
        styles_text = candidate
        applied.append(f"styles.yml patch: {patch.get('style_id')}")

    if styles_text != original:
        tmp = STYLES_YML.with_suffix(".tmp")
        tmp.write_text(styles_text)
        tmp.rename(STYLES_YML)

    return applied, skipped


_RESTYLE_CONFIG = ROOT / "assets" / "prompt_gen" / "restyle.yml"

# CLIP hard limit is 77 tokens. Target for both prompt_template and negative_prompt is 70
# tokens; 75 is the absolute ceiling (the tokeniser used at runtime may differ slightly from
# the word-count approximation here). For prompt_template we check the template text only —
# {style_description} adds tokens at runtime, so the template itself must stay well below 70.
# Approximation: word_count * 1.3 (conservative CLIP BPE estimate).
_CLIP_HARD_LIMIT = 77
_CLIP_TARGET = 70
_CLIP_MAX = 75  # reject patches that exceed this


def _clip_tokens_approx(text: str) -> int:
    """Approximate CLIP token count: word_count * 1.3, rounded up."""
    return int(len(text.split()) * 1.3) + 1


def _apply_prompt_gen_patches(patches: dict) -> list[str]:
    """Apply prompt_gen_patches to assets/prompt_gen/restyle.yml. Returns list of applied changes."""
    if not patches:
        return []
    cfg = yaml.safe_load(_RESTYLE_CONFIG.read_text())
    applied: list[str] = []
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
        old = cfg.get(key)
        cfg[key] = value
        applied.append(f"restyle.yml: {key} {old!r} → {value!r}")
    if applied:
        tmp = _RESTYLE_CONFIG.with_suffix(".tmp")
        tmp.write_text(
            yaml.dump(cfg, default_flow_style=False, sort_keys=False, allow_unicode=True)
        )
        tmp.rename(_RESTYLE_CONFIG)
    return applied


def _process_one(
    client: GatewayClient,
    name: str,
    style_entry: dict,
    example_dir: Path,
    from_source: str,
    all_styles: list[dict],
    *,
    optimize: str,
) -> dict:
    style_id = style_entry["id"]
    result: dict = {"example": name, "style_id": style_id, "error": None}

    source_bytes = _load_source_image(example_dir, from_source)
    if source_bytes is None:
        result["error"] = "no source image"
        return result

    source_b64 = base64.b64encode(source_bytes).decode()
    resolved_entry, _ = resolve_style(style_id)
    pg = build_restyle_params(resolved_entry)

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

    # Score: style match
    try:
        style_result = classify_image_style(
            candidate_bytes, all_styles, gateway_url=client.base_url
        )
        style_score = style_result.scores.get(style_id, 0.0)
        if style_result.top_style_id == style_id and style_score == 0.0:
            style_score = STYLE_PASS_THRESHOLD
        result["style_score"] = round(style_score, 3)
    except Exception as exc:
        logger.warning("style classification failed %s: %s", name, exc)
        result["style_score"] = 0.0

    # Score: identity (SBS)
    try:
        sbs = compare_side_by_side(
            source_bytes,
            candidate_bytes,
            goal="Re-render the avatar in a new style while preserving identity.",
            reference_label="source",
            generated_label="restyled",
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
# REASON: LLM fix for restyle (mid-iteration — explore new solutions)
# ---------------------------------------------------------------------------


def _apply_restyle_fixes(
    client: GatewayClient,
    entries: list[dict],
    fixes_path: Path,
    component_threshold: float = 0.75,
    style_filter: list[str] | None = None,
    max_reason_changes: int = 3,
) -> dict:
    """REASON step: uses client.reasoning() to explore new style prompt fixes."""
    failures = [
        e
        for e in entries
        if not e.get("error")
        and (
            e.get("style_score", 0) < component_threshold
            or e.get("identity_score", 0) < component_threshold
        )
    ]

    failure_summary = "\n".join(
        f"  {e['example']} x {e['style_id']}: "
        f"style={e.get('style_score', 0):.0%}  identity={e.get('identity_score', 0):.0%}  "
        f'"{e.get("sbs_reasoning", "")[:100]}"'
        for e in failures[:20]
    )

    # Scope the styles.yml excerpt to only the style(s) being learned.
    # Showing all styles causes the LLM to reason about and patch styles it
    # has no data on, which both corrupts unrelated entries and dilutes focus.
    with open(STYLES_YML) as f:
        all_styles_data = yaml.safe_load(f)
    all_style_entries = all_styles_data.get("styles", all_styles_data)
    if style_filter:
        scoped_styles = {"styles": [s for s in all_style_entries if s.get("id") in style_filter]}
    else:
        scoped_styles = all_styles_data
    styles_content = yaml.dump(
        scoped_styles, default_flow_style=False, sort_keys=False, allow_unicode=True
    )
    style_scope_note = (
        f"You are only tuning: {style_filter}. Do NOT propose patches for any other style."
        if style_filter
        else "You are tuning all styles."
    )

    prompt_gen_content = _RESTYLE_CONFIG.read_text()

    reasoning_prompt = textwrap.dedent(f"""
        You are improving the avatar-studio restyle pipeline (IP-Adapter FaceID based).
        The restyle pipeline re-renders an existing avatar in a new style using IP-Adapter.

        SCOPE: {style_scope_note}

        ## Failures (style score < {component_threshold:.0%} or identity score < {component_threshold:.0%})
        {failure_summary or "(none)"}

        ## Current restyle.yml (diffusion generation params — this is what drives generation)
        {prompt_gen_content}

        ## Current styles.yml (scoped to target style only — used by classifier)
        {styles_content}

        Diffusion parameter effects:
        - ip_adapter_scale: 0.4–0.9 — higher = stronger face identity, lower = more style freedom
        - cfg_scale: 5–12 — higher = more prompt-adherent, lower = more natural variation
        - num_inference_steps: 15–50 — more steps = higher quality/detail but slower
        - negative_prompt: what to suppress — directly reduces artifact rate
        - prompt_template: the CLIP conditioning text (≤77 tokens); {{style_description}} is filled per style

        CLIP 77-token hard limit (CRITICAL): each prompt (positive and negative) must be
        ≤ 70 tokens — 75 is the absolute ceiling but the runtime tokeniser may differ.
        For prompt_template, this is the RENDERED length (template + filled {{style_description}});
        keep the template text to ~50 tokens so there is room for the variable.
        Use comma-separated keywords for negative_prompt; avoid full sentences.

        Analyze the failures for the target style only:
        1. What pattern explains the style classification failures?
        2. Why is identity score low — what does the SBS reasoning reveal?
        3. Which restyle.yml param changes would most improve the scores?
        4. Should the style system_prompt be updated to guide the classifier better?

        Be specific. Reference actual values and exact strings from the configs shown above.
        Do not mention or suggest changes to other styles.
    """).strip()

    schema_json = json.dumps(_FIX_SCHEMA, indent=2)
    format_prompt = textwrap.dedent(f"""
        Based on the analysis below, produce a JSON fix specification.

        ANALYSIS:
        {{reasoning}}

        OUTPUT SCHEMA (single valid JSON object, no prose):
        {schema_json}

        Rules:
        - prompt_gen_patches: fields to update in restyle.yml; set a field to null to leave it unchanged
        - style_prompt_patches: find/replace patches to system_prompt strings in styles.yml
        - Leave prompt_gen_patches fields null and style_prompt_patches empty if no changes needed.
        - CLIP token limit: each prompt (positive and negative) must be ≤ 70 tokens.
            75 is the absolute hard crash limit; the runtime tokeniser may differ slightly.
            For prompt_template: count the rendered text (template + filled {{style_description}});
            keep template text ≤ ~50 tokens so the variable has room.
            For negative_prompt: ≤ 70 tokens. Use comma-separated keywords, not sentences.
            A 10-word phrase ≈ 13 tokens. If in doubt, cut.
        - IMPORTANT: propose changes to AT MOST {max_reason_changes} properties in total across
          both prompt_gen_patches and style_prompt_patches combined. Choose the single most
          impactful change first; leave all other fields null or empty. Changing many parameters
          at once makes it impossible to know which change caused any improvement or regression.
    """).strip()

    applied: list[str] = []
    skipped: list[str] = []
    fixes: dict = {"prompt_gen_patches": {}, "style_prompt_patches": [], "rationale": ""}

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
    style_patches = fixes.get("style_prompt_patches") or []
    non_null_pg = [(k, v) for k, v in pg_patches.items() if v is not None]
    total_proposed = len(non_null_pg) + len(style_patches)
    if total_proposed > max_reason_changes:
        logger.warning(
            "REASON proposed %d changes (limit=%d) — truncating to %d most important",
            total_proposed,
            max_reason_changes,
            max_reason_changes,
        )
        # Fill remaining budget with pg patches first, then style patches
        budget = max_reason_changes
        allowed_pg = dict(non_null_pg[:budget])
        budget -= len(allowed_pg)
        allowed_style = style_patches[:budget]
        # Null out pg keys that were trimmed
        for k in pg_patches:
            if k not in allowed_pg:
                pg_patches[k] = None
        fixes["prompt_gen_patches"] = pg_patches
        fixes["style_prompt_patches"] = allowed_style

    pg_applied = _apply_prompt_gen_patches(fixes.get("prompt_gen_patches") or {})
    style_applied, skipped = _apply_style_patches(fixes)
    applied = pg_applied + style_applied
    fixes["_applied"] = applied
    fixes["_skipped"] = skipped
    _atomic_write(fixes_path, fixes)

    logger.info("Restyle fixes applied: %d  Skipped: %d", len(applied), len(skipped))
    for change in applied:
        logger.info("  applied: %s", change)
    return fixes


# ---------------------------------------------------------------------------
# FINAL: consolidation pass (post-loop — select from existing solutions)
# ---------------------------------------------------------------------------


def _apply_restyle_final(
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

    with open(STYLES_YML) as f:
        styles_content = f.read()

    schema_json = json.dumps(_FIX_SCHEMA, indent=2)
    prompt = textwrap.dedent(f"""
        You are finalizing the avatar-studio restyle pipeline after
        {len(iteration_history)} improvement iteration(s).

        ## Iteration history (all REASON steps applied so far)
        {history_text}

        ## Current styles.yml (after all iterations)
        {styles_content}

        ## Your task: CONSOLIDATE — do NOT explore new ideas
        Review the trajectory. Your job is to select and lock in the best configuration
        from what has already been tested.

        - If combined scores improved consistently: current state is correct.
          Leave ALL arrays empty and confirm the final state in rationale.
        - If a specific iteration caused regression: suggest reverting ONLY those exact
          style_prompt_patches using the patch fields.
        - Do NOT propose new style prompt wording or weight values not already tested.

        OUTPUT SCHEMA (single valid JSON object, no prose):
        {schema_json}
    """).strip()

    logger.info(
        "FINAL: general model consolidating %d iteration(s) for restyle…",
        len(iteration_history),
    )

    fixes: dict = {"prompt_gen_patches": {}, "style_prompt_patches": [], "rationale": ""}

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
    style_applied, skipped = _apply_style_patches(fixes)
    applied = pg_applied + style_applied
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


def run_learn_restyle(
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
    style_filter: list[str] | None = None,
    component_threshold: float = 0.75,
    compound_threshold: float = 0.90,
    max_reason_changes: int = 3,
) -> None:
    log = make_logger("learn_restyle", log_dir)

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

    ts = datetime.now().strftime("%y-%m-%d-%H-%M")
    loop_dir = REPORTS_DIR / f"learn_restyle_{ts}"
    loop_dir.mkdir(parents=True, exist_ok=True)

    all_styles = _load_styles()

    if style_filter:
        known_ids = {s["id"] for s in all_styles}
        unknown = [sid for sid in style_filter if sid not in known_ids]
        if unknown:
            logger.error("Unknown style(s): %s  (available: %s)", unknown, sorted(known_ids))
            sys.exit(1)
        all_styles = [s for s in all_styles if s["id"] in style_filter]

    log.config(
        script="learn_restyle",
        max_iterations=max_iterations,
        stop_on_plateau=stop_on_plateau,
        improve_threshold=improve_threshold,
        workers=workers,
        optimize=optimize,
        from_source=from_source,
        samples=current_n,
        styles=[s["id"] for s in all_styles],
        loop_dir=str(loop_dir),
        max_reason_changes=max_reason_changes,
    )

    logger.info(
        "learn_restyle: samples=%d  max_iter=%d  improve_threshold=%.0f%%  optimize=%s",
        current_n,
        max_iterations,
        improve_threshold * 100,
        optimize,
    )
    for s in all_styles:
        se, _ = resolve_style(s["id"])
        pg = build_restyle_params(se)
        logger.info("  [%s] prompt_gen params:", s["id"])
        for line in pg.log_lines():
            logger.info(line)

    client = GatewayClient(gateway_url)
    score_history: list[float] = []
    iteration_history: list[dict] = []
    state: dict = {"loop_dir": str(loop_dir), "iterations": []}
    prev_pg: dict | None = None  # previous iteration's prompt_gen params for diff

    for iteration in range(1, max_iterations + 1):
        prefix = f"iter_{iteration:02d}"
        sample_names = {name for name, _ in current_sample}

        work = [
            (name, persona, style_entry)
            for name, persona in current_sample
            for style_entry in all_styles
            if sample_names  # always true, just to use the variable
        ]
        entries: list[dict] = []

        logger.info("[iter %d/%d] Generating %d images…", iteration, max_iterations, len(work))
        for s in all_styles:
            se, _ = resolve_style(s["id"])
            pg = build_restyle_params(se)
            pg_dict = {
                "prompt": pg.prompt,
                "negative_prompt": pg.negative_prompt,
                "num_inference_steps": pg.num_inference_steps,
                "cfg_scale": pg.cfg_scale,
                "ip_adapter_scale": pg.ip_adapter_scale,
                "lora": pg.lora,
                "lora_weight": pg.lora_weight,
            }
            if prev_pg is None:
                logger.info("  [%s] prompt_gen params:", s["id"])
                for line in pg.log_lines():
                    logger.info(line)
            else:
                changed = {
                    k: (prev_pg.get(k), v) for k, v in pg_dict.items() if prev_pg.get(k) != v
                }
                if changed:
                    logger.info("  [%s] prompt_gen CHANGED:", s["id"])
                    for k, (old, new) in changed.items():
                        logger.info("    %s: %r → %r", k, old, new)
                else:
                    logger.info("  [%s] prompt_gen unchanged", s["id"])
            prev_pg = pg_dict

        running_style = 0.0
        running_identity = 0.0
        n_ok = 0
        n_errors = 0
        pbar_desc = f"iter {iteration}/{max_iterations}"

        def _on_entry(entry: dict, name: str, style_id: str) -> None:
            nonlocal running_style, running_identity, n_ok, n_errors
            entries.append(entry)
            log.render(iteration=iteration, example=name, style=style_id, error=entry.get("error"))
            if entry.get("error"):
                n_errors += 1
                logger.warning("  failed: %s x %s — %s", name, style_id, entry["error"])
            else:
                n_ok += 1
                running_style += entry.get("style_score", 0.0)
                running_identity += entry.get("identity_score", 0.0)
                log.score(
                    iteration=iteration,
                    example=name,
                    style=style_id,
                    style_score=entry.get("style_score"),
                    identity_score=entry.get("identity_score"),
                )

        if workers <= 1:
            pbar = tqdm(work, desc=pbar_desc, unit="img")
            for name, persona, style_entry in pbar:
                pbar.set_postfix_str(f"{name} x {style_entry['id']}")
                entry = _process_one(
                    client,
                    name,
                    style_entry,
                    examples_dir / name,
                    from_source,
                    all_styles,
                    optimize=optimize,
                )
                _on_entry(entry, name, style_entry["id"])
                if n_ok:
                    pbar.set_postfix_str(
                        f"style={running_style / n_ok:.0%} id={running_identity / n_ok:.0%}"
                        + (f" err={n_errors}" if n_errors else "")
                    )
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {
                    pool.submit(
                        _process_one,
                        client,
                        name,
                        style_entry,
                        examples_dir / name,
                        from_source,
                        all_styles,
                        optimize=optimize,
                    ): (name, style_entry["id"])
                    for name, persona, style_entry in work
                }
                pbar = tqdm(as_completed(futures), total=len(futures), desc=pbar_desc, unit="img")
                for future in pbar:
                    name, style_id = futures[future]
                    try:
                        entry = future.result()
                    except Exception as exc:
                        entry = {"example": name, "style_id": style_id, "error": str(exc)}
                    _on_entry(entry, name, style_id)
                    if n_ok:
                        pbar.set_postfix_str(
                            f"style={running_style / n_ok:.0%} id={running_identity / n_ok:.0%}"
                            + (f" err={n_errors}" if n_errors else "")
                        )

        # Summarize
        successful = [e for e in entries if not e.get("error")]
        avg_style = (
            sum(e.get("style_score", 0) for e in successful) / len(successful)
            if successful
            else 0.0
        )
        avg_identity = (
            sum(e.get("identity_score", 0) for e in successful) / len(successful)
            if successful
            else 0.0
        )
        combined = (avg_style + avg_identity) / 2
        score_history.append(combined)

        log.summary(
            iteration=iteration,
            avg_style=round(avg_style, 3),
            avg_identity=round(avg_identity, 3),
            combined=round(combined, 3),
            n_successful=len(successful),
            n_failed=len(entries) - len(successful),
        )
        logger.info(
            "[iter %d] style=%.0f%%  identity=%.0f%%  combined=%.0f%%",
            iteration,
            avg_style * 100,
            avg_identity * 100,
            combined * 100,
        )

        # Log worst examples to surface persistent failures
        if successful:
            worst = sorted(successful, key=lambda e: e.get("identity_score", 0))[:5]
            for w in worst:
                logger.info(
                    "  low: %-24s  style=%.0f%%  id=%.0f%%  %s",
                    w["example"],
                    w.get("style_score", 0) * 100,
                    w.get("identity_score", 0) * 100,
                    w.get("sbs_reasoning", "")[:80],
                )

        # Scored sample for next iteration
        example_scores = {e["example"]: e.get("identity_score", 0.0) for e in successful}
        prev_scored = score_sample(current_sample, example_scores)

        improvement = (
            score_history[-1] - score_history[-2] if len(score_history) >= 2 else float("inf")
        )

        # ── FINAL: max iterations reached ────────────────────────────────
        if iteration == max_iterations:
            logger.info("[iter %d] Max iterations reached — running FINAL", iteration)
            final_path = loop_dir / f"{prefix}_final.json"
            final = _apply_restyle_final(client, iteration_history, final_path)
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
            final = _apply_restyle_final(client, iteration_history, final_path)
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
        fixes = _apply_restyle_fixes(
            client,
            entries,
            fixes_path,
            component_threshold=component_threshold,
            style_filter=style_filter,
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
                "avg_style": round(avg_style, 3),
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
    print(f"learn_restyle complete — {len(state['iterations'])} iterations")
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
        description="Learn: iterative improvement for the restyle (IP-Adapter) pipeline"
    )
    add_common_args(parser)
    parser.add_argument("--examples-dir", type=Path, default=EXAMPLES_DIR)
    parser.add_argument(
        "--style",
        nargs="+",
        default=["all"],
        metavar="STYLE",
        help="Style ID(s) to run, or 'all' (default: all)",
    )
    args = parser.parse_args()

    style_filter = None if args.style == ["all"] else args.style

    run_learn_restyle(
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
        style_filter=style_filter,
        component_threshold=args.component_threshold,
        compound_threshold=args.compound_threshold,
        max_reason_changes=args.max_reason_changes,
    )
