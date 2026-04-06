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

import json
import logging
import re
from dataclasses import dataclass, field

from config.config import SETTINGS
from config.gateway import GatewayClient

logger = logging.getLogger(__name__)

_DEFAULT_VISUAL_DESC_MODEL: str = SETTINGS["default_visual_desc_model"]

# ---------------------------------------------------------------------------
# Color properties — pass/fail is determined by YCbCr distance, not LLM binary
# ---------------------------------------------------------------------------

_COLOR_PROPERTIES: frozenset[str] = frozenset({"skin_tone", "hair_color", "eye_color", "clothing"})

# Approximate maximum Euclidean distance in YCbCr space between any two colors.
_MAX_YCBCR_DISTANCE: float = 325.0

# Normalized proximity threshold for color matching (proximity = 1 - dist/max).
# Colors with proximity >= threshold are considered a close match.
VALIDATION_COLOR_DISTANCE_THRESHOLD: float = 0.70

# Per-property scoring weights (doc §4.4). Unknown properties default to 1.
_PROPERTY_WEIGHTS: dict[str, float] = {
    "gender": 30,
    "hair_style": 15,
    "eye_shape": 4,
    "brows_style": 8,
    "nose_shape": 6,
    "chin_shape": 8,
    "cheeks_shape": 7,
    "accessories": 10,
    "clothing": 10,  # 5 structural + 5 color (combined property)
    "skin_tone": 25,
    "hair_color": 10,
    "eye_color": 15,
}


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


def _color_proximity(observed_hex: str, expected_desc: str) -> float | None:
    """Return normalized proximity [0,1] between observed_hex and the nearest expected hex.

    Returns None when expected_desc contains no hex values.
    Proximity = 1 - (raw_ycbcr_distance / MAX), so 1.0 = identical, 0.0 = maximally different.
    """
    expected_hexes = re.findall(r"#[0-9A-Fa-f]{6}", expected_desc)
    if not expected_hexes:
        return None
    min_dist = min(_ycbcr_distance(observed_hex, h) for h in expected_hexes)
    proximity = 1.0 - min(min_dist / _MAX_YCBCR_DISTANCE, 1.0)
    logger.debug(
        "_color_proximity: observed=%s expected=%s min_dist=%.1f proximity=%.3f threshold=%.2f",
        observed_hex,
        expected_hexes,
        min_dist,
        proximity,
        VALIDATION_COLOR_DISTANCE_THRESHOLD,
    )
    return proximity


def _within_color_tolerance(observed_hex: str, expected_desc: str) -> bool | None:
    """Return True/False if observed_hex is within proximity threshold of any hex in
    expected_desc, or None when expected_desc contains no hex values."""
    proximity = _color_proximity(observed_hex, expected_desc)
    if proximity is None:
        return None
    return proximity >= VALIDATION_COLOR_DISTANCE_THRESHOLD


def _compute_color_score(observed_hex: str, expected_desc: str) -> float | None:
    """Compute Color Score for a color property (doc §4.4).

    proximity = 1 - normalized_ycbcr_distance (1=identical, 0=maximally different)
    - success (proximity >= threshold): Color Score = proximity
    - failure (proximity < threshold): Color Score = proximity^2  (amplifies failure)

    Returns None when expected_desc contains no hex values.
    """
    proximity = _color_proximity(observed_hex, expected_desc)
    if proximity is None:
        return None
    if proximity >= VALIDATION_COLOR_DISTANCE_THRESHOLD:
        return proximity
    return proximity**2


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
    color_score: float | None = None  # set for color properties when observed_hex is reported


@dataclass
class CategoryReport:
    """Results from a single categorize_avatar_image call."""

    results: list[PropertyResult] = field(default_factory=list)
    raw_response: str = ""

    @property
    def score(self) -> float:
        """Weighted persona score (0.0–1.0); higher = better fidelity.

        Each property contributes weight × property_score where:
        - Structural: property_score = 1.0 if visible else 0.0
        - Color: property_score = color_score (proximity-based, §4.4)
        Properties not in _PROPERTY_WEIGHTS default to weight 1.
        """
        if not self.results:
            return 0.0
        total_weight = sum(_PROPERTY_WEIGHTS.get(r.property_name, 1) for r in self.results)
        if total_weight == 0:
            return 0.0
        total_score = sum(
            _PROPERTY_WEIGHTS.get(r.property_name, 1)
            * (r.color_score if r.color_score is not None else (1.0 if r.visible else 0.0))
            for r in self.results
        )
        return total_score / total_weight

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

