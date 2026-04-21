"""Portrait square crop: detect face and crop to portrait frame (waist → top of head).

Algorithm:
  1. Load image with OpenCV.
  2. Detect the largest frontal face using a Haar cascade.
  3. Compute a square crop:
       side  = SCALE * face_height     (default SCALE = 3.5)
       top   = face_top − TOP_PAD * face_height  (default TOP_PAD = 0.5)
       left  = face_center_x − side / 2
  4. Clamp the box to the image boundary; shrink *side* if needed.
  5. Fallback (no face detected):
       - Portrait image (h ≥ w): top-center square.
       - Landscape image (w > h): center square.
  6. Save back to best.jpg at 95 % JPEG quality.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)


def _cascade_xml() -> str:
    """Return the absolute path to haarcascade_frontalface_default.xml.

    Search order:
      1. cv2.data.haarcascades  — opencv-python >= 4.x standard install.
      2. <cv2_package_dir>/data/  — some system builds put it here.
      3. Project .venv           — opencv-python-headless installed in the venv
                                   even when the system Python uses a bare OpenCV.
    """
    filename = "haarcascade_frontalface_default.xml"

    # 1. Preferred: cv2.data submodule.
    if hasattr(cv2, "data") and hasattr(cv2.data, "haarcascades"):
        return cv2.data.haarcascades + filename

    # 2. Fallback: file next to the cv2 package.
    cv2_dir = os.path.dirname(cv2.__file__)
    candidate = os.path.join(cv2_dir, "data", filename)
    if os.path.exists(candidate):
        return candidate

    # 3. Last resort: search inside the project .venv.
    venv_lib = Path(__file__).resolve().parents[2] / ".venv" / "lib"
    for p in venv_lib.glob(f"*/site-packages/cv2/data/{filename}"):
        if p.exists():
            return str(p)

    raise RuntimeError(
        f"Cannot find {filename} (cv2 dir: {cv2_dir}). "
        "Run scripts/install.sh to install opencv-python-headless into .venv."
    )


# ── Tunable constants ─────────────────────────────────────────────────────────

# Total square side as a multiple of face height.
# 2.0 × gives roughly: 0.5 fh above forehead + 1 fh face + 0.5 fh chin/neck.
# This keeps the face at ~50 % of the image height, which InsightFace needs for
# reliable embedding extraction.  A 3.5× "waist-level" crop left the face at only
# ~29 % — right at InsightFace's degradation threshold.
_SCALE: float = 2.0

# Extra headroom above the face top (in face-height units).
# The Haar cascade bounding box typically starts at the eyebrow line, not the
# top of the head.  0.7× adds enough room to include forehead + hair.
_TOP_PAD: float = 0.7

# Minimum side length (pixels) for the output square.
# 512 px ensures the face is large enough for InsightFace / IPAdapter face-ID detection.
_MIN_SIDE: int = 512

# A square is "already close enough" if both dimensions differ by less than this ratio.
_SQUARE_TOLERANCE: float = 0.02


# ── Internal helpers ──────────────────────────────────────────────────────────


def _detect_face(img_bgr: np.ndarray) -> tuple[int, int, int, int] | None:
    """Return (x, y, w, h) of the largest detected frontal face, or None."""
    cascade_path = _cascade_xml()
    detector = cv2.CascadeClassifier(cascade_path)
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    faces = detector.detectMultiScale(
        gray,
        scaleFactor=1.1,
        minNeighbors=5,
        minSize=(30, 30),
    )
    if len(faces) == 0:
        return None
    # Return the largest face by area.
    return max(faces, key=lambda f: f[2] * f[3])


def _square_crop_box(
    img_h: int,
    img_w: int,
    face: tuple[int, int, int, int] | None,
) -> tuple[int, int, int]:
    """Compute (top, left, side) for the portrait square crop.

    When *face* is None, falls back to:
      - Portrait (h >= w): top-center square.
      - Landscape (w > h): center square.

    Clamping strategy: **shift the box** to stay within image bounds rather than
    shrinking it (shrinking cuts off the face when it is near an edge).  Side is
    only reduced when the image itself is smaller than *side*.
    """
    if face is not None:
        fx, fy, fw, fh = face
        side = max(_MIN_SIDE, int(_SCALE * fh))
        top = fy - int(_TOP_PAD * fh)
        left = (fx + fw // 2) - side // 2
    else:
        # Fallback: no face detected.
        side = min(img_h, img_w)
        if img_h >= img_w:
            # Portrait — take top-center square.
            top = 0
            left = (img_w - side) // 2
        else:
            # Landscape — take center square.
            top = (img_h - side) // 2
            left = (img_w - side) // 2

    # Cap side to the image dimensions first.
    side = min(side, img_h, img_w)

    # Shift the box so it fits entirely within the image (never shrink past this).
    left = max(0, min(left, img_w - side))
    top = max(0, min(top, img_h - side))

    return top, left, side


# ── Public API ────────────────────────────────────────────────────────────────


def crop_portrait_bytes(image_bytes: bytes) -> tuple[bytes, str]:
    """Crop *image_bytes* to a square portrait.

    Returns ``(jpeg_bytes, method)`` where *method* is ``"face"`` or ``"fallback"``.
    Raises ``ValueError`` if the image cannot be decoded.
    """
    arr = np.frombuffer(image_bytes, np.uint8)
    img_bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img_bgr is None:
        raise ValueError("Failed to decode image bytes")

    img_h, img_w = img_bgr.shape[:2]
    face = _detect_face(img_bgr)
    method = "face" if face is not None else "fallback"

    top, left, side = _square_crop_box(img_h, img_w, face)
    cropped = img_bgr[top : top + side, left : left + side]

    ok, buf = cv2.imencode(".jpg", cropped, [cv2.IMWRITE_JPEG_QUALITY, 95])
    if not ok:
        raise RuntimeError("Failed to JPEG-encode cropped image")
    return bytes(buf), method


def crop_portrait_file(
    path: Path,
    *,
    source: Path | None = None,
    dry_run: bool = False,
    overwrite: bool = False,
) -> str:
    """Crop a portrait image to a square and write the result to *path*.

    *source* is the file to read pixels from (default: same as *path*).
    Use ``source=original_001_path`` to always crop from the full-resolution
    original, even when *path* (best.jpg) has already been cropped in a prior run.

    Returns one of: ``"cropped_face"``, ``"cropped_fallback"``, ``"skipped"``, ``"error"``.
    Returns ``"skipped"`` when *source* (or *path* if no source) is already square
    within tolerance, unless *overwrite* is True.
    """
    read_path = source if source is not None else path
    try:
        image_bytes = read_path.read_bytes()
    except OSError as exc:
        logger.warning("Cannot read %s: %s", read_path, exc)
        return "error"

    # Quick dimension check via PIL to avoid full OpenCV decode.
    try:
        from PIL import Image

        with Image.open(read_path) as img:
            w, h = img.size
        if not overwrite and abs(w - h) / max(w, h) < _SQUARE_TOLERANCE:
            return "skipped"
    except Exception:
        pass  # PIL unavailable or unreadable — proceed anyway.

    try:
        cropped_bytes, method = crop_portrait_bytes(image_bytes)
    except Exception as exc:
        logger.warning("Crop failed for %s: %s", read_path, exc)
        return "error"

    if not dry_run:
        path.write_bytes(cropped_bytes)
        logger.debug("  Cropped %s (%s)", path.name, method)

    return f"cropped_{method}"
