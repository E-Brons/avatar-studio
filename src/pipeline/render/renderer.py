"""Top-level renderer — orchestrates the full avatar render pipeline."""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFont, PngImagePlugin

from config.config import SETTINGS, _color_for_name, _hex_to_rgb, _initials, _name_to_filename
from pipeline.render.expression_resolver import (
    EXPRESSIONS_YML,
    resolve_expression_list,
)
from pipeline.render.llm.orchestrator import generate_avatar_image, render_llm
from pipeline.render.programmatic.orchestrator import render_programmatic
from pipeline.render.style_resolver import STYLES_YML

logger = logging.getLogger(__name__)

DEFAULT_SIZE: int = SETTINGS["default_image_size"]


def create_abbreviation_avatar(
    name: str,
    out_path: Path,
    size: int = DEFAULT_SIZE,
    color: str | None = None,
) -> Path:
    """Create a circular avatar PNG with initials."""
    logger.info("[Step D] START — make_abbreviation (name=%s)", name)
    bg = _hex_to_rgb(color or _color_for_name(name))
    initials = _initials(name)

    # Supersample for smooth anti-aliasing.
    scale = 4
    big = size * scale

    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Circle background.
    draw.ellipse([0, 0, big - 1, big - 1], fill=(*bg, 255))

    # Text — use default font scaled up.
    font_size = big // 3
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
    except OSError:
        font = ImageFont.load_default(size=font_size)

    bbox = draw.textbbox((0, 0), initials, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (big - tw) // 2 - bbox[0]
    ty = (big - th) // 2 - bbox[1]
    draw.text((tx, ty), initials, fill=(255, 255, 255, 255), font=font)

    # Downscale to target size.
    img = img.resize((size, size), Image.LANCZOS)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    meta = PngImagePlugin.PngInfo()
    meta.add_text("Copyright", "\u00a9 2026 MyBoard & Elkana Bronstein")
    meta.add_text("Generator", "PIL abbreviation avatar")
    img.save(str(out_path), pnginfo=meta)
    logger.info("[Step D] DONE  — %s", out_path)
    return out_path


def make_session_dir(name: str) -> Path:
    """Create and return a timestamped session folder for one pipeline run."""
    slug = _name_to_filename(name)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_root = Path("/tmp/avatar_studio") / slug / ts
    session_root.mkdir(parents=True, exist_ok=True)
    return session_root


def create_face_avatar(
    advisor: dict,
    expressions: list[str],
    out_dir: Path,
    slug: str,
    *,
    gateway_url: str = "http://127.0.0.1:4096",
    width: int = DEFAULT_SIZE,
    height: int = DEFAULT_SIZE,
    seed: int | None = None,
) -> tuple[dict[str, str | None], dict]:
    """Generate face avatars: neutral portrait (Step E) then expression variants (Step F).

    Returns (expr_map, demographics) where expr_map maps expression IDs to
    filenames (or None on failure) and demographics is the randomized dict.
    """
    from pipeline.persona.aggregator_llm import select_features
    from pipeline.persona.generator import build_avatar_charachter, pick_demographics

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
        "styles_yml": STYLES_YML,
    }

    # Step E — neutral portrait.
    neutral_filename = f"{slug}-neutral.png"
    neutral_path = out_dir / neutral_filename
    try:
        generate_avatar_image(
            persona_path,
            style=style_arg,
            expression={"name": "neutral", "expressions_yml": EXPRESSIONS_YML},
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
                expression={"name": expr_id, "expressions_yml": EXPRESSIONS_YML},
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


def render(
    persona_path: Path,
    out_dir: Path,
    slug: str,
    *,
    demographics: dict,
    expressions: list[str],
    gateway_url: str = "http://127.0.0.1:4096",
    width: int = 256,
    height: int = 256,
    optimize: str = "normal",
    seed: int | None = None,
    pa_style: str = "toon-head",
    pa_size: int = 256,
) -> dict:
    """Render all avatar outputs for one persona.

    Returns a results dict with:
      ``expressions``       — {expr_id: filename | None}
      ``programmatic``      — {expr_id: filename | None}
    """
    expressions = resolve_expression_list(expressions)
    style_arg = {
        "name": demographics.get("style", "random"),
        "bg_color": demographics.get("bg_color", "#F5F0E8"),
        "styles_yml": STYLES_YML,
    }

    expr_map: dict[str, str | None] = {}

    # Step E — neutral portrait
    neutral_filename = f"{slug}-neutral.png"
    neutral_path = out_dir / neutral_filename
    try:
        render_llm(
            persona_path,
            style=style_arg,
            expression_name="neutral",
            reference_image=None,
            gateway_url=gateway_url,
            width=width,
            height=height,
            optimize=optimize,
            seed=seed,
            out_path=neutral_path,
            session_dir=None,
        )
        expr_map["neutral"] = neutral_filename
    except Exception as exc:
        logger.error("[render] neutral portrait failed: %s", exc)
        return {"expressions": {e: None for e in expressions}, "programmatic": {}}

    # Step F — expression variants
    for expr_id in [e for e in expressions if e != "neutral"]:
        expr_filename = f"{slug}-{expr_id}.png"
        expr_path = out_dir / expr_filename
        try:
            render_llm(
                persona_path,
                style=style_arg,
                expression_name=expr_id,
                reference_image=neutral_path,
                gateway_url=gateway_url,
                width=width,
                height=height,
                optimize=optimize,
                seed=seed,
                out_path=expr_path,
                session_dir=None,
            )
            expr_map[expr_id] = expr_filename
        except Exception as exc:
            logger.warning("[render] expression %s failed: %s", expr_id, exc)
            expr_map[expr_id] = None

    # Step D — programmatic avatar
    name = ""
    try:
        with open(persona_path) as f:
            persona = yaml.safe_load(f)
        name = persona.get("personal", {}).get("name", slug)
    except Exception:
        name = slug

    pa_map = render_programmatic(
        name,
        out_dir,
        slug,
        expressions,
        style=pa_style,
        size=pa_size,
        demographics=demographics,
    )

    return {"expressions": expr_map, "programmatic": pa_map}
