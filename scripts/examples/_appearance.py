"""Shared appearance extraction schema, prompts, and utilities.

Used by download_examples.py and enrich_persona.py — single source of truth.

The LLM returns a flat dict (APPEARANCE_SCHEMA).  Use flat_to_persona_appearance()
to convert to the nested format written into persona.yml.
"""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema (flat — what the LLM returns)
# ---------------------------------------------------------------------------

APPEARANCE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "skin_tone": {
            "type": "string",
            "description": "Dominant skin tone as #RRGGBB hex code only, e.g. '#C9A96E'",
        },
        "skin_texture": {
            "type": "string",
            "minLength": 10,
            "description": "2-5 word skin texture description, e.g. 'smooth and clear with subtle sheen'",
        },
        "presentation": {
            "type": "string",
            "description": "Visual gender presentation: masculine-presenting, feminine-presenting, androgynous, gender-neutral",
        },
        "hair_style": {
            "type": "string",
            "minLength": 20,
            "description": (
                "Hair length, cut, texture, and styling in 5-15 words, e.g. "
                "'shoulder-length loose waves with a centre part and slight volume at the crown'"
            ),
        },
        "hair_note": {
            "type": "string",
            "description": (
                "CRITICAL note about distinctive hair features (length, shave pattern, texture). "
                "Empty string if unremarkable."
            ),
        },
        "hair_color_base": {
            "type": "string",
            "description": "Base hair color as #RRGGBB hex code only",
        },
        "hair_color_shadow": {
            "type": "string",
            "description": "Shadow/darker hair tone as #RRGGBB hex code only",
        },
        "face_shape": {
            "type": "string",
            "minLength": 20,
            "description": (
                "Overall face shape with defining proportions in 5-15 words, e.g. "
                "'softly oval with high cheekbones and a gently tapered jaw'"
            ),
        },
        "eye_shape": {
            "type": "string",
            "minLength": 20,
            "description": (
                "Eye shape including lid type, corner angle, and distinctive features in 5-15 words, e.g. "
                "'almond-shaped with a slight upward tilt, deep-set and framed by long lashes'"
            ),
        },
        "eye_color_iris": {
            "type": "string",
            "description": "Iris color as #RRGGBB hex code only",
        },
        "eye_color_pupil": {
            "type": "string",
            "description": "Pupil color as #RRGGBB hex code only — typically very dark",
        },
        "brows_style": {
            "type": "string",
            "minLength": 20,
            "description": (
                "Brow shape, arch, thickness, and grooming in 5-15 words, e.g. "
                "'thick straight brows with a soft arch and dense natural hair'"
            ),
        },
        "brows_color": {
            "type": "string",
            "description": "Brow color as #RRGGBB hex code only",
        },
        "nose_shape": {
            "type": "string",
            "minLength": 20,
            "description": (
                "Nose shape covering bridge, tip, and nostrils in 5-15 words, e.g. "
                "'medium-width bridge, rounded tip, slightly flared nostrils'"
            ),
        },
        "chin_shape": {
            "type": "string",
            "minLength": 20,
            "description": (
                "Chin shape and jawline character in 5-15 words, e.g. "
                "'softly rounded chin with a gently defined jawline'"
            ),
        },
        "cheeks_shape": {
            "type": "string",
            "minLength": 20,
            "description": (
                "Cheekbone prominence, fullness, and jaw width in 5-15 words, e.g. "
                "'prominent high cheekbones with sculpted hollows and a narrow jaw'"
            ),
        },
        "clothing": {
            "type": "object",
            "additionalProperties": {"type": "string"},
            "description": "Visible garment name → dominant color #RRGGBB",
        },
        "accessories": {
            "type": "object",
            "additionalProperties": {"type": "string"},
            "description": "Accessory name → visual description",
        },
        "suggested_bg_color": {
            "type": "string",
            "description": "Background color as #RRGGBB hex code that would complement this subject",
        },
        "zodiac": {
            "type": "string",
            "description": "Zodiac sign if you know this celebrity's birthdate; otherwise 'unknown'",
        },
        "religion": {
            "type": "string",
            "description": "Religion if publicly known for this person; otherwise 'unknown'",
        },
    },
    "required": [
        "skin_tone",
        "skin_texture",
        "presentation",
        "hair_style",
        "hair_note",
        "hair_color_base",
        "hair_color_shadow",
        "face_shape",
        "eye_shape",
        "eye_color_iris",
        "eye_color_pupil",
        "brows_style",
        "brows_color",
        "nose_shape",
        "chin_shape",
        "cheeks_shape",
        "clothing",
        "accessories",
        "suggested_bg_color",
        "zodiac",
        "religion",
    ],
    "additionalProperties": False,
}

