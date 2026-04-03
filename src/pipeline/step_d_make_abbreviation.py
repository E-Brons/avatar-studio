"""Stage D — PIL abbreviation avatar generator."""

import io
import logging
from pathlib import Path

import rembg
from PIL import Image, ImageDraw, ImageFont, PngImagePlugin

from config.config import SETTINGS, _color_for_name, _hex_to_rgb, _initials

logger = logging.getLogger(__name__)

DEFAULT_SIZE: int = SETTINGS["default_image_size"]

# Reuse the rembg session across calls so the ONNX model is loaded only once.
_rembg_session = None


def _get_rembg_session():
    global _rembg_session
    if _rembg_session is None:
        _rembg_session = rembg.new_session("u2net")
    return _rembg_session


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
    except OSError, IOError:
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


def apply_circle_frame(image_bytes: bytes, frame_bg_color: str, size: int) -> bytes:
    """Composite a portrait as a sticker over a small colored circle.

    Layout
    ------
    - Canvas: ``size × size``, fully transparent outside the sticker.
    - Background circle: radius = 33 % of ``size``, centered.
    - White sticker border: 6 px ring around the background circle.
    - Portrait: scaled so its height = 80 % of ``size``, centered,
      composited ON TOP of the circle — head and feet extend outside it.

    Background removal uses rembg (u2net ML model) to cleanly separate the
    portrait subject from its background before compositing.
    """
    _CIRCLE_R_RATIO = 0.33  # background circle radius / size
    _PORTRAIT_H_RATIO = 0.80  # portrait height / size
    _BORDER_PX = 6  # white sticker border width

    # ── Load & remove background with rembg (u2net model) ────────────────
    # rembg returns RGBA PNG bytes with the background made transparent.
    bg_removed = rembg.remove(image_bytes, session=_get_rembg_session())
    src = Image.open(io.BytesIO(bg_removed)).convert("RGBA")

    # ── Scale portrait to target height ───────────────────────────────────
    src_w, src_h = src.size
    target_h = int(size * _PORTRAIT_H_RATIO)
    target_w = int(src_w * target_h / src_h)
    portrait = src.resize((target_w, target_h), Image.LANCZOS)

    # ── Build canvas ──────────────────────────────────────────────────────
    result = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(result)

    cx = cy = size // 2
    circle_r = int(size * _CIRCLE_R_RATIO)
    border_r = circle_r + _BORDER_PX

    # White sticker border (drawn first — behind the colored circle).
    draw.ellipse(
        [cx - border_r, cy - border_r, cx + border_r, cy + border_r],
        fill=(255, 255, 255, 255),
    )

    # Colored background circle.
    bg_rgb = _hex_to_rgb(frame_bg_color)
    draw.ellipse(
        [cx - circle_r, cy - circle_r, cx + circle_r, cy + circle_r],
        fill=(*bg_rgb, 255),
    )

    # Portrait centered on canvas — extends above/below the circle.
    paste_x = (size - target_w) // 2
    paste_y = (size - target_h) // 2
    result.alpha_composite(portrait, (paste_x, paste_y))

    out = io.BytesIO()
    meta = PngImagePlugin.PngInfo()
    meta.add_text("Generator", "PIL circle frame sticker (rembg)")
    result.save(out, format="PNG", pnginfo=meta)
    return out.getvalue()
