"""Normalize example persona.yml files to canonical schema with vision LLM validation.

Usage:
    python scripts/normalize_example_personas.py --dry-run          # preview changes
    python scripts/normalize_example_personas.py --write            # apply changes
    python scripts/normalize_example_personas.py --write --gateway http://127.0.0.1:4096
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from difflib import unified_diff
from pathlib import Path

import yaml
from tqdm import tqdm

# ── project root on sys.path ──────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from _example_utils import (  # noqa: E402
    EXAMPLES_DIR,
    REPORTS_DIR,
    append_learning,
    finalize_run_metadata,
    load_all_personas,
    make_run_metadata,
    normalize_persona,
)

from config.gateway import GatewayClient  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

GATEWAY_URL = "http://127.0.0.1:4096"

# JSON schema for the vision validation response
_VALIDATION_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "corrections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "name": {"type": "string"},
                    "style": {"type": "string"},
                    "color": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["category", "name", "style", "color", "note"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["corrections"],
    "additionalProperties": False,
}

_VALIDATION_OUTPUT_CONFIG: dict = {"format": {"type": "json_schema", "schema": _VALIDATION_SCHEMA}}

_VALIDATION_SYSTEM = (
    "You are a visual property verifier for portrait photos. "
    "Given a photo and a list of clothing/accessory descriptions with colors, "
    "verify each item against what you see in the image. "
    "Return corrections in structured JSON."
)


def _build_validation_prompt(clothing: dict, accessories: dict) -> str:
    """Build the user prompt for vision validation."""
    lines = [
        "Examine this photo carefully. For each clothing and accessory item below,",
        "verify the description (style) and color hex match what's visible.",
        "",
        "Return a JSON object with a 'corrections' array. Include ALL items listed below,",
        "even if they need no changes. For each item:",
        '  - "category": "clothing" or "accessories"',
        '  - "name": the item name exactly as listed',
        '  - "style": corrected description of the garment/accessory as visible in the photo',
        '  - "color": the dominant #RRGGBB hex color you observe for this item',
        '  - "note": what you changed and why (empty string if no change needed)',
        "",
    ]

    if clothing:
        lines.append("Clothing:")
        for garment, info in clothing.items():
            style = info.get("style", "") if isinstance(info, dict) else ""
            color = info.get("color", "") if isinstance(info, dict) else str(info)
            lines.append(f'  {garment}: {{style: "{style}", color: "{color}"}}')
        lines.append("")

    if accessories:
        lines.append("Accessories:")
        for name, info in accessories.items():
            style = info.get("style", "") if isinstance(info, dict) else ""
            color = info.get("color", "") if isinstance(info, dict) else str(info)
            lines.append(f'  {name}: {{style: "{style}", color: "{color}"}}')
        lines.append("")

    return "\n".join(lines)


def _parse_validation_response(raw: str) -> list[dict]:
    """Parse the vision LLM response into a list of correction dicts."""
    text = raw.strip()
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence_match:
        text = fence_match.group(1).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Vision validation: JSON parse failed — raw=%r", raw[:200])
        return []

    if isinstance(parsed, dict):
        return parsed.get("corrections", [])
    if isinstance(parsed, list):
        return parsed
    return []


def _apply_vision_corrections(persona: dict, corrections: list[dict]) -> tuple[dict, list[dict]]:
    """Apply vision corrections to a normalized persona. Returns (updated_persona, changes)."""
    appearance = persona.get("appearance", {})
    changes: list[dict] = []

    for correction in corrections:
        if not isinstance(correction, dict):
            continue

        category = correction.get("category", "")
        name = correction.get("name", "")
        new_style = correction.get("style", "")
        new_color = correction.get("color", "")
        note = correction.get("note", "")

        if category not in ("clothing", "accessories") or not name:
            continue

        items = appearance.get(category, {})
        if not isinstance(items, dict) or name not in items:
            continue

        current = items[name]
        if not isinstance(current, dict):
            continue

        old_style = current.get("style", "")
        old_color = current.get("color", "")
        changed = False

        if new_style and new_style != old_style:
            current["style"] = new_style
            changes.append(
                {
                    "field": f"{category}.{name}.style",
                    "action": "added" if not old_style else "corrected",
                    "old": old_style,
                    "new": new_style,
                    "note": note,
                }
            )
            changed = True

        if new_color and re.match(r"^#[0-9A-Fa-f]{6}$", new_color):
            if new_color.upper() != (old_color or "").upper():
                current["color"] = new_color
                changes.append(
                    {
                        "field": f"{category}.{name}.color",
                        "action": "added" if not old_color else "corrected",
                        "old": old_color,
                        "new": new_color,
                        "note": note,
                    }
                )
                changed = True

        if not changed and note:
            changes.append(
                {
                    "field": f"{category}.{name}",
                    "action": "verified",
                    "note": note,
                }
            )

    return persona, changes


def _vision_validate(
    client: GatewayClient, image_path: Path, persona: dict
) -> tuple[dict, list[dict]]:
    """Validate clothing/accessories against original.jpg via vision LLM.

    Returns (updated_persona, vision_changes).
    """
    appearance = persona.get("appearance", {})
    clothing = appearance.get("clothing", {})
    accessories = appearance.get("accessories", {})

    if not clothing and not accessories:
        return persona, []

    with open(image_path, "rb") as f:
        image_bytes = f.read()

    prompt = _build_validation_prompt(clothing, accessories)

    try:
        raw = client.image_inspector(
            image_bytes,
            _VALIDATION_SYSTEM,
            prompt,
            timeout=60,
            output_config=_VALIDATION_OUTPUT_CONFIG,
        )
    except Exception as exc:
        logger.warning("Vision validation failed for %s: %s", image_path.parent.name, exc)
        return persona, []

    corrections = _parse_validation_response(raw)
    return _apply_vision_corrections(persona, corrections)


def _compute_diff(original_yaml: str, normalized_yaml: str, name: str) -> str:
    """Compute unified diff between original and normalized YAML strings."""
    orig_lines = original_yaml.splitlines(keepends=True)
    norm_lines = normalized_yaml.splitlines(keepends=True)
    diff = unified_diff(
        orig_lines,
        norm_lines,
        fromfile=f"{name}/persona.yml",
        tofile=f"{name}/persona.yml (normalized)",
    )
    return "".join(diff)


def _detect_dropped_fields(original: dict, normalized: dict) -> list[dict]:
    """Detect fields that were dropped during normalization."""
    dropped: list[dict] = []
    orig_appearance = original.get("appearance", {})

    for category in ("clothing", "accessories"):
        orig_items = orig_appearance.get(category)
        if not isinstance(orig_items, dict):
            continue
        for item_name, item_val in orig_items.items():
            if not isinstance(item_val, dict):
                continue
            for field in ("material", "pattern", "details", "secondary_color", "color_labels"):
                if field in item_val:
                    dropped.append(
                        {
                            "path": f"{category}.{item_name}.{field}",
                            "value": item_val[field],
                        }
                    )

    # Also handle list-format clothing
    orig_clothing = orig_appearance.get("clothing")
    if isinstance(orig_clothing, list):
        for entry in orig_clothing:
            if not isinstance(entry, dict):
                continue
            item_name = entry.get("item", entry.get("name", ""))
            for field in (
                "secondary_color",
                "details",
                "material",
                "pattern",
                "color_labels",
            ):
                if field in entry:
                    dropped.append(
                        {
                            "path": f"clothing.{item_name}.{field}",
                            "value": entry[field],
                        }
                    )

    return dropped


def run(
    examples_dir: Path,
    gateway_url: str,
    dry_run: bool = True,
) -> None:
    """Run normalization on all example personas."""
    client = GatewayClient(gateway_url)
    metadata = make_run_metadata(
        "normalize_example_personas.py",
        {"dry_run": dry_run, "gateway_url": gateway_url, "examples_dir": str(examples_dir)},
    )

    load_all_personas(examples_dir)  # validate loading works
    # Process all dirs with persona.yml (including those load_all_personas skips)
    all_dirs = sorted(
        d for d in examples_dir.iterdir() if d.is_dir() and (d / "persona.yml").exists()
    )

    stats = {
        "total_processed": 0,
        "modified": 0,
        "skipped_empty": 0,
        "skipped_no_image": 0,
        "skipped_no_change": 0,
        "vision_calls": 0,
    }
    all_changes: list[dict] = []

    for example_dir in tqdm(all_dirs, desc="Normalizing", unit="persona"):
        name = example_dir.name
        persona_path = example_dir / "persona.yml"
        image_path = example_dir / "original.jpg"

        with open(persona_path) as f:
            original = yaml.safe_load(f) or {}

        stats["total_processed"] += 1

        appearance = original.get("appearance")
        if not appearance or (isinstance(appearance, dict) and not appearance):
            stats["skipped_empty"] += 1
            continue

        # Step 1: structural normalization
        normalized = normalize_persona(original)

        # Step 2: vision validation (if image exists)
        vision_changes: list[dict] = []
        if image_path.exists():
            norm_appearance = normalized.get("appearance", {})
            clothing = norm_appearance.get("clothing", {})
            accessories = norm_appearance.get("accessories", {})
            if clothing or accessories:
                stats["vision_calls"] += 1
                normalized, vision_changes = _vision_validate(client, image_path, normalized)
        else:
            stats["skipped_no_image"] += 1
            logger.info("  %s: no original.jpg — structural normalize only", name)

        # Detect dropped fields
        dropped = _detect_dropped_fields(original, normalized)

        # Compare
        original_yaml = yaml.dump(original, default_flow_style=False, sort_keys=False)
        normalized_yaml = yaml.dump(normalized, default_flow_style=False, sort_keys=False)

        if original_yaml == normalized_yaml:
            stats["skipped_no_change"] += 1
            continue

        stats["modified"] += 1

        # Determine structural changes
        structural_changes: list[str] = []
        orig_app = original.get("appearance", {})
        norm_app = normalized.get("appearance", {})
        for field in ("clothing", "accessories", "hair_color", "eye_color"):
            orig_val = orig_app.get(field)
            norm_val = norm_app.get(field)
            if orig_val != norm_val and orig_val is not None:
                orig_type = type(orig_val).__name__
                norm_type = type(norm_val).__name__ if norm_val else "removed"
                structural_changes.append(f"{field} format: {orig_type}->{norm_type}")

        change_entry = {
            "example": name,
            "structural_changes": structural_changes,
            "vision_corrections": vision_changes,
            "fields_dropped": dropped,
        }
        all_changes.append(change_entry)

        if dry_run:
            diff = _compute_diff(original_yaml, normalized_yaml, name)
            if diff:
                print(f"\n{diff}")
            if dropped:
                for d in dropped:
                    print(f"  DROPPED: {d['path']} = {d['value']!r}")
            if vision_changes:
                for vc in vision_changes:
                    action = vc.get("action", "")
                    field = vc.get("field", "")
                    note = vc.get("note", "")
                    print(f"  VISION {action}: {field} — {note}")
        else:
            with open(persona_path, "w") as f:
                yaml.dump(normalized, f, default_flow_style=False, sort_keys=False)
            logger.info("  %s: written (%d changes)", name, len(vision_changes))

    # Summary
    print(f"\n=== Normalization {'Preview' if dry_run else 'Complete'} ===")
    print(f"Total processed: {stats['total_processed']}")
    print(f"Modified:        {stats['modified']}")
    print(f"Skipped (empty): {stats['skipped_empty']}")
    print(f"Skipped (no img):{stats['skipped_no_image']}")
    print(f"No change:       {stats['skipped_no_change']}")
    print(f"Vision calls:    {stats['vision_calls']}")

    # Write report if not dry-run
    if not dry_run:
        metadata = finalize_run_metadata(metadata)
        report = {
            "run_metadata": metadata,
            **stats,
            "changes": all_changes,
        }
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = metadata["run_id"]
        report_path = REPORTS_DIR / f"normalization_{ts}.json"
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        logger.info("Report written: %s", report_path)

        # Append learnings
        append_learning(
            {
                "source": "normalize_example_personas",
                "run_id": metadata["run_id"],
                "type": "metric",
                "category": "normalization",
                "detail": (
                    f"Normalized {stats['modified']}/{stats['total_processed']} personas, "
                    f"{stats['vision_calls']} vision calls"
                ),
                "severity": "low",
            }
        )

        if all_changes:
            total_vision = sum(len(c.get("vision_corrections", [])) for c in all_changes)
            total_dropped = sum(len(c.get("fields_dropped", [])) for c in all_changes)
            if total_vision:
                append_learning(
                    {
                        "source": "normalize_example_personas",
                        "run_id": metadata["run_id"],
                        "type": "finding",
                        "category": "data_quality",
                        "detail": f"Vision LLM made {total_vision} corrections across {len(all_changes)} personas",
                        "severity": "medium",
                    }
                )
            if total_dropped:
                append_learning(
                    {
                        "source": "normalize_example_personas",
                        "run_id": metadata["run_id"],
                        "type": "finding",
                        "category": "schema",
                        "detail": f"Dropped {total_dropped} non-canonical fields (material, pattern, etc.)",
                        "severity": "low",
                    }
                )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Normalize example persona.yml files")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true", default=True, help="Preview changes")
    group.add_argument("--write", action="store_true", help="Apply changes")
    parser.add_argument("--examples-dir", type=Path, default=EXAMPLES_DIR)
    parser.add_argument("--gateway", default=GATEWAY_URL)
    args = parser.parse_args()

    if args.write:
        args.dry_run = False

    run(
        examples_dir=args.examples_dir,
        gateway_url=args.gateway,
        dry_run=args.dry_run,
    )