APPEARANCE_OUTPUT_CONFIG: dict = {"format": {"type": "json_schema", "schema": APPEARANCE_SCHEMA}}

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

APPEARANCE_SYSTEM = (
    "You are an expert portrait analyst producing detailed visual descriptions for AI avatar generation. "
    "Examine every feature carefully and write rich, specific multi-word descriptions — never single words. "
    "All color fields must be #RRGGBB hex codes — never use color names like 'fair', 'brown', or 'dark'. "
    "For zodiac and religion, draw on your knowledge of this person; if genuinely unknown, use 'unknown'. "
    "Do not guess colors — report what you actually observe in the image."
)

APPEARANCE_PROMPT = (
    "Analyze this portrait photograph and extract all visual appearance attributes. "
    "For every shape/style field write a descriptive phrase of 5-15 words that captures "
    "the feature's specific character — shape, proportions, texture, and any distinctive qualities. "
    "Never answer with a single word like 'oval' or 'almond'; always elaborate. "
    "Be precise with hex color values by sampling the actual colors visible in the image. "
    "For clothing, only include items clearly visible in the frame (e.g. 'top', 'jacket'). "
    "For accessories, only include items clearly visible (e.g. 'earrings', 'glasses', 'necklace'). "
    "If hair is not visible, set hair_style to 'not visible' and use '#333333' for hair_color fields. "
    "Respond with JSON only."
)

# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def _parse_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def extract_appearance(
    gateway,
    image_bytes: bytes,
    name: str,
    *,
    timeout: int = 120,
) -> dict:
    """Call the vision LLM to extract appearance attributes from a portrait.

    Returns a flat dict matching APPEARANCE_SCHEMA, or {} on failure.
    """
    try:
        raw = gateway.image_inspector(
            image_bytes,
            system=APPEARANCE_SYSTEM,
            prompt=APPEARANCE_PROMPT,
            timeout=timeout,
            output_config=APPEARANCE_OUTPUT_CONFIG,
        )
        return _parse_json(raw)
    except Exception as exc:
        logger.warning("Appearance extraction failed for %r: %s", name, exc)
        return {}


# ---------------------------------------------------------------------------
# Conversion: flat LLM output → nested persona.yml appearance section
# ---------------------------------------------------------------------------

_PERSONA_APPEARANCE_KEYS = (
    "skin_tone",
    "skin_texture",
    "presentation",
    "hair_style",
    "hair_note",
    "face_shape",
    "eye_shape",
    "brows_style",
    "brows_color",
    "nose_shape",
    "chin_shape",
    "cheeks_shape",
)


def flat_to_persona_appearance(flat: dict) -> dict:
    """Convert flat LLM appearance dict to the nested format used in persona.yml.

    Nested fields produced:
        hair_color: {hex_base, hex_shadow}
        eye_color:  {hex_iris, hex_pupil}

    All other fields are passed through as-is (excluding clothing, accessories,
    suggested_bg_color, zodiac, religion — those belong elsewhere in persona.yml).
    """
    out: dict = {}

    for key in _PERSONA_APPEARANCE_KEYS:
        val = flat.get(key)
        if val:
            out[key] = val

    if flat.get("hair_color_base"):
        out["hair_color"] = {
            "hex_base": flat["hair_color_base"],
            "hex_shadow": flat.get("hair_color_shadow") or flat["hair_color_base"],
        }

    if flat.get("eye_color_iris"):
        out["eye_color"] = {
            "hex_iris": flat["eye_color_iris"],
            "hex_pupil": flat.get("eye_color_pupil") or "#0A0A0A",
        }

    return out
