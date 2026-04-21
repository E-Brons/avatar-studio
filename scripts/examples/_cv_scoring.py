"""Fast, non-LLM image quality scoring for portrait selection.

Uses OpenCV (haarcascade face detection, Laplacian blur) and imagehash
(perceptual deduplication). No LLM calls — all CPU/local computation.

Intended as a pre-filter before the LLM-based _validate_portrait() check.
"""

from __future__ import annotations

import colorsys
import io
import math
import os
from pathlib import Path

import cv2
import imagehash
import numpy as np
from PIL import Image

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

_GRAYSCALE_SAT_THRESHOLD: float = 0.20
_SEPIA_RB_DIFF: float = 60.0
_SEPIA_SAT_THRESHOLD: float = 0.20

_BLUR_SHARP_THRESHOLD: float = 100.0  # Laplacian variance — above = sharp
_BLUR_VERY_SHARP: float = 300.0

_FACE_SIZE_TIERS: list[tuple[int, float]] = [
    (512, 1.0),
    (256, 0.7),
    (128, 0.4),
    (0, 0.1),
]

_PHASH_SIZE: int = 16  # 256-bit hash
_DUPLICATE_THRESHOLD: int = 12  # Hamming distance


# ---------------------------------------------------------------------------
# Face detection
# ---------------------------------------------------------------------------


def _cascade_xml() -> str:
    """Return the absolute path to haarcascade_frontalface_default.xml.

    Same multi-location search as _portrait_crop._cascade_xml().
    """
    filename = "haarcascade_frontalface_default.xml"
    if hasattr(cv2, "data") and hasattr(cv2.data, "haarcascades"):
        return cv2.data.haarcascades + filename
    cv2_dir = os.path.dirname(cv2.__file__)
    candidate = os.path.join(cv2_dir, "data", filename)
    if os.path.exists(candidate):
        return candidate
    venv_lib = Path(__file__).resolve().parents[2] / ".venv" / "lib"
    for p in venv_lib.glob(f"*/site-packages/cv2/data/{filename}"):
        if p.exists():
            return str(p)
    raise RuntimeError(
        f"Cannot find {filename} (cv2 dir: {cv2_dir}). "
        "Run scripts/install.sh to install opencv-python-headless into .venv."
    )


# Resolved once at import time (single-threaded), reused read-only afterwards.
_CASCADE_XML: str = _cascade_xml()


def _new_cascade() -> cv2.CascadeClassifier:
    """Return a fresh CascadeClassifier.

    A new object is created per call so that concurrent threads never share
    the same classifier instance — OpenCV's detectMultiScale is not safe when
    the same CascadeClassifier is called from multiple threads simultaneously.
    """
    return cv2.CascadeClassifier(_CASCADE_XML)


def detect_faces(image_bytes: bytes) -> list[dict]:
    """Detect frontal faces in an image.

    Returns a list of dicts with keys:
        x, y, w, h       — bounding box
        confidence       — proxy confidence [0, 3] based on multi-threshold detection
        aspect_ratio     — w/h (near 1.0 = frontal, far from 1.0 = profile/tilted)
    """
    arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return []

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    cascade = _new_cascade()

    # Run at three strictness levels; more detections = higher confidence
    detections_by_level: list[list] = []
    for min_neighbors in (3, 5, 7):
        faces = cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=min_neighbors, minSize=(64, 64)
        )
        detections_by_level.append([] if len(faces) == 0 else faces.tolist())

    # Use strictest available detection set for bboxes
    canonical: list = []
    for faces in reversed(detections_by_level):
        if faces:
            canonical = faces
            break
    if not canonical:
        return []

    # Count how many strictness levels detected faces (proxy for confidence)
    levels_hit = sum(1 for f in detections_by_level if f)

    result = []
    for x, y, w, h in canonical:
        result.append(
            {
                "x": int(x),
                "y": int(y),
                "w": int(w),
                "h": int(h),
                "confidence": levels_hit,  # 1-3
                "aspect_ratio": w / h if h > 0 else 1.0,
            }
        )
    return result


# ---------------------------------------------------------------------------
# Blur scoring
# ---------------------------------------------------------------------------


def face_blur_score(image_bytes: bytes, face_bbox: dict) -> float:
    """Laplacian variance of the face crop. Higher = sharper.

    Returns 0.0 if the crop cannot be extracted.
    """
    arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return 0.0

    x, y, w, h = face_bbox["x"], face_bbox["y"], face_bbox["w"], face_bbox["h"]
    crop = img[y : y + h, x : x + w]
    if crop.size == 0:
        return 0.0

    return float(cv2.Laplacian(crop, cv2.CV_64F).var())


# ---------------------------------------------------------------------------
# Resolution scoring
# ---------------------------------------------------------------------------


def face_resolution_score(face_bbox: dict) -> float:
    """0-1 score based on face bounding-box pixel size."""
    face_w = face_bbox["w"]
    for threshold, score in _FACE_SIZE_TIERS:
        if face_w >= threshold:
            return score
    return 0.1


# ---------------------------------------------------------------------------
# Color balance check (canonical implementation — used by both download + audit)
# ---------------------------------------------------------------------------


