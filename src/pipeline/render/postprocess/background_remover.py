"""Background remover for avatar portrait images.

Two strategies are available:

* ``remove_background_illustration`` — color-distance BFS flood-fill from corners
  (fast, no ML).  Works for styles with a solid/uniform background and strong
  outline strokes acting as BFS barriers: korean, lineart, clay.

* ``remove_background`` — rembg u2net with alpha-matting + morphological
  closing (ML-based).  Required for studio_3d and photorealistic:
  - studio_3d: dark gradient background (std ≈ 20–36) overlaps with dark hair/
    clothing; no outline barriers → flood-fill leaks or fails to spread
  - photorealistic: complex real-photo backgrounds

Routing by style:
  korean / lineart / clay → remove_background_illustration()
  studio_3d / photorealistic → remove_background()

Research notes:
  docs/software/llm_prompts/remove_bg_Korean.md
  docs/software/llm_prompts/remove_bg_lineart.md
  docs/software/llm_prompts/remove_bg_clay.md
  docs/software/llm_prompts/remove_bg_studio_3d.md
  docs/software/llm_prompts/remove_bg_photorealistic.md
"""

from __future__ import annotations

import io
from collections import deque

import numpy as np
from PIL import Image, ImageFilter

# ── lazy rembg session (only loaded when remove_background() is called) ───────
_rembg_session = None


def _get_rembg_session():
    import rembg

    global _rembg_session
    if _rembg_session is None:
        _rembg_session = rembg.new_session("u2net")
    return _rembg_session


# ── flood-fill helpers ────────────────────────────────────────────────────────


def _estimate_bg_color(rgb: np.ndarray, quantize: int = 16) -> np.ndarray:
    """Estimate background colour from the dominant colour along the image border.

    Samples all pixels on the outermost 1-pixel ring, quantizes to reduce noise,
    and returns the most frequent (mode) colour.  More robust than corner-only
    sampling when the subject bleeds into one or more corners of the frame.
    """
    h, w = rgb.shape[:2]
    border = np.concatenate(
        [
            rgb[0, :],  # top row
            rgb[h - 1, :],  # bottom row
            rgb[1 : h - 1, 0],  # left col (excl corners)
            rgb[1 : h - 1, w - 1],  # right col (excl corners)
        ]
    )
    quantized = border // quantize * quantize
    keys, counts = np.unique(quantized.reshape(-1, 3), axis=0, return_counts=True)
    return keys[np.argmax(counts)].astype(float)


# ── public API ────────────────────────────────────────────────────────────────


