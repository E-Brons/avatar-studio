#! .venv/bin/python3
"""Download celebrity example folders: persona.yml + portrait image.

Uses DuckDuckGo Images to find a portrait photo for each celebrity.
Creates assets/examples/{folder_name}/ with:
  - persona.yml  (basic personal info; appearance left empty for pipeline)
  - original.jpg / best.jpg (downloaded from Web image search)

Usage:
    python scripts/download_celebrity_examples.py [--dry-run] [--overwrite]

The candidate list lives in candidates.csv (same directory).  Edit that file
to add/remove entries or update aliases.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _appearance import extract_appearance, flat_to_persona_appearance  # noqa: E402
from _cv_scoring import compute_phash, compute_quality_score, is_duplicate  # noqa: E402

try:
    from config.gateway import GatewayClient

    _GATEWAY_AVAILABLE = True
except ImportError:
    _GATEWAY_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

EXAMPLES_DIR = ROOT / "assets" / "examples"
CANDIDATES_CSV = Path(__file__).resolve().parent / "candidates.csv"


# ── Candidate loader ──────────────────────────────────────────────────────────


def load_candidates(csv_path: Path | None = None) -> list[dict]:
    """Load candidate list from CSV, returning dicts with name/age/nationality/gender/pronouns/aliases."""
    path = csv_path or CANDIDATES_CSV
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            entry: dict = {
                "name": row["name"],
                "age": int(row["age"]) if row.get("age") else None,
                "nationality": row.get("nationality") or "",
                "gender": row.get("gender") or "",
            }
            if row.get("pronouns"):
                entry["pronouns"] = row["pronouns"]
            if row.get("aliases"):
                entry["aliases"] = row["aliases"].split("|")
            rows.append(entry)
    return rows


candidates: list[dict] = load_candidates()


# ── helpers ───────────────────────────────────────────────────────────────────


def _default_pronouns(gender: str) -> str:
    """Derive default pronouns from gender field."""
    return {"male": "he/him", "female": "she/her", "non-binary": "they/them"}.get(
        gender, "they/them"
    )


_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


_MIN_DIM = 768  # minimum width and height

# ── portrait validation ───────────────────────────────────────────────────────

_VALIDATION_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "passes": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["passes", "reason"],
    "additionalProperties": False,
}

_VALIDATION_OUTPUT_CONFIG: dict = {"format": {"type": "json_schema", "schema": _VALIDATION_SCHEMA}}

_VALIDATION_SYSTEM = (
    "You are a strict portrait photo quality checker for avatar generation. "
    "Evaluate the image against all criteria and return a single JSON result."
)


def _validate_portrait(
    image_bytes: bytes,
    name: str,
    gateway_url: str,
    timeout: int = 30,
) -> tuple[bool, str]:
    """Ask the vision LLM whether a portrait image meets quality requirements.

    Criteria:
    - Face is roughly frontal (slight tilts OK, no extreme side profiles)
    - Face occupies >= 30% of the frame
    - Face is not obscured by hands, objects, sunglasses, or opaque eyewear (hair is allowed)
    - Image is sharp and high quality (not blurry, noisy, or heavily processed)
    - Image is in full color (not grayscale, sepia, or monochromatic)
    - Image is a real photograph (not illustration, painting, CGI, cartoon, etc.)
    - No watermarks, text overlays, or logos visible

    Returns (passes, reason).  On LLM failure returns (True, "validation skipped")
    so the image is accepted rather than silently discarded.
    """
    if not _GATEWAY_AVAILABLE:
        return True, "validation skipped (gateway unavailable)"

    prompt = (
        f"Examine this portrait photo of {name}.\n\n"
        "Evaluate ALL of the following criteria:\n"
        "1. Face is roughly frontal — slight tilts or turns are acceptable; only reject clear side profiles or extreme angles\n"
        "2. Face fills at least 30% of the image frame\n"
        "3. Face is unobstructed — not covered by hands, microphones, large logos, or any other object; "
        "sunglasses or tinted/opaque eyewear are not allowed (clear/thin glasses frames are fine); "
        "own hair partially falling over the face is acceptable\n"
        "4. Image quality is high — sharp focus, good exposure, not pixelated or heavily compressed\n"
        "5. Image is in full color — not grayscale, sepia, black-and-white, or monochromatic "
        "(e.g. brown-toned, blue-toned, or any dominant single-hue tint)\n"
        "6. Image is a real photograph — not an illustration, painting, drawing, cartoon, CGI render, "
        "or any other non-photographic artwork\n"
        "7. No visible watermarks, text overlays, logos, or copyright stamps on the face\n\n"
        "Set passes=true only if ALL seven criteria are met. "
        "Set passes=false if any criterion fails, and state which one(s) in reason."
    )

    try:
        raw = GatewayClient(gateway_url).image_inspector(
            image_bytes,
            _VALIDATION_SYSTEM,
            prompt,
            timeout=timeout,
            output_config=_VALIDATION_OUTPUT_CONFIG,
        )
    except Exception as exc:
        logger.warning("  portrait validation LLM call failed: %s", exc)
        return True, f"validation skipped ({exc})"

    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()

    try:
        result = json.loads(text)
        passes = bool(result.get("passes", True))
        reason = str(result.get("reason", ""))
        return passes, reason
    except json.JSONDecodeError, AttributeError:
        return True, "validation skipped (parse error)"


def _folder_name(name: str) -> str:
    """Convert display name to snake_case folder name."""
    s = name.lower()
    s = re.sub(r"[^a-z0-9 ]", "", s)
    s = re.sub(r"\s+", "_", s.strip())
    return s


def _duckduckgo_image_candidates(name: str, query: str | None = None) -> list[tuple[str, int, int]]:
    """Return a list of (url, width, height) candidates from DuckDuckGo Images.

    Pre-filters to images where both dimensions are >= _MIN_DIM.
    Falls back to all results if none meet the size threshold.
    """
    if query is None:
        query = f"{name} portrait"

    encoded = urllib.parse.quote(query)
    init_url = f"https://duckduckgo.com/?q={encoded}&iax=images&ia=images"
    req0 = urllib.request.Request(init_url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req0, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        logger.warning("DuckDuckGo init request failed for %r: %s", name, exc)
        return []

    vqd_match = re.search(r'vqd=([\'"])([^\'"]+)\1', html)
    if not vqd_match:
        vqd_match = re.search(r'"vqd"\s*:\s*"([^"]+)"', html)
    if not vqd_match:
        logger.warning("DuckDuckGo: no VQD token found for %r", name)
        return []
    vqd = vqd_match.group(2) if vqd_match.lastindex >= 2 else vqd_match.group(1)

    params = {
        "l": "us-en",
        "o": "json",
        "q": query,
        "vqd": vqd,
        "f": ",,,,,",
        "p": "1",
    }
    img_url = "https://duckduckgo.com/i.js?" + urllib.parse.urlencode(params)
    req1 = urllib.request.Request(
        img_url, headers={**_HEADERS, "Referer": "https://duckduckgo.com/"}
    )
    try:
        with urllib.request.urlopen(req1, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        logger.warning("DuckDuckGo image search failed for %r: %s", name, exc)
        return []

    results = data.get("results", [])
    if not results:
        logger.warning("DuckDuckGo: no image results for %r", name)
        return []

    candidates: list[tuple[str, int, int]] = []
    fallback: list[tuple[str, int, int]] = []
    for r in results[:20]:
        url = r.get("image", "")
        if not url:
            continue
        w = int(r.get("width", 0) or 0)
        h = int(r.get("height", 0) or 0)
        if w >= _MIN_DIM and h >= _MIN_DIM:
            candidates.append((url, w, h))
        else:
            fallback.append((url, w, h))

    # Return qualifying images first; append fallbacks so we always have something to try.
    return candidates + fallback


def _fetch_image_bytes(url: str) -> bytes | None:
    """Download *url* and return raw bytes, or None on failure."""
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.read()
    except Exception as exc:
        logger.debug("  fetch failed for %s: %s", url.split("/")[-1][:60], exc)
        return None


# ── multi-image sourcing ──────────────────────────────────────────────────────

_QUERY_VARIATIONS = [
    "{name} portrait",
    "{name} headshot",
    "{name} interview",
    "{name} face close up",
]

_DEFAULT_MAX_CANDIDATES = 30
_DEFAULT_TOP_K = 5
_LLM_PRE_FILTER_K = 8  # how many CV-passing images to send through LLM validation
_DDQ_INTER_QUERY_SLEEP = 0.3  # seconds between DDG queries for same person


def _gather_all_candidates(
    name: str, max_candidates: int = _DEFAULT_MAX_CANDIDATES
) -> list[tuple[str, int, int]]:
    """Gather image candidates for *name* across multiple query variations.

    Returns a URL-deduplicated list of (url, width, height).
    """
    seen_urls: set[str] = set()
    result: list[tuple[str, int, int]] = []
    for tmpl in _QUERY_VARIATIONS:
        query = tmpl.format(name=name)
        for url, w, h in _duckduckgo_image_candidates(name, query=query):
            if url not in seen_urls:
                seen_urls.add(url)
                result.append((url, w, h))
        if len(result) >= max_candidates:
            break
        time.sleep(_DDQ_INTER_QUERY_SLEEP)
    return result[:max_candidates]


def _download_and_score_images(
    celeb: dict,
    candidates: list[tuple[str, int, int]],
    gateway_url: str,
    skip_llm: bool,
    pre_filter_k: int = _LLM_PRE_FILTER_K,
) -> list[dict]:
    """Download candidates, score with CV, deduplicate, and optionally LLM-validate.

    Returns a list of accepted image dicts sorted by quality score (best first):
        bytes, url, width, height, quality (dict), phash, llm_passes, llm_reason
    """
    accepted: list[dict] = []
    seen_hashes: list[str] = []

    for idx, (url, w, h) in enumerate(candidates):
        img_bytes = _fetch_image_bytes(url)
        if img_bytes is None:
            continue

        try:
            quality = compute_quality_score(img_bytes)
        except Exception as exc:
            logger.debug("  candidate %d: CV scoring failed: %s", idx + 1, exc)
            continue

        if not quality["has_face"]:
            logger.debug("  candidate %d: rejected (no face detected)", idx + 1)
            continue
        if not quality["color_ok"]:
            logger.debug("  candidate %d: rejected (color: %s)", idx + 1, quality["color_reason"])
            continue

        try:
            phash = compute_phash(img_bytes)
        except Exception as exc:
            logger.debug("  candidate %d: phash failed: %s", idx + 1, exc)
            phash = ""

        if phash and is_duplicate(phash, seen_hashes):
            logger.debug("  candidate %d: duplicate (phash)", idx + 1)
            continue
        if phash:
            seen_hashes.append(phash)

        accepted.append(
            {
                "bytes": img_bytes,
                "url": url,
                "width": w,
                "height": h,
                "quality": quality,
                "phash": phash,
                "llm_passes": True,
                "llm_reason": "",
            }
        )

    if not accepted:
        return []

    # Sort by composite score, take top pre_filter_k for LLM validation
    accepted.sort(key=lambda x: x["quality"]["composite_score"], reverse=True)
    top = accepted[:pre_filter_k]

    if skip_llm or not _GATEWAY_AVAILABLE:
        return top

    # LLM secondary validation pass
    llm_passed: list[dict] = []
    for item in top:
        passes, reason = _validate_portrait(item["bytes"], celeb["name"], gateway_url)
        item["llm_passes"] = passes
        item["llm_reason"] = reason
        if passes:
            llm_passed.append(item)
        else:
            logger.debug(
                "  LLM rejected candidate (score=%.3f): %s",
                item["quality"]["composite_score"],
                reason,
            )
    return llm_passed


# ── appearance aggregation ────────────────────────────────────────────────────

_IDENTITY_COLOR_FIELDS = [
    "skin_tone",
    "hair_color_base",
    "hair_color_shadow",
    "eye_color_iris",
    "eye_color_pupil",
    "brows_color",
]
_IDENTITY_ENUM_FIELDS = [
    "face_shape",
    "eye_shape",
    "nose_shape",
    "chin_shape",
    "cheeks_shape",
    "brows_style",
    "presentation",
]
_IDENTITY_TEXT_FIELDS = ["hair_style", "hair_note", "skin_texture"]


def _hex_to_rgb(h: str) -> tuple[int, int, int] | None:
    h = h.lstrip("#")
    if len(h) != 6:
        return None
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return None


def _rgb_to_lab(r: int, g: int, b: int) -> tuple[float, float, float]:
    """Convert sRGB (0–255) to CIELAB (D65 illuminant)."""

    def linearize(c: float) -> float:
        c /= 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    rl, gl, bl = linearize(r), linearize(g), linearize(b)
    x = 0.4124564 * rl + 0.3575761 * gl + 0.1804375 * bl
    y = 0.2126729 * rl + 0.7151522 * gl + 0.0721750 * bl
    z = 0.0193339 * rl + 0.1191920 * gl + 0.9503041 * bl

    xn, yn, zn = 0.95047, 1.00000, 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fy = f(y / yn)
    L = 116 * fy - 16
    a_val = 500 * (f(x / xn) - fy)
    b_val = 200 * (fy - f(z / zn))
    return L, a_val, b_val


def _median_hex_lab(hex_values: list[str]) -> str:
    """Return the median hex color by computing component-wise median in CIELAB space.

    Snaps to the nearest *actual* value in the set to avoid out-of-gamut synthetics.
    """
    rgbs = [_hex_to_rgb(h) for h in hex_values]
    valid_rgbs = [rgb for rgb in rgbs if rgb is not None]
    if not valid_rgbs:
        return "#808080"

    labs = [_rgb_to_lab(*rgb) for rgb in valid_rgbs]
    n = len(labs)
    l_med = sorted(lab[0] for lab in labs)[n // 2]
    a_med = sorted(lab[1] for lab in labs)[n // 2]
    b_med = sorted(lab[2] for lab in labs)[n // 2]

    # Snap to nearest actual value (avoid synthetic gamut violations)
    best_rgb = min(
        zip(labs, valid_rgbs),
        key=lambda pair: (
            (pair[0][0] - l_med) ** 2 + (pair[0][1] - a_med) ** 2 + (pair[0][2] - b_med) ** 2
        ),
    )[1]
    return "#{:02X}{:02X}{:02X}".format(*best_rgb)


def _consolidate_text_field(
    field: str, values: list[str], celeb_name: str, gateway_url: str
) -> str:
    """Use LLM text_gen to consolidate multiple descriptions into one."""
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    if not _GATEWAY_AVAILABLE:
        return values[0]

    lines = "\n".join(f"- {v}" for v in values)
    prompt = (
        f"These are {len(values)} descriptions of {celeb_name}'s {field} from different photos:\n"
        f"{lines}\n\n"
        f"Write a single authoritative description of {celeb_name}'s {field} capturing "
        "the consistent, stable features. Be concise (one phrase or sentence)."
    )
    try:
        raw = GatewayClient(gateway_url).text_gen([{"role": "user", "content": prompt}])
        return raw.strip()
    except Exception as exc:
        logger.debug("  text consolidation failed for %s.%s: %s", celeb_name, field, exc)
        return values[0]


def _aggregate_appearance(
    appearances: list[dict],
    celeb: dict,
    gateway_url: str,
) -> dict:
    """Aggregate appearance features from multiple per-image extractions.

    Colors → CIELAB median (snapped to nearest actual value)
    Enums/shapes → majority vote
    Free text → LLM consolidation
    Clothing/accessories are dropped (image-specific, not identity)
    """
    if not appearances:
        return {}
    if len(appearances) == 1:
        return dict(appearances[0])

    result: dict = {}

    for field in _IDENTITY_COLOR_FIELDS:
        vals = [a[field] for a in appearances if a.get(field)]
        if vals:
            result[field] = _median_hex_lab(vals)

    for field in _IDENTITY_ENUM_FIELDS:
        vals = [a[field] for a in appearances if a.get(field)]
        if vals:
            result[field] = Counter(vals).most_common(1)[0][0]

    for field in _IDENTITY_TEXT_FIELDS:
        vals = [a[field] for a in appearances if a.get(field)]
        if vals:
            result[field] = _consolidate_text_field(field, vals, celeb["name"], gateway_url)

    # Pass-through fields: take first non-"unknown" value
    for field in ("zodiac", "religion", "suggested_bg_color"):
        for a in appearances:
            v = a.get(field, "")
            if v and v not in ("unknown", ""):
                result[field] = v
                break
        if field not in result and appearances:
            fallback = appearances[0].get(field)
            if fallback:
                result[field] = fallback

    return result


# ── multi-image storage ───────────────────────────────────────────────────────


def _save_multi_images(folder: Path, selected_images: list[dict]) -> Path:
    """Save selected images to folder/images/ and write metadata.json.

    Returns the images/ directory path.
    """
    images_dir = folder / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    metadata_entries: list[dict] = []
    for i, img in enumerate(selected_images, 1):
        fname = f"{i:03d}.jpg"
        (images_dir / fname).write_bytes(img["bytes"])
        q = img["quality"]
        metadata_entries.append(
            {
                "file": f"images/{fname}",
                "url": img["url"],
                "width": img["width"],
                "height": img["height"],
                "quality_score": q["composite_score"],
                "quality": {
                    "composite_score": q["composite_score"],
                    "has_face": q["has_face"],
                    "face_count": q["face_count"],
                    "blur_score": q["blur_score"],
                    "blur_raw": q["blur_raw"],
                    "resolution_score": q["resolution_score"],
                    "frontality_score": q["frontality_score"],
                    "color_ok": q["color_ok"],
                    "color_reason": q["color_reason"],
                },
                "llm_passes": img.get("llm_passes"),
                "llm_reason": img.get("llm_reason", ""),
                "phash": img.get("phash", ""),
            }
        )

    shutil.copy2(images_dir / "001.jpg", images_dir / "best.jpg")

    meta = {
        "count": len(selected_images),
        "best": "images/best.jpg",
        "images": metadata_entries,
    }
    (images_dir / "metadata.json").write_text(json.dumps(meta, indent=2))
    return images_dir


def _persona_yml(
    celeb: dict,
    appearance: dict | None = None,
    image_meta: dict | None = None,
) -> str:
    """Return persona.yml content for *celeb*.

    *appearance* is the aggregated identity appearance dict.
    *image_meta* is the metadata from _save_multi_images (optional).
    Clothing and accessories are intentionally excluded (image-specific).
    """
    app = dict(appearance) if appearance else {}

    bg_color = app.pop("suggested_bg_color", "#4A90D9")
    zodiac = app.pop("zodiac", "unknown")
    religion = app.pop("religion", "unknown")

    app_section = flat_to_persona_appearance(app)

    pronouns = celeb.get("pronouns") or _default_pronouns(celeb["gender"])

    data: dict = {
        "personal": {
            "name": celeb["name"],
            "gender": celeb["gender"],
            "pronouns": pronouns,
            "age": celeb["age"],
            "nationality": celeb["nationality"],
            "religion": religion,
            "zodiac": zodiac,
        },
        "style": {
            "bg_color": bg_color,
            "fg_color": "#FFFFFF",
        },
        "appearance": app_section,
    }

    if image_meta:
        data["images"] = {
            "count": image_meta.get("count", 0),
            "best": image_meta.get("best", ""),
            "sources": [
                {"file": img["file"], "quality_score": img["quality_score"]}
                for img in image_meta.get("images", [])
            ],
        }

    return yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)


# ── main ──────────────────────────────────────────────────────────────────────

_RESULT_OK = "ok"
_RESULT_SKIP = "skip"
_RESULT_FAIL = "fail"


def _process_celeb(
    celeb: dict,
    overwrite: bool,
    gateway_url: str,
    skip_llm: bool,
    personas_only: bool,
    dry_run: bool,
    top_k: int = _DEFAULT_TOP_K,
    max_candidates: int = _DEFAULT_MAX_CANDIDATES,
) -> str:
    """Process a single celebrity — download images + write persona.yml.

    Returns one of _RESULT_OK / _RESULT_SKIP / _RESULT_FAIL.
    """
    folder = EXAMPLES_DIR / _folder_name(celeb["name"])
    persona_path = folder / "persona.yml"
    images_dir = folder / "images"
    legacy_image = folder / "original.jpg"

    # Determine whether images already exist (multi-image or legacy)
    has_images = images_dir.exists() and any(images_dir.glob("*.jpg"))
    has_legacy = legacy_image.exists()
    is_complete = folder.exists() and persona_path.exists() and (has_images or has_legacy)

    if personas_only:
        # Re-generate persona.yml from existing images without re-downloading
        if not has_images and not has_legacy:
            logger.info("skip  %s (no images found)", celeb["name"])
            return _RESULT_SKIP
        if persona_path.exists() and not overwrite:
            logger.info("skip  %s (persona.yml exists)", celeb["name"])
            return _RESULT_SKIP
        logger.info("── %s ── (persona only)", celeb["name"])
        if dry_run:
            logger.info("  [dry-run] would write persona.yml")
            return _RESULT_OK

        # Find available images for extraction
        if has_images:
            image_paths = sorted(images_dir.glob("[0-9]*.jpg"))
            image_meta_path = images_dir / "metadata.json"
            image_meta: dict | None = None
            if image_meta_path.exists():
                try:
                    image_meta = json.loads(image_meta_path.read_text())
                except Exception:
                    pass
        else:
            image_paths = [legacy_image]
            image_meta = None

        appearances: list[dict] = []
        if not skip_llm:
            for img_path in image_paths[:top_k]:
                try:
                    app = extract_appearance(
                        GatewayClient(gateway_url), img_path.read_bytes(), celeb["name"]
                    )
                    if app:
                        appearances.append(app)
                except Exception as exc:
                    logger.warning(
                        "  %s: appearance extraction error (%s): %s",
                        celeb["name"],
                        img_path.name,
                        exc,
                    )

        aggregated = _aggregate_appearance(appearances, celeb, gateway_url) if appearances else None
        persona_path.write_text(_persona_yml(celeb, aggregated, image_meta))
        logger.info(
            "  %s: wrote persona.yml%s",
            celeb["name"],
            f" (aggregated from {len(appearances)} images)"
            if appearances
            else " (appearance empty)",
        )
        return _RESULT_OK

    if is_complete and not overwrite:
        logger.info("skip  %s (already complete)", celeb["name"])
        return _RESULT_SKIP

    logger.info("── %s ──", celeb["name"])

    if dry_run:
        logger.info("  [dry-run] would create %s", folder.relative_to(ROOT))
        return _RESULT_OK

    folder.mkdir(parents=True, exist_ok=True)

    # Gather, score, and select images
    if overwrite or not has_images:
        candidates = _gather_all_candidates(celeb["name"], max_candidates=max_candidates)
        if not candidates:
            logger.warning("  no image candidates found for %s", celeb["name"])
            return _RESULT_FAIL

        scored = _download_and_score_images(celeb, candidates, gateway_url, skip_llm)
        if not scored:
            logger.warning("  no valid portraits found for %s after scoring", celeb["name"])
            return _RESULT_FAIL

        selected = scored[:top_k]
        logger.info(
            "  %s: selected %d/%d images (top score=%.3f)",
            celeb["name"],
            len(selected),
            len(scored),
            selected[0]["quality"]["composite_score"],
        )

        _save_multi_images(folder, selected)
        logger.info("  %s: saved %d images to images/", celeb["name"], len(selected))
        new_images_dir = folder / "images"
    else:
        new_images_dir = images_dir

    # Extract appearance from selected images
    appearances = []
    if not skip_llm and (overwrite or not persona_path.exists()):
        image_paths = sorted(new_images_dir.glob("[0-9]*.jpg"))
        for img_path in image_paths[:top_k]:
            try:
                app = extract_appearance(
                    GatewayClient(gateway_url), img_path.read_bytes(), celeb["name"]
                )
                if app:
                    appearances.append(app)
            except Exception as exc:
                logger.warning(
                    "  %s: appearance extraction error (%s): %s", celeb["name"], img_path.name, exc
                )

    # Load image metadata for persona.yml
    image_meta = None
    meta_path = new_images_dir / "metadata.json"
    if meta_path.exists():
        try:
            image_meta = json.loads(meta_path.read_text())
        except Exception:
            pass

    # Aggregate and write persona.yml
    if overwrite or not persona_path.exists():
        aggregated = _aggregate_appearance(appearances, celeb, gateway_url) if appearances else None
        persona_path.write_text(_persona_yml(celeb, aggregated, image_meta))
        logger.info(
            "  %s: wrote persona.yml%s",
            celeb["name"],
            f" (aggregated from {len(appearances)} images)"
            if appearances
            else " (appearance empty)",
        )

    return _RESULT_OK


def run(
    dry_run: bool = False,
    overwrite: bool = False,
    gateway_url: str = "http://127.0.0.1:4096",
    skip_llm: bool = False,
    personas_only: bool = False,
    workers: int = 8,
    top_k: int = _DEFAULT_TOP_K,
    max_candidates: int = _DEFAULT_MAX_CANDIDATES,
    filter_names: set[str] | None = None,
) -> None:
    celebrities = candidates
    if filter_names:
        celebrities = [c for c in candidates if c["name"] in filter_names]
        logger.info("Filtered to %d celebrities", len(celebrities))

    ok = skipped = failed = 0

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _process_celeb,
                celeb,
                overwrite,
                gateway_url,
                skip_llm,
                personas_only,
                dry_run,
                top_k,
                max_candidates,
            ): celeb
            for celeb in celebrities
        }
        for future in as_completed(futures):
            celeb = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                logger.error("  %s: unhandled error: %s", celeb["name"], exc)
                result = _RESULT_FAIL
            if result == _RESULT_OK:
                ok += 1
            elif result == _RESULT_SKIP:
                skipped += 1
            else:
                failed += 1

    logger.info("")
    logger.info(
        "Done. ok=%d  skipped=%d  failed=%d  total=%d", ok, skipped, failed, len(celebrities)
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download celebrity example folders")
    parser.add_argument("--dry-run", action="store_true", help="List what would be done")
    parser.add_argument(
        "--overwrite", action="store_true", help="Re-download even if folder exists"
    )
    parser.add_argument(
        "--gateway",
        default="http://127.0.0.1:4096",
        help="LLM Gateway URL for appearance extraction (default: http://127.0.0.1:4096)",
    )
    parser.add_argument(
        "--skip-llm",
        action="store_true",
        help="Skip LLM appearance extraction and write empty appearance",
    )
    parser.add_argument(
        "--personas-only",
        action="store_true",
        help="Skip image download — only (re)generate persona.yml from existing images",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Number of parallel download workers (default: 8)",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=_DEFAULT_TOP_K,
        help=f"Number of top images to keep per celebrity (default: {_DEFAULT_TOP_K})",
    )
    parser.add_argument(
        "--max-candidates",
        type=int,
        default=_DEFAULT_MAX_CANDIDATES,
        help=f"Max image candidates to gather per celebrity (default: {_DEFAULT_MAX_CANDIDATES})",
    )
    parser.add_argument(
        "--filter",
        default="",
        help="Comma-separated celebrity names to process (default: all)",
    )
    parser.add_argument(
        "--enrich",
        action="store_true",
        help="After download, enrich persona.yml files via Wikipedia + image analysis",
    )
    parser.add_argument(
        "--audit-quality",
        action="store_true",
        help="After download/enrich, run portrait quality audit",
    )
    parser.add_argument(
        "--audit-variety",
        action="store_true",
        help="After download/enrich, run persona coverage audit",
    )
    args = parser.parse_args()
    filter_names: set[str] | None = None
    if args.filter:
        filter_names = {n.strip() for n in args.filter.split(",") if n.strip()}
    run(
        dry_run=args.dry_run,
        overwrite=args.overwrite,
        gateway_url=args.gateway,
        skip_llm=args.skip_llm,
        personas_only=args.personas_only,
        workers=args.workers,
        top_k=args.top_k,
        max_candidates=args.max_candidates,
        filter_names=filter_names,
    )
    if args.enrich:
        from enrich_persona import run_enrich

        run_enrich(
            gateway_url=args.gateway,
            dry_run=args.dry_run,
            overwrite=args.overwrite,
            workers=args.workers,
        )
    if args.audit_quality:
        from audit_examples import run_quality_audit

        run_quality_audit(gateway=args.gateway, skip_llm=args.skip_llm, dry_run=args.dry_run)
    if args.audit_variety:
        from audit_examples import run_variety_audit

        run_variety_audit()
