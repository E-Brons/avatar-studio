"""Standalone LLM-based categorizer for avatar visual property verification.

Can be imported by any integration or unit test.  The only requirement is a
running Ollama (or any litellm-compatible) server with a vision-capable model.

Usage
-----
    from avatar_studio.tuning.classify_persona import categorize_avatar_image, CategoryReport

    report = categorize_avatar_image(
        image_bytes,
        persona,
        model="ollama/llava:latest",
        ollama_url="http://127.0.0.1:4096",
    )
    print(f"score={report.score:.0%}")   # e.g. "score=87%"
    print(report.failures())             # list of unmatched properties
"""
from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import litellm
import yaml

from avatar_studio.config.config import SETTINGS

logger = logging.getLogger(__name__)

_DEFAULT_VISUAL_DESC_MODEL: str = SETTINGS["default_visual_desc_model"]

# ---------------------------------------------------------------------------
# Color → human-readable label tables
# (hex values that appear in avatar_studio_settings.json)
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
    """Return a label from *table* or fall back to the raw hex."""
    return table.get(hex_color.upper(), hex_color)


# ---------------------------------------------------------------------------
# Persona → property descriptions
# ---------------------------------------------------------------------------

def _describe_properties(persona: dict) -> dict[str, str]:
    """Convert an avatar_persona dict to a flat dict of checkable descriptions.

    Returns {property_name: human_readable_description}.  Only properties that
    are directly visible in a portrait are included.
    """
    props: dict[str, str] = {}
    personal = persona.get("personal", {})
    appearance = persona.get("appearance", {})

    # ── demographic / visible ────────────────────────────────────────────
    gender = personal.get("gender", "")
    if gender:
        props["gender"] = gender

    # ── skin tone ────────────────────────────────────────────────────────
    skin_hex = appearance.get("skin_tone", "")
    if skin_hex:
        props["skin_tone"] = _hex_label(skin_hex.upper(), _SKIN_TONE_LABELS)

    # ── hair ─────────────────────────────────────────────────────────────
    hair_style = appearance.get("hair_style", "")
    if hair_style:
        props["hair_style"] = hair_style

    hair_color = appearance.get("hair_color", {})
    if isinstance(hair_color, dict):
        base_hex = hair_color.get("hex_base", "")
        if base_hex:
            props["hair_color"] = _hex_label(base_hex.upper(), _HAIR_BASE_LABELS)
    elif isinstance(hair_color, str) and hair_color:
        first_hex = re.search(r"#[0-9A-Fa-f]{6}", hair_color)
        if first_hex:
            props["hair_color"] = _hex_label(first_hex.group().upper(), _HAIR_BASE_LABELS)

    # ── eyes ─────────────────────────────────────────────────────────────
    eye_shape = appearance.get("eye_shape", "")
    if eye_shape:
        props["eye_shape"] = eye_shape

    eye_color = appearance.get("eye_color", {})
    if isinstance(eye_color, dict):
        iris_hex = eye_color.get("hex_iris", "")
        if iris_hex:
            props["eye_color"] = _hex_label(iris_hex.upper(), _EYE_IRIS_LABELS)
    elif isinstance(eye_color, str) and eye_color:
        first_hex = re.search(r"#[0-9A-Fa-f]{6}", eye_color)
        if first_hex:
            props["eye_color"] = _hex_label(first_hex.group().upper(), _EYE_IRIS_LABELS)

    # ── eyebrows ─────────────────────────────────────────────────────────
    brows = appearance.get("brows_style", "")
    if brows:
        props["brows_style"] = brows

    # ── facial structure (harder, lower-weight) ───────────────────────
    for key in ("nose_shape", "chin_shape", "cheeks_shape"):
        val = appearance.get(key, "")
        if val:
            props[key] = val

    # ── clothing ─────────────────────────────────────────────────────────
    clothing = appearance.get("clothing", {})
    if isinstance(clothing, dict) and clothing:
        items = []
        for garment, color_hex in clothing.items():
            label = _hex_label(str(color_hex).upper(), {})
            items.append(f"{garment} ({color_hex})")
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
        """Property names that were NOT found."""
        return [r.property_name for r in self.results if not r.visible]

    def passes(self) -> list[str]:
        """Property names that WERE found."""
        return [r.property_name for r in self.results if r.visible]

    def __repr__(self) -> str:
        pct = f"{self.score:.0%}"
        return (
            f"CategoryReport(score={pct}, "
            f"pass={len(self.passes())}, "
            f"fail={len(self.failures())})"
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
    "Be strict but fair: 'visible: true' means the property is clearly identifiable "
    "in the image. Subtle or ambiguous cases should be 'false'."
)


def categorize_avatar_image(
    image_bytes: bytes,
    persona: dict,
    *,
    model: str = _DEFAULT_VISUAL_DESC_MODEL,
    ollama_url: str = "http://127.0.0.1:4096",
    timeout: int = 60,
) -> CategoryReport:
    """Ask a vision LLM to verify which avatar persona properties are visible.

    Parameters
    ----------
    image_bytes:
        Raw PNG/JPEG bytes of the generated avatar image.
    persona:
        The ``avatar_persona`` dict from the rand/image pipeline.
    model:
        litellm model string, e.g. ``"ollama/llava:latest"`` or
        ``"ollama/llava-llama3"``.
    ollama_url:
        Base URL of the Ollama server.
    timeout:
        Request timeout in seconds.

    Returns
    -------
    CategoryReport
        Per-property visibility results and an aggregate score.
    """
    props = _describe_properties(persona)
    if not props:
        logger.warning("categorize_avatar_image: no checkable properties in persona")
        return CategoryReport()

    # Build the property checklist
    checklist_lines = []
    for name, description in props.items():
        checklist_lines.append(f"  {name}: {description}")
    checklist = "\n".join(checklist_lines)

    user_text = (
        "Examine this portrait image carefully.\n\n"
        "For each property below, determine if it is clearly visible.\n\n"
        "Expected properties:\n"
        f"{checklist}\n\n"
        "Reply as YAML only, using the exact property names as keys:\n"
        + "\n".join(
            f"{name}:\n  visible: true  # or false\n  note: ..."
            for name in props
        )
    )

    b64 = base64.b64encode(image_bytes).decode()
    messages = [
        {"role": "system", "content": _CATEGORIZER_SYSTEM},
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                },
                {"type": "text", "text": user_text},
            ],
        },
    ]

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 1024,
        "timeout": timeout,
    }
    if "ollama" in model.lower():
        kwargs["api_base"] = ollama_url

    try:
        response = litellm.completion(**kwargs)
        raw = response.choices[0].message.content or ""
    except Exception as exc:
        logger.error("categorize_avatar_image: LLM call failed: %s", exc)
        raise

    report = _parse_categorizer_response(raw, props)
    report.raw_response = raw
    return report


def _parse_categorizer_response(raw: str, props: dict[str, str]) -> CategoryReport:
    """Parse the LLM YAML response into a CategoryReport."""
    # Strip code fences
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
            # Accept both boolean and string "true"/"false"
            if isinstance(visible_raw, bool):
                visible = visible_raw
            else:
                visible = str(visible_raw).lower().strip() == "true"
            note = str(entry.get("note", "")).strip()
        else:
            visible = False
            note = ""

        results.append(PropertyResult(
            property_name=prop_name,
            expected=expected_desc,
            visible=visible,
            note=note,
        ))

    return CategoryReport(results=results)
