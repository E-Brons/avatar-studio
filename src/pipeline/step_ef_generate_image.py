"""Stage E/F — avatar portrait and expression generation via the LLM Gateway.

Step E — canonical neutral portrait:
  generate_avatar_image(persona_path, style=..., expression={"name": "neutral", ...})

Step F — expression variant:
  generate_avatar_image(persona_path, style=..., expression={"name": <id>, ...},
                        reference_image=<neutral portrait path>)

Both steps are driven by the same function. The only differences are:
  - expression.name  (neutral vs any)
  - reference_image  (None vs path to neutral portrait)
"""

from __future__ import annotations

import base64
import io
import logging
import random
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

import yaml
from PIL import Image, PngImagePlugin

from config.config import SETTINGS as _SETTINGS
from config.gateway import GatewayClient
from pipeline.step_a_randomise_person import pick_demographics
from pipeline.step_c_select_features import build_avatar_charachter, select_features

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_EXPRESSIONS_YML = _PROJECT_ROOT / "assets" / "expressions" / "expressions.yml"
_STYLES_YML = _PROJECT_ROOT / "assets" / "styles" / "styles.yml"

# Public aliases for importers
EXPRESSIONS_YML = _EXPRESSIONS_YML
STYLES_YML = _STYLES_YML

_DEFAULT_IMAGE_SIZE: int = _SETTINGS["default_image_size"]

logger = logging.getLogger(__name__)


def _resolve_unilateral(facs: str) -> str:
    """Replace AUNNx placeholders with a randomly chosen side (R or L)."""
    side = random.choice(["R", "L"])
    return re.sub(r"AU(\d+)x", lambda m: f"AU{m.group(1)}{side}", facs)


def _load_expression_ids() -> list[str]:
    with open(_EXPRESSIONS_YML) as f:
        data = yaml.safe_load(f)
    return [e.get("id") or e["expression"].lower() for e in data["expressions"]]


EXPRESSION_IDS = _load_expression_ids()


def make_session_dir(name: str) -> Path:
    """Create and return a timestamped session folder for one pipeline run."""
    from config.config import _name_to_filename

    slug = _name_to_filename(name)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_root = Path("/tmp/avatar_studio") / slug / ts
    session_root.mkdir(parents=True, exist_ok=True)
    return session_root


# Backward-compat alias
_make_session_dir = make_session_dir


