"""Standalone LLM-based categorizer for avatar visual property verification.

Can be imported by any integration or unit test.  The only requirement is a
running LLM Gateway server with a vision-capable model.

Usage
-----
    from tuning.classify_persona import categorize_avatar_image, CategoryReport

    report = categorize_avatar_image(
        image_bytes,
        persona,
        gateway_url="http://127.0.0.1:4096",
    )
    print(f"score={report.score:.0%}")   # e.g. "score=87%"
    print(report.failures())             # list of unmatched properties
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import yaml

from config.config import SETTINGS
from config.gateway import GatewayClient

logger = logging.getLogger(__name__)

_DEFAULT_VISUAL_DESC_MODEL: str = SETTINGS["default_visual_desc_model"]

# ---------------------------------------------------------------------------
# Color properties — pass/fail is determined by YCbCr distance, not LLM binary
# ---------------------------------------------------------------------------

_COLOR_PROPERTIES: frozenset[str] = frozenset({"skin_tone", "hair_color", "eye_color", "clothing"})

# Maximum Euclidean distance in YCbCr space to consider a color "matching".
# ≈55 permits shade/lighting variation typical of diffusion models while
# still catching genuinely wrong color families (e.g. dark brown vs blue).
_YCBCR_THRESHOLD: float = 55.0


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int] | None:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return None
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return None


def _rgb_to_ycbcr(r: int, g: int, b: int) -> tuple[float, float, float]:
    y = 0.299 * r + 0.587 * g + 0.114 * b
    cb = 128 - 0.168736 * r - 0.331264 * g + 0.5 * b
    cr = 128 + 0.5 * r - 0.418688 * g - 0.081312 * b
    return y, cb, cr


def _ycbcr_distance(hex1: str, hex2: str) -> float:
    """Euclidean distance in YCbCr space between two hex colors."""
    rgb1 = _hex_to_rgb(hex1)
    rgb2 = _hex_to_rgb(hex2)
    if rgb1 is None or rgb2 is None:
        return float("inf")
    ycc1 = _rgb_to_ycbcr(*rgb1)
    ycc2 = _rgb_to_ycbcr(*rgb2)
    return sum((a - b) ** 2 for a, b in zip(ycc1, ycc2)) ** 0.5


def _within_color_tolerance(observed_hex: str, expected_desc: str) -> bool | None:
    """Return True/False if observed_hex is within YCbCr threshold of any hex in
    expected_desc, or None when expected_desc contains no hex values."""
    expected_hexes = re.findall(r"#[0-9A-Fa-f]{6}", expected_desc)
    if not expected_hexes:
        return None
    min_dist = min(_ycbcr_distance(observed_hex, h) for h in expected_hexes)
    logger.debug(
        "_within_color_tolerance: observed=%s expected=%s min_dist=%.1f threshold=%.1f",
        observed_hex,
        expected_hexes,
        min_dist,
        _YCBCR_THRESHOLD,
    )
    return min_dist <= _YCBCR_THRESHOLD


# ---------------------------------------------------------------------------
# Color → human-readable label tables (with hex preserved in description)
# ---------------------------------------------------------------------------

_SKIN_TONE_LABELS: dict[str, str] = {
    "#F5E0C9": "warm ivory — very fair",
    "#FBCCB3": "light peach — fair",
    "#E8C49A": "golden beige — light",
    "#D4A76A": "honey tan — medium",
    "#C9A96E": "warm olive — medium",
    "#A67C52": "light brown — medium-dark",
    "#8B5E3C": "medium brown — dark",
    "#6B3F23": "deep brown — very dark",
    "#4A2912": "rich espresso — darkest",
    "#E0CEBC": "cool beige — light",
    "#F2D3C4": "rosy fair — light",
    "#D9B896": "warm sand — medium",
}

_HAIR_BASE_LABELS: dict[str, str] = {
    "#1A0E07": "near-black",
    "#2D1B0E": "very dark brown",
    "#0D0703": "jet black",
    "#3B2314": "dark brown",
    "#8B5E3C": "medium brown",
    "#C8712A": "copper / auburn",
    "#D4A055": "golden blonde",
    "#C0B0A0": "silver-grey / platinum",
}

_EYE_IRIS_LABELS: dict[str, str] = {
    "#3D1C02": "dark brown",
    "#2D1200": "very dark brown",
    "#5C3010": "warm brown",
    "#8B6914": "amber / hazel",
    "#5C4A10": "hazel",
    "#2B5BA8": "bright blue",
    "#5C8B7A": "grey-green",
    "#3A7D44": "green",
}


def _hex_label(hex_color: str, table: dict[str, str]) -> str:
    """Return label from *table*, nearest-color label if not found exactly."""
    result = table.get(hex_color.upper())
    if result:
        return result
    if not table:
        return hex_color
    rgb = _hex_to_rgb(hex_color)
    if rgb is None:
        return hex_color
    best_label, best_dist = hex_color, float("inf")
    for entry_hex, label in table.items():
        entry_rgb = _hex_to_rgb(entry_hex)
        if entry_rgb is None:
            continue
        dist = sum((a - b) ** 2 for a, b in zip(rgb, entry_rgb)) ** 0.5
        if dist < best_dist:
            best_dist, best_label = dist, label
    return best_label


def _color_desc(hex_color: str, table: dict[str, str]) -> str:
    """Return '<label> (<hex>)' so the LLM has both semantic and numeric reference."""
    label = _hex_label(hex_color.upper(), table)
    return f"{label} ({hex_color.upper()})"


# ---------------------------------------------------------------------------
# Persona → property descriptions
# ---------------------------------------------------------------------------


def _describe_properties(persona: dict) -> dict[str, str]:
    """Convert an avatar_persona dict to a flat dict of checkable descriptions.

    Color properties include the expected hex in parentheses so the LLM can
    report an ``observed_hex`` that the code checks against in YCbCr space.
    """
    props: dict[str, str] = {}
    personal = persona.get("personal", {})
    appearance = persona.get("appearance", {})

    # ── demographic / visible ────────────────────────────────────────────
    gender = personal.get("gender", "")
    if gender:
        # "non-binary" is not a visually distinct category — describe the
        # presentation style the image model actually renders instead.
        if gender.lower() == "non-binary":
            props["gender"] = "gender-neutral or androgynous appearance"
        else:
            props["gender"] = gender

    # ── skin tone ────────────────────────────────────────────────────────
    skin_hex = appearance.get("skin_tone", "")
    if skin_hex:
        props["skin_tone"] = _color_desc(skin_hex, _SKIN_TONE_LABELS)

    # ── hair ─────────────────────────────────────────────────────────────
    hair_style = appearance.get("hair_style", "")
    if hair_style:
        props["hair_style"] = hair_style

    hair_color = appearance.get("hair_color", {})
    if isinstance(hair_color, dict):
        base_hex = hair_color.get("hex_base", "")
        if base_hex:
            props["hair_color"] = _color_desc(base_hex, _HAIR_BASE_LABELS)
    elif isinstance(hair_color, str) and hair_color:
        first_hex = re.search(r"#[0-9A-Fa-f]{6}", hair_color)
        if first_hex:
            props["hair_color"] = _color_desc(first_hex.group(), _HAIR_BASE_LABELS)

    # ── eyes ─────────────────────────────────────────────────────────────
    eye_shape = appearance.get("eye_shape", "")
    if eye_shape:
        props["eye_shape"] = eye_shape

    eye_color = appearance.get("eye_color", {})
    if isinstance(eye_color, dict):
        iris_hex = eye_color.get("hex_iris", "")
        if iris_hex:
            props["eye_color"] = _color_desc(iris_hex, _EYE_IRIS_LABELS)
    elif isinstance(eye_color, str) and eye_color:
        first_hex = re.search(r"#[0-9A-Fa-f]{6}", eye_color)
        if first_hex:
            props["eye_color"] = _color_desc(first_hex.group(), _EYE_IRIS_LABELS)

    # ── eyebrows ─────────────────────────────────────────────────────────
    brows = appearance.get("brows_style", "")
    if brows:
        props["brows_style"] = brows

    # ── facial structure ─────────────────────────────────────────────────
    for key in ("nose_shape", "chin_shape", "cheeks_shape"):
        val = appearance.get(key, "")
        if val:
            props[key] = val

    # ── clothing — garment name + expected hex ────────────────────────────
    clothing = appearance.get("clothing", {})
    if isinstance(clothing, dict) and clothing:
        items = [f"{garment} ({hex_val})" for garment, hex_val in clothing.items()]
        props["clothing"] = ", ".join(items)
    elif isinstance(clothing, str) and clothing:
        props["clothing"] = clothing

    # ── accessories ──────────────────────────────────────────────────────
    accessories = appearance.get("accessories", {})
    if isinstance(accessories, dict) and accessories:
        parts = [f"{name}: {desc}" for name, desc in accessories.items()]
        props["accessories"] = "; ".join(parts)
    elif isinstance(accessories, str) and accessories not in ("none", ""):
        props["accessories"] = accessories

    return props


# ---------------------------------------------------------------------------
# CategoryReport
# ---------------------------------------------------------------------------


@dataclass
class PropertyResult:
    property_name: str
    expected: str
    visible: bool
    note: str = ""


@dataclass
class CategoryReport:
    """Results from a single categorize_avatar_image call."""

    results: list[PropertyResult] = field(default_factory=list)
    raw_response: str = ""

    @property
    def score(self) -> float:
        """Fraction of properties marked visible (0.0–1.0)."""
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.visible) / len(self.results)

    def failures(self) -> list[str]:
        return [r.property_name for r in self.results if not r.visible]

    def passes(self) -> list[str]:
        return [r.property_name for r in self.results if r.visible]

    def __repr__(self) -> str:
        pct = f"{self.score:.0%}"
        return (
            f"CategoryReport(score={pct}, pass={len(self.passes())}, fail={len(self.failures())})"
        )


# ---------------------------------------------------------------------------
# Main categorizer function
# ---------------------------------------------------------------------------

_CATEGORIZER_SYSTEM = (
    "You are a visual property verifier for AI-generated portrait images. "
    "Given an image and a list of expected visual properties, check each property. "
    "Reply ONLY as YAML. For each property key, output:\n"
    "  visible: true  # or false\n"
    "  note: <one-sentence observation>\n"
    "For color properties (skin_tone, hair_color, eye_color, clothing), also output:\n"
    "  observed_hex: '#RRGGBB'  # the dominant color you observe for this property\n"
    "Be strict but fair for structural properties. "
    "For color properties, always report observed_hex — pass/fail is computed "
    "programmatically from the YCbCr distance between expected and observed."
)


def categorize_avatar_image(
    image_bytes: bytes,
    persona: dict,
    *,
    gateway_url: str = "http://127.0.0.1:4096",
    timeout: int = 60,
) -> CategoryReport:
    """Ask a vision LLM to verify which avatar persona properties are visible."""
    props = _describe_properties(persona)
    if not props:
        logger.warning("categorize_avatar_image: no checkable properties in persona")
        return CategoryReport()

    checklist = "\n".join(f"  {name}: {desc}" for name, desc in props.items())

    color_fmt = "\n  observed_hex: '#RRGGBB'  # report the color you observe"
    response_template = "\n".join(
        f"{name}:\n  visible: true  # or false"
        + (color_fmt if name in _COLOR_PROPERTIES else "")
        + "\n  note: ..."
        for name in props
    )

    user_text = (
        "Examine this portrait image carefully.\n\n"
        "For each property below, determine if it is clearly visible.\n\n"
        "Expected properties:\n"
        f"{checklist}\n\n"
        "Reply as YAML only, using the exact property names as keys:\n"
        f"{response_template}"
    )

    try:
        raw = GatewayClient(gateway_url).image_inspector(
            image_bytes, _CATEGORIZER_SYSTEM, user_text, timeout=timeout
        )
    except Exception as exc:
        logger.error("categorize_avatar_image: LLM call failed: %s", exc)
        raise

    report = _parse_categorizer_response(raw, props)
    report.raw_response = raw
    return report


def _parse_categorizer_response(raw: str, props: dict[str, str]) -> CategoryReport:
    """Parse the LLM YAML response into a CategoryReport.

    For color properties: if the LLM reports an ``observed_hex``, the
    ``visible`` flag is overridden by a YCbCr distance check against the
    expected hex(es) embedded in the property description string.
    """
    cleaned = re.sub(r"^```(?:ya?ml)?\s*\n?", "", raw.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"\n?```\s*$", "", cleaned.strip())

    try:
        parsed = yaml.safe_load(cleaned)
    except yaml.YAMLError as exc:
        logger.warning("categorize: YAML parse failed: %s — raw=%r", exc, raw[:200])
        parsed = {}

    results: list[PropertyResult] = []
    if not isinstance(parsed, dict):
        parsed = {}

    for prop_name, expected_desc in props.items():
        entry = parsed.get(prop_name, {})
        if isinstance(entry, dict):
            visible_raw = entry.get("visible", False)
            visible = (
                visible_raw
                if isinstance(visible_raw, bool)
                else (str(visible_raw).lower().strip() == "true")
            )
            note = str(entry.get("note", "")).strip()

            # For color properties, override with objective YCbCr distance check.
            if prop_name in _COLOR_PROPERTIES:
                observed_hex = str(entry.get("observed_hex", "")).strip()
                if re.match(r"^#[0-9A-Fa-f]{6}$", observed_hex):
                    color_ok = _within_color_tolerance(observed_hex, expected_desc)
                    if color_ok is not None:
                        visible = color_ok
                        logger.debug(
                            "YCbCr override: %s observed=%s expected=%s → visible=%s",
                            prop_name,
                            observed_hex,
                            expected_desc,
                            visible,
                        )
        else:
            visible = False
            note = ""

        results.append(
            PropertyResult(
                property_name=prop_name,
                expected=expected_desc,
                visible=visible,
                note=note,
            )
        )

    return CategoryReport(results=results)
