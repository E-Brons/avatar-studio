"""Audit assets/examples/*/original.jpg and remove sub-standard entries.

Checks run in order:
  1. Resolution  — hard fail if either dimension < 512 px
  2. Colour balance — grayscale (mean HSV saturation < 0.08) or sepia/brown
                      (R−B channel mean > 60 AND saturation < 0.20)
  3. Portrait quality — calls the LLM gateway (_validate_portrait) when
                        available; flags as "needs-review" without gateway,
                        but does NOT delete.

Usage:
    python scripts/audit_examples.py --dry-run          # report only, no deletions
    python scripts/audit_examples.py                    # interactive confirmation per folder
    python scripts/audit_examples.py --auto-remove      # delete without confirmation
    python scripts/audit_examples.py --gateway http://host:4096
    python scripts/audit_examples.py --skip-llm         # pixel-checks only
"""

from __future__ import annotations

import argparse
import colorsys
import json
import logging
import re
import shutil
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

try:
    from config.gateway import GatewayClient

    _GATEWAY_AVAILABLE = True
except ImportError:
    _GATEWAY_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

EXAMPLES_DIR = ROOT / "assets" / "examples"

# ── Thresholds ────────────────────────────────────────────────────────────────

_MIN_DIM = 512                    # minimum width or height in pixels
_GRAYSCALE_SAT_THRESHOLD = 0.08   # mean HSV saturation below this → grayscale
_SEPIA_SAT_THRESHOLD = 0.20       # combined with R-B check → sepia/brown
_SEPIA_RB_DIFF = 60               # R_mean − B_mean above this → sepia/brown tint