def color_balance_check(image_bytes: bytes) -> tuple[bool, str]:
    """Check whether the image has acceptable colour balance.

    Returns (passes: bool, reason: str).
    Rejects:
      - Grayscale/monochrome images (mean HSV saturation < 0.08)
      - Sepia/brown-tinted images (R−B mean > 60 AND saturation < 0.20)
    """
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB").resize((64, 64), Image.LANCZOS)
    except Exception as exc:
        return False, f"cannot decode image ({exc})"

    pixels = list(img.getdata())
    r_sum = g_sum = b_sum = sat_sum = 0.0
    for r, g, b in pixels:
        r_sum += r
        g_sum += g
        b_sum += b
        _, s, _ = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
        sat_sum += s

    n = len(pixels)
    r_mean = r_sum / n
    b_mean = b_sum / n
    sat_mean = sat_sum / n

    if sat_mean < _GRAYSCALE_SAT_THRESHOLD:
        return (
            False,
            f"grayscale/monochrome (mean HSV saturation={sat_mean:.3f} < {_GRAYSCALE_SAT_THRESHOLD})",
        )

    rb_diff = r_mean - b_mean
    if rb_diff > _SEPIA_RB_DIFF and sat_mean < _SEPIA_SAT_THRESHOLD:
        return (
            False,
            f"sepia/brown tint (R−B={rb_diff:.0f} > {_SEPIA_RB_DIFF}, "
            f"saturation={sat_mean:.3f} < {_SEPIA_SAT_THRESHOLD})",
        )

    return True, ""


# ---------------------------------------------------------------------------
# Frontality score (from face aspect ratio)
# ---------------------------------------------------------------------------


def _frontality_score(face: dict) -> float:
    """Estimate how frontal-facing the face is from its aspect ratio.

    A perfect frontal face has aspect_ratio ~1.0.
    Scores drop off as the ratio deviates from 1.0.
    """
    ar = face.get("aspect_ratio", 1.0)
    deviation = abs(ar - 1.0)
    # Map 0.0 deviation → 1.0, 0.5+ deviation → 0.0
    return max(0.0, 1.0 - deviation / 0.5)


def _blur_to_score(laplacian_var: float) -> float:
    """Sigmoid-like mapping of Laplacian variance to [0, 1]."""
    if laplacian_var <= 0:
        return 0.0
    # log scale: 50 → ~0.4, 100 → ~0.6, 300 → ~0.9
    return min(1.0, math.log1p(laplacian_var) / math.log1p(_BLUR_VERY_SHARP))


# ---------------------------------------------------------------------------
# Composite quality score
# ---------------------------------------------------------------------------


def compute_quality_score(image_bytes: bytes) -> dict:
    """Compute a composite quality score for a portrait image.

    Returns a dict with:
        has_face        — bool: required; score=0 if False
        face_count      — int
        best_face       — dict | None: bbox of the largest/most-confident face
        blur_score      — float: Laplacian variance (higher = sharper)
        resolution_score — float [0, 1]
        frontality_score — float [0, 1]
        color_ok        — bool
        color_reason    — str
        composite_score — float [0, 1]
    """
    color_ok, color_reason = color_balance_check(image_bytes)

    faces = detect_faces(image_bytes)
    has_face = len(faces) > 0
    face_count = len(faces)

    best_face: dict | None = None
    blur = 0.0
    res_score = 0.0
    front_score = 0.0

    if has_face:
        # Pick largest face by area
        best_face = max(faces, key=lambda f: f["w"] * f["h"])
        blur = face_blur_score(image_bytes, best_face)
        res_score = face_resolution_score(best_face)
        front_score = _frontality_score(best_face)

    blur_score = _blur_to_score(blur)

    # Face count penalty: ideal = 1; 0 or 2+ reduce score
    if face_count == 1:
        face_count_factor = 1.0
    elif face_count == 0:
        face_count_factor = 0.0
    else:
        face_count_factor = 0.6  # multiple faces — probably not a clean portrait

    if not has_face or not color_ok:
        composite = 0.0
    else:
        composite = (
            0.30 * res_score
            + 0.25 * blur_score
            + 0.20 * front_score
            + 0.15 * (1.0 if color_ok else 0.0)
            + 0.10 * face_count_factor
        )

    return {
        "has_face": has_face,
        "face_count": face_count,
        "best_face": best_face,
        "blur_raw": blur,
        "blur_score": blur_score,
        "resolution_score": res_score,
        "frontality_score": front_score,
        "color_ok": color_ok,
        "color_reason": color_reason,
        "composite_score": round(composite, 4),
    }


# ---------------------------------------------------------------------------
# Perceptual hashing
# ---------------------------------------------------------------------------


def compute_phash(image_bytes: bytes) -> str:
    """Compute a 256-bit perceptual hash of an image. Returns hex string."""
    img = Image.open(io.BytesIO(image_bytes))
    return str(imagehash.phash(img, hash_size=_PHASH_SIZE))


def hamming_distance(hash1: str, hash2: str) -> int:
    """Hamming distance between two hex pHash strings."""
    h1 = imagehash.hex_to_hash(hash1)
    h2 = imagehash.hex_to_hash(hash2)
    return h1 - h2


def is_duplicate(
    new_hash: str, existing_hashes: list[str], threshold: int = _DUPLICATE_THRESHOLD
) -> bool:
    """Return True if new_hash is within threshold hamming distance of any existing hash."""
    for h in existing_hashes:
        if hamming_distance(new_hash, h) <= threshold:
            return True
    return False