def remove_background_illustration(image_bytes: bytes, feather: bool = False) -> bytes:
    """Remove the background from a solid-background illustration.

    Uses BFS flood-fill seeded from image corners with Euclidean RGB
    color-distance matching.  Works for styles with a solid/near-uniform
    background.  Korean and lineart rely on outline strokes as BFS barriers;
    clay works despite no outlines because its background is very uniform (low
    gradient std ≈ 2–8) and well-separated from subject colours:

    - Korean (white background, strong outline barriers)
    - Lineart (orange/amber background, strong outline barriers)
    - Clay (warm gray/beige background, near-uniform, dist=50 safe)

    Not suitable for studio_3d (dark gradient bg std ≈ 20–36, overlaps dark
    hair/clothing; use remove_background() instead).

    Args:
        image_bytes: Raw image bytes (PNG / JPEG / etc.).
        feather:     If True applies a 0.8 px Gaussian blur to the alpha edge
                     for softer compositing.  False gives crisp comic-style edges.

    Returns:
        RGBA PNG bytes with background removed.
    """
    img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")

    # Pre-close: MinFilter darkens tiny bright gaps in outline strokes,
    # preventing the fill from leaking through sub-pixel breaks.
    rgb_closed = np.array(img.convert("RGB").filter(ImageFilter.MinFilter(3)))
    bg_color = _estimate_bg_color(rgb_closed)

    # Color-distance threshold: gap between bg (dist=0) and nearest subject
    # colour (skin ≈ dist 30–100 depending on style) is large — dist=50 is safe.
    dist_threshold = 50.0

    h, w = rgb_closed.shape[:2]
    keep = np.ones((h, w), dtype=bool)
    visited = np.zeros((h, w), dtype=bool)
    queue: deque[tuple[int, int]] = deque()

    def _is_bg(y: int, x: int) -> bool:
        return (
            float(np.sqrt(np.sum((rgb_closed[y, x].astype(float) - bg_color) ** 2)))
            <= dist_threshold
        )

    for sy, sx in [(0, 0), (0, w - 1), (h - 1, 0), (h - 1, w - 1)]:
        if _is_bg(sy, sx) and not visited[sy, sx]:
            queue.append((sy, sx))
            visited[sy, sx] = True

    while queue:
        y, x = queue.popleft()
        keep[y, x] = False
        for dy, dx in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and not visited[ny, nx]:
                if _is_bg(ny, nx):
                    visited[ny, nx] = True
                    queue.append((ny, nx))

    alpha = Image.fromarray((keep * 255).astype(np.uint8))
    if feather:
        alpha = alpha.filter(ImageFilter.GaussianBlur(radius=0.8))
    img.putalpha(alpha)

    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def remove_background_for_style(image_bytes: bytes, style: str, feather: bool = False) -> bytes:
    """Remove the background from an avatar image, routing by generation style.

    This is the preferred entry point for pipeline code.  Selects the correct
    strategy based on the style name:

    - ``korean`` / ``lineart`` / ``clay``  → flood-fill (fast, no ML, ~0.1–0.4s)
    - ``studio_3d`` / ``photorealistic``   → u2net + alpha-matting (~0.4–1.7s)

    Args:
        image_bytes: Raw image bytes (PNG / JPEG / etc.).
        style:       Generation style name (case-insensitive).
        feather:     Passed through to ``remove_background_illustration`` for
                     illustration styles (soft alpha edge).  Ignored for ML path.

    Returns:
        RGBA PNG bytes with background removed.

    Raises:
        ValueError: If ``style`` is not a recognised style name.
    """
    style = style.lower()
    if style in {"korean", "lineart", "clay"}:
        return remove_background_illustration(image_bytes, feather=feather)
    elif style in {"studio_3d", "photorealistic"}:
        return remove_background(image_bytes)
    else:
        raise ValueError(
            f"Unknown style {style!r}. "
            "Expected one of: korean, lineart, clay, studio_3d, photorealistic."
        )


def _has_existing_transparency(image_bytes: bytes) -> bool:
    """Return True if the image already has meaningful alpha transparency.

    Used to skip re-processing images that have already had their background
    removed.  Re-running u2net on a pre-extracted RGBA image degrades quality:
    transparent pixels are converted to black internally, causing dark clothing
    to be misidentified as background and removed.

    Threshold: >5% of pixels fully transparent signals an existing cutout.
    """
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode != "RGBA":
        return False
    a = np.array(img.split()[-1])
    return float((a == 0).sum()) / a.size > 0.05


def remove_background(image_bytes: bytes) -> bytes:
    """Remove the background using rembg u2net with alpha-matting.

    Required for studio_3d and photorealistic (gradient backgrounds that
    overlap subject colours; no outline barriers for flood-fill).
    For illustration styles (korean, lineart, clay) use
    ``remove_background_illustration`` which is faster and more accurate.

    If the image already has meaningful alpha transparency (>5% transparent
    pixels), it is returned as-is — re-running u2net on a pre-extracted RGBA
    image degrades quality because transparent pixels are filled with black
    internally, causing dark clothing to be mistaken for background.

    Returns RGBA PNG bytes with the background made transparent.
    """
    if _has_existing_transparency(image_bytes):
        img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
        out = io.BytesIO()
        img.save(out, format="PNG")
        return out.getvalue()

    import rembg

    result_bytes = rembg.remove(
        image_bytes,
        session=_get_rembg_session(),
        alpha_matting=True,
        alpha_matting_foreground_threshold=240,
        alpha_matting_background_threshold=10,
        alpha_matting_erode_size=10,
    )
    # Morphological closing: fill small interior holes in the alpha mask
    img = Image.open(io.BytesIO(result_bytes)).convert("RGBA")
    r, g, b, a = img.split()
    a = a.filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.MinFilter(7))
    img.putalpha(a)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
