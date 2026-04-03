"""Avatar studio settings loader — single source of truth for SETTINGS dict.

Also contains the full color palette, WCAG utilities, and helper functions.
"""

import hashlib
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
_SETTINGS_FILES = [
    _ROOT / "settings.json",
    _ROOT / "assets" / "persona" / "phenotype_settings.json",
    _ROOT / "assets" / "persona" / "cv_settings.json",
    _ROOT / "assets" / "persona" / "presentation_settings.json",
]


def _load_settings() -> dict:
    """Load and merge avatar studio settings from the four settings files."""
    merged: dict = {}
    for path in _SETTINGS_FILES:
        with open(path) as f:
            data = json.load(f)
        # Strip comment-only keys (prefixed with _ or __)
        merged.update({k: v for k, v in data.items() if not k.startswith("_")})
    # Expose presentation schema under the step_c namespace expected by step_c code.
    if "schema" in merged:
        merged["step_c"] = {"schema": merged.pop("schema")}
    return merged


SETTINGS = _load_settings()

# Palette and WCAG-filtered background palette
PALETTE: list[str] = SETTINGS["palette"]

_WCAG_MIN_CONTRAST: float = SETTINGS["wcag_min_contrast"]
_FRAME_FG_COLOR: str = SETTINGS["frame_fg_color"]


def _relative_luminance(hex_color: str) -> float:
    """WCAG relative luminance of a hex color."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4))

    def linearize(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = linearize(r), linearize(g), linearize(b)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_ratio(hex1: str, hex2: str) -> float:
    """WCAG contrast ratio between two hex colors."""
    l1, l2 = _relative_luminance(hex1), _relative_luminance(hex2)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


# Pre-filter palette for abbreviation avatar backgrounds: only keep colors
# that meet WCAG AA contrast (4.5:1) against white foreground text.
VALID_BG_PALETTE = [c for c in PALETTE if _contrast_ratio(c, _FRAME_FG_COLOR) >= _WCAG_MIN_CONTRAST]


def _color_for_name(name: str) -> str:
    """Deterministic color from name hash."""
    idx = int(hashlib.md5(name.encode()).hexdigest(), 16) % len(PALETTE)
    return PALETTE[idx]


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def _darken_hex(hex_color: str, factor: float = 0.7) -> str:
    """Return a darkened version of *hex_color* by multiplying each channel."""
    r, g, b = _hex_to_rgb(hex_color)
    return "#{:02X}{:02X}{:02X}".format(int(r * factor), int(g * factor), int(b * factor))


def _initials(name: str) -> str:
    parts = name.split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    return name[:2].upper()


def _name_to_filename(name: str) -> str:
    """Convert a name to a filename-safe slug."""
    return name.lower().replace(" ", "-")


def _slug(name: str) -> str:
    return name.lower().replace(" ", "-")