def generate_avatar_image(
    avatar_persona_path: Path,
    *,
    style: dict,
    expression: dict,
    reference_image: Path | None = None,
    gateway_url: str = "http://127.0.0.1:4096",
    width: int = _DEFAULT_IMAGE_SIZE,
    height: int = _DEFAULT_IMAGE_SIZE,
    seed: int | None = None,
    out_path: Path,
    session_dir: Path | None = None,
) -> Path:
    """Generate an avatar portrait (Step E) or expression variant (Step F).

    Parameters
    ----------
    avatar_persona_path:
        Path to the ``avatar_persona.yml`` file produced by Step C.
    style:
        ``{"name": str, "bg_color": str, "styles_yml": Path}``
        *name* is the style ID to look up in styles_yml.
        *bg_color* replaces the ``[BG_COLOR]`` placeholder in the style directive.
    expression:
        ``{"name": str, "expressions_yml": Path}``
        *name* defaults to ``"neutral"`` for Step E.
    reference_image:
        None for Step E (neutral portrait).
        Path to the neutral portrait PNG for Step F (expression variants).
    gateway_url:
        Base URL of the LLM Gateway server.
    out_path:
        Destination for the generated PNG.
    session_dir:
        When provided, session artifacts are written here before calling the
        image model: ``prompt_system.txt``, ``prompt_user.txt``, ``style.yml``,
        ``expression.yml``, ``reference_person.png`` (Step F only),
        ``output.png`` (copy of out_path).

    Raises
    ------
    RuntimeError
        When the gateway returns no image data.
    """
    step = "E" if reference_image is None else "F"
    expr_name = expression["name"]
    style_name = style["name"]

    logger.info(
        "[Step %s] START — generate_avatar_image expression=%s style=%s gateway_url=%s",
        step,
        expr_name,
        style_name,
        gateway_url,
    )

    # --- Load inputs from provided paths ---
    with open(avatar_persona_path) as f:
        persona = yaml.safe_load(f)

    with open(style["styles_yml"]) as f:
        styles_data = yaml.safe_load(f)
    style_entry = {s["id"]: s for s in styles_data["styles"]}.get(style_name) or {}
    style_directive = (style_entry.get("system_prompt") or "").replace(
        "[BG_COLOR]", style.get("bg_color", "#F5F0E8")
    )

    with open(expression["expressions_yml"]) as f:
        expr_data = yaml.safe_load(f)
    expr_entry = {e.get("id") or e["expression"].lower(): e for e in expr_data["expressions"]}.get(
        expr_name
    ) or {"expression": expr_name}

    # --- Build prompt ---
    # Strip the 'style' key — it holds post-processing metadata (bg_color, fg_color)
    # for Step G and is not visual identity data for the image model.
    persona_for_prompt = {k: v for k, v in persona.items() if k != "style"}
    persona_yaml = yaml.dump(
        persona_for_prompt, default_flow_style=False, sort_keys=False, allow_unicode=True
    )
    # Extract only image-relevant fields from the expression entry.
    facs = _resolve_unilateral(expr_entry.get("facs_action_units", ""))
    expr_for_prompt = {
        "Expression": expr_entry.get("expression", expr_name),
        "FACS": facs,
        "Description": expr_entry.get("description", ""),
    }
    expr_yaml = yaml.dump(
        expr_for_prompt, default_flow_style=False, sort_keys=False, allow_unicode=True
    )

    user_prompt = f"persona profile:\n{persona_yaml}\nexpression:\n{expr_yaml}"
    if reference_image is not None:
        user_prompt += "\nreference image: see the attached neutral expression avatar PNG file"

    # Image models have no system concept — prepend the style directive to the prompt.
    full_prompt = f"{style_directive}\n\n{user_prompt}".strip() if style_directive else user_prompt

    # --- Log inputs + prompt ---
    _SEP = "─" * 60
    logger.info(
        "\n%s\n  [Step %s] gateway_url=%s | style=%s | expression=%s | reference=%s\n\n"
        "STYLE DIRECTIVE:\n%s\n\n"
        "PERSONA:\n%s\n"
        "EXPRESSION:\n%s\n"
        'PROMPT:\n"""\n%s\n"""\n%s',
        _SEP,
        step,
        gateway_url,
        style_name,
        expr_name,
        str(reference_image) if reference_image else "none",
        style_directive or "(none)",
        persona_yaml,
        expr_yaml,
        full_prompt,
        _SEP,
    )

    # --- Write session artifacts before calling the image model ---
    if session_dir is not None:
        try:
            session_dir.mkdir(parents=True, exist_ok=True)
            (session_dir / "prompt.txt").write_text(full_prompt)
            with open(session_dir / "style.yml", "w") as f:
                yaml.dump(
                    style_entry, f, default_flow_style=False, sort_keys=False, allow_unicode=True
                )
            with open(session_dir / "expression.yml", "w") as f:
                yaml.dump(
                    expr_entry, f, default_flow_style=False, sort_keys=False, allow_unicode=True
                )
            if reference_image is not None and reference_image.exists():
                shutil.copy2(reference_image, session_dir / "reference_person.png")
            logger.info("[Step %s] Writing session artifacts to %s", step, session_dir)
        except Exception as exc:
            logger.warning("[Step %s] Failed to write session artifacts: %s", step, exc)

    # --- Call LLM Gateway ---
    client = GatewayClient(gateway_url)
    raw_bytes = client.image_gen(
        full_prompt,
        width=width,
        height=height,
        seed=seed,
        reference_images_b64=[base64.b64encode(reference_image.read_bytes()).decode()]
        if reference_image
        else None,
    )

    # --- Embed inputs + prompt into PNG metadata and save ---
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.open(io.BytesIO(raw_bytes))
    meta = PngImagePlugin.PngInfo()
    meta.add_text("Copyright", "\u00a9 2026 MyBoard & Elkana Bronstein")
    meta.add_text("GatewayUrl", gateway_url)
    meta.add_text("StyleDirective", style_directive)
    meta.add_text("UserPrompt", user_prompt)
    meta.add_text("Prompt", full_prompt)
    meta.add_text("PersonaYaml", persona_yaml)
    meta.add_text(
        "StyleYaml",
        yaml.dump(style_entry, default_flow_style=False, sort_keys=False, allow_unicode=True),
    )
    meta.add_text("ExpressionYaml", expr_yaml)
    img.save(str(out_path), pnginfo=meta)

    if session_dir is not None:
        try:
            img.save(str(session_dir / "output.png"), pnginfo=meta)
        except Exception as exc:
            logger.warning("[Step %s] Failed to save output.png to session_dir: %s", step, exc)

    logger.info("[Step %s] DONE — %s", step, out_path)
    return out_path