# ---------------------------------------------------------------------------
# Main categorizer function
# ---------------------------------------------------------------------------

# JSON schema for the vision model response. observed_hex is always present
# (empty string for structural properties that have no color).
_PERSONA_PROPERTY_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "visible": {"type": "boolean"},
        "note": {"type": "string"},
        "observed_hex": {"type": "string"},
    },
    "required": ["name", "visible", "note", "observed_hex"],
    "additionalProperties": False,
}

_PERSONA_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "properties": {
            "type": "array",
            "items": _PERSONA_PROPERTY_SCHEMA,
        }
    },
    "required": ["properties"],
    "additionalProperties": False,
}

_PERSONA_OUTPUT_CONFIG: dict = {"format": {"type": "json_schema", "schema": _PERSONA_SCHEMA}}

_CATEGORIZER_SYSTEM = (
    "You are a visual property verifier for AI-generated portrait images. "
    "Given an image and a list of expected visual properties, check each property. "
    "Return a JSON array of property results. For each property set:\n"
    "  visible: true or false\n"
    "  note: one-sentence observation\n"
    "For color properties (skin_tone, hair_color, eye_color, clothing), set observed_hex "
    "to the dominant '#RRGGBB' color you observe; set it to '' for structural properties. "
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

    user_text = (
        "Examine this portrait image carefully.\n\n"
        "For each property below, determine if it is clearly visible.\n\n"
        "Expected properties:\n"
        f"{checklist}\n\n"
        "Return a result entry for every property name listed above."
    )

    try:
        raw = GatewayClient(gateway_url).image_inspector(
            image_bytes,
            _CATEGORIZER_SYSTEM,
            user_text,
            timeout=timeout,
            output_config=_PERSONA_OUTPUT_CONFIG,
        )
    except Exception as exc:
        logger.error("categorize_avatar_image: LLM call failed: %s", exc)
        raise

    report = _parse_categorizer_response(raw, props)
    report.raw_response = raw
    return report


def _parse_categorizer_response(raw: str, props: dict[str, str]) -> CategoryReport:
    """Parse the LLM JSON response into a CategoryReport.

    For color properties: if the LLM reports a non-empty observed_hex, the
    ``visible`` flag is overridden by a YCbCr distance check against the
    expected hex(es) embedded in the property description string.
    """
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("categorize: JSON parse failed: %s — raw=%r", exc, raw[:200])
        parsed = {}

    if not isinstance(parsed, dict):
        parsed = {}

    # Build a lookup of name → entry from the array response.
    entries: dict[str, dict] = {}
    for item in parsed.get("properties", []):
        if isinstance(item, dict):
            name = str(item.get("name", "")).strip()
            if name:
                entries[name] = item

    results: list[PropertyResult] = []
    for prop_name, expected_desc in props.items():
        entry = entries.get(prop_name, {})
        if isinstance(entry, dict) and entry:
            visible = bool(entry.get("visible", False))
            note = str(entry.get("note", "")).strip()
            color_score: float | None = None

            # For color properties, override visible and compute color_score from YCbCr proximity.
            if prop_name in _COLOR_PROPERTIES:
                observed_hex = str(entry.get("observed_hex", "")).strip()
                if re.match(r"^#[0-9A-Fa-f]{6}$", observed_hex):
                    color_ok = _within_color_tolerance(observed_hex, expected_desc)
                    score = _compute_color_score(observed_hex, expected_desc)
                    if color_ok is not None:
                        visible = color_ok
                        color_score = score
                        logger.debug(
                            "YCbCr override: %s observed=%s expected=%s → visible=%s score=%.3f",
                            prop_name,
                            observed_hex,
                            expected_desc,
                            visible,
                            color_score if color_score is not None else 0.0,
                        )
        else:
            visible = False
            note = ""
            color_score = None

        results.append(
            PropertyResult(
                property_name=prop_name,
                expected=expected_desc,
                visible=visible,
                note=note,
                color_score=color_score,
            )
        )

    return CategoryReport(results=results)
