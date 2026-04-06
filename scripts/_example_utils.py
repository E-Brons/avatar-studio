"""Shared utilities for loading, normalizing, and documenting example personas.

Used by:
    - normalize_example_personas.py
    - audit_example_coverage.py
    - example_benchmark.py
    - analyze_benchmark.py
"""

from __future__ import annotations

import copy
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT / "reports"
LEARNINGS_FILE = REPORTS_DIR / "learnings.jsonl"
EXAMPLES_DIR = ROOT / "assets" / "examples"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_all_personas(
    examples_dir: Path | None = None,
) -> list[tuple[str, dict]]:
    """Return sorted list of (folder_name, persona_dict) for dirs with persona.yml.

    Skips dirs where appearance is empty or missing.
    """
    examples_dir = examples_dir or EXAMPLES_DIR
    results: list[tuple[str, dict]] = []
    for d in sorted(examples_dir.iterdir()):
        if not d.is_dir():
            continue
        persona_path = d / "persona.yml"
        if not persona_path.exists():
            continue
        with open(persona_path) as f:
            persona = yaml.safe_load(f) or {}
        appearance = persona.get("appearance")
        if not appearance or (isinstance(appearance, dict) and not appearance):
            continue
        results.append((d.name, persona))
    return results


# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------


def _darken_hex(hex_color: str, factor: float = 0.5) -> str:
    """Darken a hex color by shifting RGB channels toward 0."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return hex_color
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return hex_color
    r = int(r * factor)
    g = int(g * factor)
    b = int(b * factor)
    return f"#{r:02X}{g:02X}{b:02X}"


def _extract_first_hex(value: str | list | dict) -> str:
    """Extract the first #RRGGBB hex from a string, list, or dict value."""
    if isinstance(value, str):
        m = re.search(r"#[0-9A-Fa-f]{6}", value)
        return m.group() if m else ""
    if isinstance(value, list):
        for item in value:
            h = _extract_first_hex(item)
            if h:
                return h
    if isinstance(value, dict):
        for v in value.values():
            h = _extract_first_hex(v)
            if h:
                return h
    return ""


# ---------------------------------------------------------------------------
# Normalization — clothing
# ---------------------------------------------------------------------------


def normalize_clothing(raw: object) -> dict[str, dict]:
    """Normalize clothing to canonical {garment: {style: str, color: str}}.

    Handles:
    1. Already canonical {garment: {style:..., color:...}}
    2. Flat hex {garment: "#hex"}
    3. Nested dict with extras {garment: {style:..., color:..., material:..., ...}}
    4. List of items [{item:..., primary_color:..., description:...}]
    """
    if not raw:
        return {}

    # Format 4: list of items
    if isinstance(raw, list):
        result: dict[str, dict] = {}
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("item", entry.get("name", "garment")))
            desc = str(entry.get("description", entry.get("style", "")))
            color = str(entry.get("primary_color", entry.get("color", "")))
            if not color:
                color = _extract_first_hex(entry)
            result[name] = {"style": desc, "color": color}
        return result

    if isinstance(raw, str):
        # Plain string — unlikely but handle
        hex_val = _extract_first_hex(raw)
        if hex_val:
            return {"garment": {"style": "", "color": hex_val}}
        return {}

    if not isinstance(raw, dict):
        return {}

    result = {}
    for garment, value in raw.items():
        if isinstance(value, str):
            # Format 2: flat hex like {sweater: '#808080'}
            hex_val = _extract_first_hex(value)
            result[garment] = {"style": "", "color": hex_val or value}
        elif isinstance(value, dict):
            # Check if already canonical
            if set(value.keys()) == {"style", "color"} and isinstance(value.get("style"), str):
                result[garment] = {"style": value["style"], "color": str(value["color"])}
            else:
                # Format 3: nested with extras — extract style + color
                style = str(value.get("style", value.get("type", value.get("description", ""))))
                color = str(value.get("color", ""))
                if not color:
                    # Try colors list
                    colors = value.get("colors", [])
                    if colors and isinstance(colors, list):
                        color = _extract_first_hex(colors)
                    if not color:
                        color = _extract_first_hex(value)
                result[garment] = {"style": style, "color": color}
        else:
            continue
    return result


# ---------------------------------------------------------------------------
# Normalization — accessories
# ---------------------------------------------------------------------------


def normalize_accessories(raw: object) -> dict[str, dict]:
    """Normalize accessories to canonical {name: {style: str, color: str}}.

    Handles:
    1. Already canonical {name: {style:..., color:...}}
    2. Flat string {name: "description"}
    3. Nested dict {name: {type:..., material:..., color:...}}
    """
    if not raw:
        return {}
    if isinstance(raw, str):
        if raw.lower() in ("none", ""):
            return {}
        return {}
    if not isinstance(raw, dict):
        return {}

    result: dict[str, dict] = {}
    for name, value in raw.items():
        if isinstance(value, str):
            if value.lower() in ("none", ""):
                continue
            # Format 2: flat string description
            result[name] = {"style": value}
        elif isinstance(value, dict):
            # Check if already canonical
            if "style" in value and isinstance(value["style"], str):
                entry: dict[str, str] = {"style": value["style"]}
                if "color" in value:
                    entry["color"] = str(value["color"])
                result[name] = entry
            else:
                # Format 3: nested with type/material/color
                style = str(value.get("type", value.get("description", "")))
                entry = {"style": style}
                color = str(value.get("color", ""))
                if color:
                    entry["color"] = color
                result[name] = entry
    return result


# ---------------------------------------------------------------------------
# Normalization — colors
# ---------------------------------------------------------------------------


