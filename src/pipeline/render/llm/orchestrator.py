"""LLM render orchestrator — single entry point for both Step E and Step F."""

from __future__ import annotations

import base64
import io
import logging
import random
import re
import shutil
from pathlib import Path

import yaml
from PIL import Image, PngImagePlugin

from config.config import SETTINGS as _SETTINGS
from config.gateway import GatewayClient
from pipeline.render.expression_resolver import EXPRESSIONS_YML
from pipeline.render.style_resolver import STYLES_YML

_DEFAULT_IMAGE_SIZE: int = _SETTINGS["default_image_size"]

logger = logging.getLogger(__name__)


def _resolve_unilateral(facs: str) -> str:
    """Replace AUNNx placeholders with a randomly chosen side (R or L)."""
    side = random.choice(["R", "L"])
    return re.sub(r"AU(\d+)x", lambda m: f"AU{m.group(1)}{side}", facs)


def generate_avatar_image(
    avatar_persona_path: Path,
    *,
    style: dict,
    expression: dict,
    reference_image: Path | None = None,
    gateway_url: str = "http://127.0.0.1:4096",
    width: int = _DEFAULT_IMAGE_SIZE,
    height: int = _DEFAULT_IMAGE_SIZE,
    optimize: str = "normal",
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
        optimize=optimize,
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


def render_llm(
    persona_path: Path,
    *,
    style: dict,
    expression_name: str,
    reference_image: Path | None = None,
    gateway_url: str = "http://127.0.0.1:4096",
    width: int = 256,
    height: int = 256,
    optimize: str = "normal",
    seed: int | None = None,
    out_path: Path,
    session_dir: Path | None = None,
) -> Path:
    """Generate an avatar image via the LLM Gateway (Step E or F).

    Thin delegation to ``generate_avatar_image`` with a normalized interface.
    """
    styles_yml = style.get("styles_yml", STYLES_YML)

    return generate_avatar_image(
        persona_path,
        style={
            "name": style.get("name", "random"),
            "bg_color": style.get("bg_color", "#F5F0E8"),
            "styles_yml": styles_yml,
        },
        expression={"name": expression_name, "expressions_yml": EXPRESSIONS_YML},
        reference_image=reference_image,
        gateway_url=gateway_url,
        width=width,
        height=height,
        optimize=optimize,
        seed=seed,
        out_path=out_path,
        session_dir=session_dir,
    )
