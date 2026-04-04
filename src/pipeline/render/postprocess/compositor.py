"""Compositor — composites a portrait onto a circle sticker background.

Generalized from ``step_d_make_abbreviation.apply_circle_frame``.

Modes
-----
transparent  — circle is transparent (portrait floats, no bg fill)
color_fill   — circle filled with *bg_color*
round_fill   — circle with white sticker border + *bg_color* fill (original)
"""

from __future__ import annotations

import io
import logging

from PIL import Image, ImageDraw, PngImagePlugin

from config.config import _hex_to_rgb

logger = logging.getLogger(__name__)

_CIRCLE_R_RATIO = 0.33
_PORTRAIT_H_RATIO = 0.80
_BORDER_PX = 6


def composite(
    image_bytes: bytes,
    size: int,
    bg_color: str = "#FFFFFF",
    mode: str = "round_fill",
) -> bytes:
    """Composite portrait bytes onto a circle sticker.

    Parameters
    ----------
    image_bytes:
        RGBA PNG bytes (background already removed).
    size:
        Output canvas size in pixels (square).
    bg_color:
        Hex color for the background circle.
    mode:
        ``"transparent"`` | ``"color_fill"`` | ``"round_fill"`` (default).
    """
    src = Image.open(io.BytesIO(image_bytes)).convert("RGBA")

    # Scale portrait to target height
    src_w, src_h = src.size
    target_h = int(size * _PORTRAIT_H_RATIO)
    target_w = int(src_w * target_h / src_h)
    portrait = src.resize((target_w, target_h), Image.LANCZOS)

    result = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(result)

    cx = cy = size // 2
    circle_r = int(size * _CIRCLE_R_RATIO)

    if mode == "transparent":
        pass  # No background circle — portrait on transparent canvas

    elif mode == "color_fill":
        bg_rgb = _hex_to_rgb(bg_color)
        draw.ellipse(
            [cx - circle_r, cy - circle_r, cx + circle_r, cy + circle_r],
            fill=(*bg_rgb, 255),
        )

    else:  # round_fill (default)
        border_r = circle_r + _BORDER_PX
        draw.ellipse(
            [cx - border_r, cy - border_r, cx + border_r, cy + border_r],
            fill=(255, 255, 255, 255),
        )
        bg_rgb = _hex_to_rgb(bg_color)
        draw.ellipse(
            [cx - circle_r, cy - circle_r, cx + circle_r, cy + circle_r],
            fill=(*bg_rgb, 255),
        )

    paste_x = (size - target_w) // 2
    paste_y = (size - target_h) // 2
    result.alpha_composite(portrait, (paste_x, paste_y))

    out = io.BytesIO()
    meta = PngImagePlugin.PngInfo()
    meta.add_text("Generator", f"PIL compositor mode={mode}")
    result.save(out, format="PNG", pnginfo=meta)
    return out.getvalue()
