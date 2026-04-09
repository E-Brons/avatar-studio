#! .venv/bin/python3
"""Audit example portraits and persona attribute coverage.

Two audit modes (pass at least one):
  --audit-quality   Check original.jpg files for resolution, colour, and portrait quality.
                    Optionally remove failing folders.
  --audit-variety   Check persona.yml appearance attributes against pipeline pools.
                    Reports coverage gaps and unused pool entries.

Quality checks (in order):
  1. Resolution  — hard fail if either dimension < 512 px
  2. Colour balance — grayscale (mean HSV saturation < 0.08) or sepia/brown
                      (R−B channel mean > 60 AND saturation < 0.20)
  3. Portrait quality — calls the LLM gateway when available

Usage:
    python scripts/examples/audit_examples.py --audit-quality [--dry-run] [--auto-remove] [--skip-llm]
    python scripts/examples/audit_examples.py --audit-variety [--output PATH]
    python scripts/examples/audit_examples.py --audit-quality --audit-variety
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from config.gateway import GatewayClient

    _GATEWAY_AVAILABLE = True
except ImportError:
    _GATEWAY_AVAILABLE = False

from _cv_scoring import color_balance_check, compute_quality_score  # noqa: E402
from _example_utils import (  # noqa: E402
    EXAMPLES_DIR,
    REPORTS_DIR,
    append_learning,
    color_proximity,
    finalize_run_metadata,
    find_best_image,
    load_all_personas,
    make_run_metadata,
    normalize_persona,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# ── Quality audit constants ───────────────────────────────────────────────────

_MIN_DIM = 512
_GRAYSCALE_SAT_THRESHOLD = 0.08
_SEPIA_SAT_THRESHOLD = 0.20
_SEPIA_RB_DIFF = 60

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

_VERDICT_PASS = "pass"
_VERDICT_FAIL = "fail"
_VERDICT_REVIEW = "needs-review"

# ── Variety audit constants ───────────────────────────────────────────────────

PHENOTYPE_PATH = ROOT / "assets" / "persona" / "phenotype_settings.json"
PRESENTATION_PATH = ROOT / "assets" / "persona" / "presentation_settings.json"

COLOR_MATCH_THRESHOLD = 0.85
TEXT_MATCH_THRESHOLD = 0.5

# ── Quality audit ─────────────────────────────────────────────────────────────


def _validate_portrait(
    image_bytes: bytes,
    name: str,
    gateway_url: str,
    timeout: int = 30,
) -> tuple[bool, str]:
    """Ask the vision LLM whether a portrait meets quality requirements."""
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
    except json.JSONDecodeError, AttributeError:
        return True, "validation skipped (parse error)"


def _check_resolution(img: Image.Image) -> tuple[bool, str]:
    w, h = img.size
    if w < _MIN_DIM or h < _MIN_DIM:
        return False, f"too small ({w}×{h}, minimum {_MIN_DIM}px per side)"
    return True, ""


def _check_color_balance(img: Image.Image) -> tuple[bool, str]:
    """Thin wrapper around _cv_scoring.color_balance_check (canonical implementation)."""
    import io

    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return color_balance_check(buf.getvalue())


def _audit_folder(folder: Path, gateway_url: str, skip_llm: bool) -> dict:
    result: dict = {
        "name": folder.name,
        "path": folder,
        "verdict": _VERDICT_PASS,
        "reasons": [],
        "has_multi_images": (folder / "images").exists(),
    }

    img_path = find_best_image(folder)
    if img_path is None:
        result["verdict"] = _VERDICT_FAIL
        result["reasons"].append(
            "no image found (checked images/best.jpg, images/001.jpg, original.jpg)"
        )
        return result

    try:
        img = Image.open(img_path)
        img.load()
    except Exception as exc:
        result["verdict"] = _VERDICT_FAIL
        result["reasons"].append(f"cannot open image: {exc}")
        return result

    ok, reason = _check_resolution(img)
    if not ok:
        result["verdict"] = _VERDICT_FAIL
        result["reasons"].append(f"resolution: {reason}")
        return result

    ok, reason = _check_color_balance(img)
    if not ok:
        result["verdict"] = _VERDICT_FAIL
        result["reasons"].append(f"colour: {reason}")
        return result

    # Add CV quality metrics (non-blocking — informational only)
    try:
        image_bytes = img_path.read_bytes()
        cv_quality = compute_quality_score(image_bytes)
        result["cv_quality"] = {
            "composite_score": cv_quality["composite_score"],
            "has_face": cv_quality["has_face"],
            "blur_score": cv_quality["blur_score"],
            "resolution_score": cv_quality["resolution_score"],
        }
    except Exception:
        pass

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


def run_quality_audit(
    *,
    gateway: str = "http://127.0.0.1:4096",
    skip_llm: bool = False,
    dry_run: bool = False,
    auto_remove: bool = False,
    examples_dir: Path | None = None,
) -> dict:
    """Audit original.jpg quality for all example folders.

    Returns {"total": N, "pass": N, "review": N, "fail": N, "removed": N}.
    """
    examples_dir = examples_dir or EXAMPLES_DIR
    folders = sorted(p for p in examples_dir.iterdir() if p.is_dir())
    if not folders:
        logger.error("No example folders found under %s", examples_dir)
        return {"total": 0, "pass": 0, "review": 0, "fail": 0, "removed": 0}

    logger.info("Auditing %d example folder(s)…", len(folders))

    results_list: list[dict] = []
    for folder in folders:
        r = _audit_folder(folder, gateway, skip_llm)
        results_list.append(r)
        if r["verdict"] == _VERDICT_PASS:
            logger.debug("  %-40s  PASS", r["name"])
        else:
            label = "FAIL" if r["verdict"] == _VERDICT_FAIL else "NEEDS-REVIEW"
            logger.info("  %-40s  %-12s  %s", r["name"], label, "; ".join(r["reasons"]))

    total = len(results_list)
    passes = [r for r in results_list if r["verdict"] == _VERDICT_PASS]
    reviews = [r for r in results_list if r["verdict"] == _VERDICT_REVIEW]
    failures = [r for r in results_list if r["verdict"] == _VERDICT_FAIL]

    multi_image_count = sum(1 for r in results_list if r.get("has_multi_images"))
    legacy_only_count = total - multi_image_count

    print()
    print("=" * 68)
    print(f"  Total checked : {total}")
    print(f"  Pass          : {len(passes)}")
    print(f"  Needs review  : {len(reviews)}  (LLM skipped — inspect manually)")
    print(f"  Fail          : {len(failures)}")
    print(f"  Progress      : {len(passes)} / 1000 quality portraits")
    print(f"  Multi-image   : {multi_image_count} / {total} migrated")
    print(f"  Legacy only   : {legacy_only_count} folders (single original.jpg)")
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

    if dry_run or not failures:
        if not failures:
            print("\nNo failures — nothing to remove.")
        else:
            print(f"\n[dry-run] {len(failures)} folder(s) would be removed.")
        return {
            "total": total,
            "pass": len(passes),
            "review": len(reviews),
            "fail": len(failures),
            "removed": 0,
        }

    removed = 0
    for r in failures:
        folder: Path = r["path"]
        if not auto_remove:
            answer = input(f"\nRemove {folder.relative_to(ROOT)}? [y/N] ").strip().lower()
            if answer not in ("y", "yes"):
                logger.info("  Skipped %s", r["name"])
                continue
        shutil.rmtree(folder)
        logger.info("  Removed %s", folder.name)
        removed += 1

    print()
    print(f"Removed {removed} folder(s).  Kept {total - removed} examples.")
    return {
        "total": total,
        "pass": len(passes),
        "review": len(reviews),
        "fail": len(failures),
        "removed": removed,
    }


# ── Variety audit ─────────────────────────────────────────────────────────────


def _load_pools() -> dict:
    with open(PHENOTYPE_PATH) as f:
        phenotype = json.load(f)
    with open(PRESENTATION_PATH) as f:
        presentation = json.load(f)
    return {"phenotype": phenotype, "presentation": presentation}


def _parse_pool_hex_pairs(pool_list: list[str]) -> list[str]:
    result = []
    for entry in pool_list:
        hexes = re.findall(r"#[0-9A-Fa-f]{6}", entry)
        if hexes:
            result.append(hexes[0])
    return result


def _get_gendered_pool(pool_dict: dict, gender: str) -> list[str]:
    entries = list(pool_dict.get(gender, []))
    if gender != "neutral":
        entries.extend(pool_dict.get("neutral", []))
    return entries


def _tokenize(text: str) -> set[str]:
    return set(re.split(r"[\s\-]+", text.lower().strip())) - {""}


def _text_overlap(example_val: str, pool_val: str) -> float:
    ex_tokens = _tokenize(example_val)
    pool_tokens = _tokenize(pool_val)
    if not ex_tokens:
        return 0.0
    return len(ex_tokens & pool_tokens) / len(ex_tokens)


def _best_color_match(hex_val: str, pool_hexes: list[str]) -> tuple[str, float]:
    best_match = ""
    best_prox = 0.0
    for pool_hex in pool_hexes:
        prox = color_proximity(hex_val, pool_hex)
        if prox > best_prox:
            best_prox = prox
            best_match = pool_hex
    return best_match, best_prox


def _best_text_match(value: str, pool_values: list[str]) -> tuple[str, float]:
    best_match = ""
    best_overlap = 0.0
    for pool_val in pool_values:
        overlap = _text_overlap(value, pool_val)
        if overlap > best_overlap:
            best_overlap = overlap
            best_match = pool_val
    return best_match, best_overlap


def _audit_color_attribute(
    examples: list[tuple[str, dict]],
    attr_key: str,
    pool_hexes: list[str],
    extract_hex: callable,
) -> dict:
    matched = []
    unmatched = []
    used_pool: set[str] = set()

    for name, persona in examples:
        appearance = persona.get("appearance", {})
        hex_val = extract_hex(appearance.get(attr_key))
        if not hex_val:
            continue

        best_match, prox = _best_color_match(hex_val, pool_hexes)
        entry = {
            "example": name,
            "value": hex_val,
            "best_pool_match": best_match,
            "proximity": round(prox, 3),
        }

        if prox >= COLOR_MATCH_THRESHOLD:
            matched.append(entry)
            used_pool.add(best_match)
        else:
            unmatched.append(entry)

    total = len(matched) + len(unmatched)
    unused = [h for h in pool_hexes if h not in used_pool]

    return {
        "coverage_pct": round(len(matched) / total, 3) if total else 0.0,
        "total_with_value": total,
        "matched_count": len(matched),
        "unmatched_count": len(unmatched),
        "matched": matched,
        "unmatched": sorted(unmatched, key=lambda x: x["proximity"]),
        "unused_pool": unused,
        "unused_pool_count": len(unused),
    }


def _audit_text_attribute(
    examples: list[tuple[str, dict]],
    attr_key: str,
    pool_values: list[str],
    get_pool_for_gender: callable | None = None,
) -> dict:
    matched = []
    unmatched = []
    used_pool: set[str] = set()

    for name, persona in examples:
        appearance = persona.get("appearance", {})
        value = appearance.get(attr_key, "")
        if not value or not isinstance(value, str):
            continue

        if get_pool_for_gender:
            gender = persona.get("personal", {}).get("gender", "neutral")
            pool = get_pool_for_gender(gender)
        else:
            pool = pool_values

        best_match, overlap = _best_text_match(value, pool)
        entry = {
            "example": name,
            "value": value,
            "best_pool_match": best_match,
            "overlap": round(overlap, 3),
        }

        if overlap >= TEXT_MATCH_THRESHOLD:
            matched.append(entry)
            used_pool.add(best_match)
        else:
            unmatched.append(entry)

    total = len(matched) + len(unmatched)
    unused = [v for v in pool_values if v not in used_pool]

    return {
        "coverage_pct": round(len(matched) / total, 3) if total else 0.0,
        "total_with_value": total,
        "matched_count": len(matched),
        "unmatched_count": len(unmatched),
        "matched": matched,
        "unmatched": sorted(unmatched, key=lambda x: x["overlap"]),
        "unused_pool": unused,
        "unused_pool_count": len(unused),
    }


def _extract_skin_hex(val: object) -> str:
    if isinstance(val, str):
        m = re.match(r"^#[0-9A-Fa-f]{6}$", val)
        return val if m else ""
    return ""


def _extract_hair_hex(val: object) -> str:
    if isinstance(val, dict):
        return str(val.get("hex_base", ""))
    if isinstance(val, str):
        m = re.match(r"^#[0-9A-Fa-f]{6}$", val)
        return val if m else ""
    return ""


def _extract_eye_hex(val: object) -> str:
    if isinstance(val, dict):
        return str(val.get("hex_iris", ""))
    if isinstance(val, str):
        m = re.match(r"^#[0-9A-Fa-f]{6}$", val)
        return val if m else ""
    return ""


def run_variety_audit(
    *,
    output_path: Path | None = None,
    examples_dir: Path | None = None,
) -> dict:
    """Audit persona appearance attribute coverage against pipeline pools.

    Returns the report dict. Also writes JSON to output_path if given.
    """
    examples_dir = examples_dir or EXAMPLES_DIR
    output_path = output_path or REPORTS_DIR / "coverage_audit.json"

    metadata = make_run_metadata(
        "audit_examples.py",
        {"examples_dir": str(examples_dir), "output": str(output_path)},
    )

    raw_examples = load_all_personas(examples_dir)
    examples = [(name, normalize_persona(persona)) for name, persona in raw_examples]

    all_dirs = [
        d for d in sorted(examples_dir.iterdir()) if d.is_dir() and (d / "persona.yml").exists()
    ]
    skipped_empty = len(all_dirs) - len(examples)

    pools = _load_pools()
    phenotype = pools["phenotype"]
    presentation = pools["presentation"]

    skin_pool = phenotype.get("skin_tones", [])
    hair_color_pool = _parse_pool_hex_pairs(phenotype.get("hair_colors", []))
    eye_color_pool = _parse_pool_hex_pairs(phenotype.get("eye_colors", []))

    attributes: dict[str, dict] = {}

    attributes["skin_tone"] = _audit_color_attribute(
        examples, "skin_tone", skin_pool, _extract_skin_hex
    )
    attributes["hair_color"] = _audit_color_attribute(
        examples, "hair_color", hair_color_pool, _extract_hair_hex
    )
    attributes["eye_color"] = _audit_color_attribute(
        examples, "eye_color", eye_color_pool, _extract_eye_hex
    )

    attributes["eye_shape"] = _audit_text_attribute(
        examples, "eye_shape", phenotype.get("eye_shapes", [])
    )
    attributes["nose_shape"] = _audit_text_attribute(
        examples, "nose_shape", phenotype.get("nose_shapes", [])
    )

    brows_pool = phenotype.get("brows_styles", {})
    all_brows = []
    for v in brows_pool.values():
        all_brows.extend(v)
    attributes["brows_style"] = _audit_text_attribute(
        examples,
        "brows_style",
        all_brows,
        get_pool_for_gender=lambda g: _get_gendered_pool(brows_pool, g),
    )

    chin_pool = phenotype.get("chin_shapes", {})
    all_chins = []
    for v in chin_pool.values():
        all_chins.extend(v)
    attributes["chin_shape"] = _audit_text_attribute(
        examples,
        "chin_shape",
        all_chins,
        get_pool_for_gender=lambda g: _get_gendered_pool(chin_pool, g),
    )

    cheeks_pool = phenotype.get("cheeks_shapes", {})
    all_cheeks = []
    for v in cheeks_pool.values():
        all_cheeks.extend(v)
    attributes["cheeks_shape"] = _audit_text_attribute(
        examples,
        "cheeks_shape",
        all_cheeks,
        get_pool_for_gender=lambda g: _get_gendered_pool(cheeks_pool, g),
    )

    hair_style_pool = presentation.get("hair_styles", {})
    all_hair_styles = []
    for v in hair_style_pool.values():
        all_hair_styles.extend(v)
    attributes["hair_style"] = _audit_text_attribute(
        examples,
        "hair_style",
        all_hair_styles,
        get_pool_for_gender=lambda g: _get_gendered_pool(hair_style_pool, g),
    )

    best_attr = max(attributes.items(), key=lambda x: x[1]["coverage_pct"])
    worst_attr = min(
        ((k, v) for k, v in attributes.items() if v["total_with_value"] > 0),
        key=lambda x: x[1]["coverage_pct"],
    )
    total_gaps = sum(a["unmatched_count"] for a in attributes.values())
    total_unused = sum(a["unused_pool_count"] for a in attributes.values())

    summary = {
        "best_covered": f"{best_attr[0]} ({best_attr[1]['coverage_pct']:.0%})",
        "worst_covered": f"{worst_attr[0]} ({worst_attr[1]['coverage_pct']:.0%})",
        "total_pool_gaps": total_gaps,
        "total_unused_pool_entries": total_unused,
    }

    metadata = finalize_run_metadata(metadata)
    report = {
        "run_metadata": metadata,
        "total_examples": len(examples),
        "skipped_empty": skipped_empty,
        "attributes": attributes,
        "summary": summary,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    logger.info("Report written: %s", output_path)

    print("\n=== Pool Coverage Audit ===")
    for attr_name, attr_data in attributes.items():
        total = attr_data["total_with_value"]
        matched = attr_data["matched_count"]
        unused = attr_data["unused_pool_count"]
        pct = attr_data["coverage_pct"]
        print(
            f"  {attr_name:15s} {pct:5.0%} covered ({matched:3d}/{total:3d}) — {unused} unused pool entries"
        )

    print(f"\n  Best covered:  {summary['best_covered']}")
    print(f"  Worst covered: {summary['worst_covered']}")
    print(f"  Total gaps:    {total_gaps}")
    print(f"  Unused pool:   {total_unused}")

    all_unmatched = []
    for attr_name, attr_data in attributes.items():
        for entry in attr_data["unmatched"]:
            all_unmatched.append({**entry, "attribute": attr_name})

    if all_unmatched:
        all_unmatched.sort(key=lambda x: x.get("proximity", x.get("overlap", 0)))
        print("\n  Top unmatched gaps:")
        for entry in all_unmatched[:10]:
            attr = entry["attribute"]
            name = entry["example"]
            val = entry["value"]
            best = entry["best_pool_match"]
            score = entry.get("proximity", entry.get("overlap", 0))
            score_label = "proximity" if "proximity" in entry else "overlap"
            print(f"    {attr} {val!r} ({name}) — closest: {best!r} @ {score:.0%} {score_label}")

    for attr_name, attr_data in attributes.items():
        append_learning(
            {
                "source": "audit_examples",
                "run_id": metadata["run_id"],
                "type": "metric",
                "category": "coverage",
                "detail": f"{attr_name} coverage: {attr_data['coverage_pct']:.0%} "
                f"({attr_data['matched_count']}/{attr_data['total_with_value']})",
                "severity": "low",
            }
        )
        for entry in attr_data["unmatched"]:
            score = entry.get("proximity", entry.get("overlap", 0))
            if score < 0.70:
                append_learning(
                    {
                        "source": "audit_examples",
                        "run_id": metadata["run_id"],
                        "type": "finding",
                        "category": "pool_gap",
                        "detail": f"{attr_name} {entry['value']!r} ({entry['example']}) "
                        f"has no close pool match (best: {entry['best_pool_match']!r} @ {score:.0%})",
                        "action": f"Consider adding {entry['value']!r} to {attr_name} pool",
                        "severity": "medium",
                        "affected_examples": [entry["example"]],
                    }
                )

    if total_unused > 0:
        append_learning(
            {
                "source": "audit_examples",
                "run_id": metadata["run_id"],
                "type": "finding",
                "category": "pool_bloat",
                "detail": f"{total_unused} pool entries not matched by any example",
                "severity": "low",
            }
        )

    return report


# ── CLI ───────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    mode = parser.add_argument_group("audit mode (at least one required)")
    mode.add_argument("--audit-quality", action="store_true", help="Run portrait quality audit")
    mode.add_argument("--audit-variety", action="store_true", help="Run persona coverage audit")

    quality = parser.add_argument_group("quality audit options")
    quality.add_argument("--dry-run", action="store_true", help="Report without deleting")
    quality.add_argument(
        "--auto-remove",
        action="store_true",
        help="Delete failing folders without confirmation",
    )
    quality.add_argument(
        "--gateway",
        default="http://127.0.0.1:4096",
        help="LLM Gateway URL (default: %(default)s)",
    )
    quality.add_argument("--skip-llm", action="store_true", help="Skip LLM portrait check")

    variety = parser.add_argument_group("variety audit options")
    variety.add_argument(
        "--output",
        type=Path,
        default=REPORTS_DIR / "coverage_audit.json",
        help="Coverage report output path (default: %(default)s)",
    )

    args = parser.parse_args()

    if not args.audit_quality and not args.audit_variety:
        parser.error("Specify at least one of --audit-quality or --audit-variety")

    if args.audit_quality and args.dry_run and args.auto_remove:
        parser.error("--dry-run and --auto-remove are mutually exclusive")

    if args.audit_quality:
        run_quality_audit(
            gateway=args.gateway,
            skip_llm=args.skip_llm,
            dry_run=args.dry_run,
            auto_remove=args.auto_remove,
        )

    if args.audit_variety:
        run_variety_audit(output_path=args.output)


if __name__ == "__main__":
    main()