def create_face_avatar(
    advisor: dict,
    expressions: list[str],
    out_dir: Path,
    slug: str,
    *,
    gateway_url: str = "http://127.0.0.1:4096",
    width: int = _DEFAULT_IMAGE_SIZE,
    height: int = _DEFAULT_IMAGE_SIZE,
    seed: int | None = None,
) -> tuple[dict[str, str | None], dict]:
    """Generate face avatars: neutral portrait (Step E) then expression variants (Step F).

    Returns (expr_map, demographics) where expr_map maps expression IDs to
    filenames (or None on failure) and demographics is the randomized dict.
    """
    name = advisor.get("name", "Unknown")
    demographics = pick_demographics(seed)
    session_root = make_session_dir(name)

    # Step C — feature selection (writes features to session_root/persona.yml).
    features = None
    try:
        features = select_features(
            demographics,
            advisor,
            gateway_url=gateway_url,
            session_dir=session_root,
        )
    except Exception as exc:
        logger.warning("[Step C] feature selection failed: %s", exc)

    # Marshal the full avatar_persona and write persona.yml to session_root.
    avatar = build_avatar_charachter(advisor, demographics, features)
    persona_path = session_root / "persona.yml"
    with open(persona_path, "w") as f:
        yaml.dump(
            avatar["avatar_persona"],
            f,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )

    style_arg = {
        "name": demographics.get("style", "random"),
        "bg_color": demographics.get("bg_color", "#F5F0E8"),
        "styles_yml": _STYLES_YML,
    }

    # Step E — neutral portrait.
    neutral_filename = f"{slug}-neutral.png"
    neutral_path = out_dir / neutral_filename
    try:
        generate_avatar_image(
            persona_path,
            style=style_arg,
            expression={"name": "neutral", "expressions_yml": _EXPRESSIONS_YML},
            gateway_url=gateway_url,
            width=width,
            height=height,
            seed=seed,
            out_path=neutral_path,
            session_dir=session_root / "neutral",
        )
        print(f"  [neutral] {neutral_path}")
    except Exception as exc:
        print(f"  Warning: failed to generate neutral portrait for {name}: {exc}", file=sys.stderr)
        return {expr_id: None for expr_id in expressions}, demographics

    expr_map: dict[str, str | None] = {"neutral": neutral_filename}

    # Step F — expression variants.
    for expr_id in [e for e in expressions if e != "neutral"]:
        expr_filename = f"{slug}-{expr_id}.png"
        expr_path = out_dir / expr_filename
        try:
            generate_avatar_image(
                persona_path,
                style=style_arg,
                expression={"name": expr_id, "expressions_yml": _EXPRESSIONS_YML},
                reference_image=neutral_path,
                gateway_url=gateway_url,
                width=width,
                height=height,
                seed=seed,
                out_path=expr_path,
                session_dir=session_root / expr_id,
            )
            expr_map[expr_id] = expr_filename
            print(f"  [{expr_id}] {expr_path}")
        except Exception as exc:
            print(f"  Warning: failed to generate {expr_id} for {name}: {exc}", file=sys.stderr)
            expr_map[expr_id] = None

    return expr_map, demographics