# ── LLM validation (mirrors download_examples.py) ────────────────────────────

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
    """Ask the vision LLM whether a portrait meets quality requirements.

    Returns (passes, reason).  On any failure returns (True, reason) so the
    image is accepted rather than wrongly discarded.
    """
    if not _GATEWAY_AVAILABLE:
        return True, "validation skipped (gateway client unavailable)"

    prompt = (
        f"Examine this portrait photo of {name}.\n\n"
        "Evaluate ALL of the following criteria:\n"
        "1. Face is roughly frontal — slight tilts or turns are acceptable; "
        "only reject clear side profiles or extreme angles\n"
        "2. Face fills at least 30% of the image frame\n"
        "3. Face is unobstructed — not covered by hands, microphones, large logos, or any "
        "other object; sunglasses or tinted/opaque eyewear are not allowed (clear/thin "
        "glasses frames are fine); own hair partially falling over the face is acceptable\n"
        "4. Image quality is high — sharp focus, good exposure, not pixelated or heavily "
        "compressed\n"
        "5. Image is in full color — not grayscale, sepia, black-and-white, or monochromatic "
        "(e.g. brown-toned, blue-toned, or any dominant single-hue tint)\n"
        "6. Image is a real photograph — not an illustration, painting, drawing, cartoon, "
        "CGI render, or any other non-photographic artwork\n"
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
        logger.warning("  LLM call failed for %r: %s", name, exc)
        return True, f"validation skipped ({exc})"

    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()

    try:
        result = json.loads(text)
        return bool(result.get("passes", True)), str(result.get("reason", ""))
    except (json.JSONDecodeError, AttributeError):
        return True, "validation skipped (parse error)"


# ── Pixel-level checks ────────────────────────────────────────────────────────


def _check_resolution(img: Image.Image) -> tuple[bool, str]:
    w, h = img.size
    if w < _MIN_DIM or h < _MIN_DIM:
        return False, f"too small ({w}×{h}, minimum {_MIN_DIM}px per side)"
    return True, ""


def _check_color_balance(img: Image.Image) -> tuple[bool, str]:
    """Check for grayscale / sepia using a fast 64×64 thumbnail."""
    thumb = img.convert("RGB").resize((64, 64), Image.LANCZOS)
    pixels = list(thumb.getdata())

    r_sum = g_sum = b_sum = 0.0
    sat_sum = 0.0
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


# ── Per-folder audit ──────────────────────────────────────────────────────────

_VERDICT_PASS = "pass"
_VERDICT_FAIL = "fail"
_VERDICT_REVIEW = "needs-review"  # LLM unavailable — manual inspection required


def _audit_folder(folder: Path, gateway_url: str, skip_llm: bool) -> dict:
    """Audit one example folder; return a result dict."""
    result: dict = {
        "name": folder.name,
        "path": folder,
        "verdict": _VERDICT_PASS,
        "reasons": [],
    }

    img_path = folder / "original.jpg"
    if not img_path.exists():
        result["verdict"] = _VERDICT_FAIL
        result["reasons"].append("original.jpg missing")
        return result

    try:
        img = Image.open(img_path)
        img.load()
    except Exception as exc:
        result["verdict"] = _VERDICT_FAIL
        result["reasons"].append(f"cannot open image: {exc}")
        return result

    # 1. Resolution
    ok, reason = _check_resolution(img)
    if not ok:
        result["verdict"] = _VERDICT_FAIL
        result["reasons"].append(f"resolution: {reason}")
        return result  # no need to continue

    # 2. Colour balance
    ok, reason = _check_color_balance(img)
    if not ok:
        result["verdict"] = _VERDICT_FAIL
        result["reasons"].append(f"colour: {reason}")
        return result

    # 3. Portrait quality via LLM
    if not skip_llm:
        display_name = folder.name.replace("_", " ").title()
        image_bytes = img_path.read_bytes()
        ok, reason = _validate_portrait(image_bytes, display_name, gateway_url)
        if not ok:
            result["verdict"] = _VERDICT_FAIL
            result["reasons"].append(f"portrait: {reason}")
        elif "skipped" in reason:
            result["verdict"] = _VERDICT_REVIEW
            result["reasons"].append(f"llm: {reason}")

    return result


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--dry-run", action="store_true", help="Report without deleting")
    parser.add_argument(
        "--auto-remove",
        action="store_true",
        help="Delete failing folders without confirmation",
    )
    parser.add_argument(
        "--gateway",
        default="http://127.0.0.1:4096",
        help="LLM Gateway URL (default: %(default)s)",
    )
    parser.add_argument("--skip-llm", action="store_true", help="Skip LLM portrait check")
    args = parser.parse_args()

    if args.dry_run and args.auto_remove:
        parser.error("--dry-run and --auto-remove are mutually exclusive")

    folders = sorted(p for p in EXAMPLES_DIR.iterdir() if p.is_dir())
    if not folders:
        logger.error("No example folders found under %s", EXAMPLES_DIR)
        sys.exit(1)

    logger.info("Auditing %d example folder(s)…", len(folders))

    results: list[dict] = []
    for folder in folders:
        r = _audit_folder(folder, args.gateway, args.skip_llm)
        results.append(r)
        if r["verdict"] == _VERDICT_PASS:
            logger.debug("  %-40s  PASS", r["name"])
        else:
            label = "FAIL" if r["verdict"] == _VERDICT_FAIL else "NEEDS-REVIEW"
            logger.info("  %-40s  %-12s  %s", r["name"], label, "; ".join(r["reasons"]))

    total = len(results)
    passes = [r for r in results if r["verdict"] == _VERDICT_PASS]
    reviews = [r for r in results if r["verdict"] == _VERDICT_REVIEW]
    failures = [r for r in results if r["verdict"] == _VERDICT_FAIL]

    print()
    print("=" * 68)
    print(f"  Total checked : {total}")
    print(f"  Pass          : {len(passes)}")
    print(f"  Needs review  : {len(reviews)}  (LLM skipped — inspect manually)")
    print(f"  Fail          : {len(failures)}")
    print(f"  Progress      : {len(passes)} / 1000 quality portraits")
    print("=" * 68)

    if failures:
        print()
        print("FAILURES:")
        for r in failures:
            print(f"  {r['name']:<42}  {'; '.join(r['reasons'])}")

    if reviews:
        print()
        print("NEEDS REVIEW (LLM unavailable):")
        for r in reviews:
            print(f"  {r['name']}")

    if args.dry_run or not failures:
        if not failures:
            print("\nNo failures — nothing to remove.")
        else:
            print(f"\n[dry-run] {len(failures)} folder(s) would be removed.")
        return

    # Remove failing folders
    removed = 0
    for r in failures:
        folder: Path = r["path"]
        if not args.auto_remove:
            answer = input(f"\nRemove {folder.relative_to(ROOT)}? [y/N] ").strip().lower()
            if answer not in ("y", "yes"):
                logger.info("  Skipped %s", r["name"])
                continue
        shutil.rmtree(folder)
        logger.info("  Removed %s", folder.name)
        removed += 1

    print()
    print(f"Removed {removed} folder(s).  Kept {total - removed} examples.")


if __name__ == "__main__":
    main()