def normalize_hair_color(raw: object) -> dict[str, str] | None:
    """Normalize hair_color to {hex_base, hex_shadow}."""
    if not raw:
        return None
    if isinstance(raw, dict):
        if "hex_base" in raw:
            return {"hex_base": str(raw["hex_base"]), "hex_shadow": str(raw.get("hex_shadow", ""))}
        # Unknown dict format — try to extract hex
        hex_val = _extract_first_hex(raw)
        if hex_val:
            return {"hex_base": hex_val, "hex_shadow": _darken_hex(hex_val)}
        return None
    if isinstance(raw, str):
        hex_val = _extract_first_hex(raw)
        if hex_val:
            return {"hex_base": hex_val, "hex_shadow": _darken_hex(hex_val)}
    return None


def normalize_eye_color(raw: object) -> dict[str, str] | None:
    """Normalize eye_color to {hex_iris, hex_pupil}."""
    if not raw:
        return None
    if isinstance(raw, dict):
        if "hex_iris" in raw:
            return {"hex_iris": str(raw["hex_iris"]), "hex_pupil": str(raw.get("hex_pupil", ""))}
        hex_val = _extract_first_hex(raw)
        if hex_val:
            return {"hex_iris": hex_val, "hex_pupil": _darken_hex(hex_val)}
        return None
    if isinstance(raw, str):
        hex_val = _extract_first_hex(raw)
        if hex_val:
            return {"hex_iris": hex_val, "hex_pupil": _darken_hex(hex_val)}
    return None


# ---------------------------------------------------------------------------
# Full persona normalization
# ---------------------------------------------------------------------------


def normalize_persona(persona: dict) -> dict:
    """Normalize a persona dict to canonical schema. Returns a deep copy."""
    p = copy.deepcopy(persona)
    appearance = p.get("appearance")
    if not appearance or not isinstance(appearance, dict):
        return p

    # Clothing
    clothing = appearance.get("clothing")
    if clothing is not None:
        normalized = normalize_clothing(clothing)
        if normalized:
            appearance["clothing"] = normalized
        else:
            del appearance["clothing"]

    # Accessories
    accessories = appearance.get("accessories")
    if accessories is not None:
        normalized_acc = normalize_accessories(accessories)
        if normalized_acc:
            appearance["accessories"] = normalized_acc
        else:
            del appearance["accessories"]

    # Hair color
    hair_color = appearance.get("hair_color")
    if hair_color is not None:
        normalized_hc = normalize_hair_color(hair_color)
        if normalized_hc:
            appearance["hair_color"] = normalized_hc
        else:
            del appearance["hair_color"]

    # Eye color
    eye_color = appearance.get("eye_color")
    if eye_color is not None:
        normalized_ec = normalize_eye_color(eye_color)
        if normalized_ec:
            appearance["eye_color"] = normalized_ec
        else:
            del appearance["eye_color"]

    return p


# ---------------------------------------------------------------------------
# Run metadata + learnings
# ---------------------------------------------------------------------------


def _git_sha() -> str:
    """Return short git SHA of HEAD, or 'unknown'."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=ROOT,
            timeout=5,
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def make_run_metadata(script_name: str, parameters: dict) -> dict:
    """Create run metadata dict for embedding in output files."""
    return {
        "run_id": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "started_at": datetime.now().isoformat(),
        "parameters": parameters,
        "versions": {
            "script": script_name,
            "git_sha": _git_sha(),
        },
    }


def finalize_run_metadata(metadata: dict) -> dict:
    """Add finished_at and duration_s to run metadata."""
    metadata = copy.copy(metadata)
    metadata["finished_at"] = datetime.now().isoformat()
    started = datetime.fromisoformat(metadata["started_at"])
    metadata["duration_s"] = round((datetime.now() - started).total_seconds(), 1)
    return metadata


def append_learning(entry: dict) -> None:
    """Append a structured learning entry to reports/learnings.jsonl."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    entry = copy.copy(entry)
    if "timestamp" not in entry:
        entry["timestamp"] = datetime.now().isoformat()
    with open(LEARNINGS_FILE, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# YCbCr color distance (copied from classify_persona.py — pure math)
# ---------------------------------------------------------------------------

_MAX_YCBCR_DISTANCE: float = 325.0


def hex_to_rgb(hex_color: str) -> tuple[int, int, int] | None:
    """Convert #RRGGBB to (R, G, B) or None."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return None
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return None


def rgb_to_ycbcr(r: int, g: int, b: int) -> tuple[float, float, float]:
    """Convert RGB to YCbCr."""
    y = 0.299 * r + 0.587 * g + 0.114 * b
    cb = 128 - 0.168736 * r - 0.331264 * g + 0.5 * b
    cr = 128 + 0.5 * r - 0.418688 * g - 0.081312 * b
    return y, cb, cr


def ycbcr_distance(hex1: str, hex2: str) -> float:
    """Euclidean distance in YCbCr space between two hex colors."""
    rgb1 = hex_to_rgb(hex1)
    rgb2 = hex_to_rgb(hex2)
    if rgb1 is None or rgb2 is None:
        return float("inf")
    ycc1 = rgb_to_ycbcr(*rgb1)
    ycc2 = rgb_to_ycbcr(*rgb2)
    return sum((a - b) ** 2 for a, b in zip(ycc1, ycc2)) ** 0.5


def color_proximity(hex1: str, hex2: str) -> float:
    """Normalized proximity [0,1] — 1.0 = identical, 0.0 = maximally different."""
    dist = ycbcr_distance(hex1, hex2)
    return max(0.0, 1.0 - dist / _MAX_YCBCR_DISTANCE)
