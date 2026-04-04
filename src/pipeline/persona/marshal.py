"""Persona marshalling — combine demographics + advisor + features into the
canonical ``avatar_persona`` dict used by the image prompt and the UI panel.

Moved here from ``step_c_select_features.py``.
"""

from __future__ import annotations

import re

from config.config import SETTINGS

_INJECTION_MARKERS = ("###", "### Instruction", "### System:", "```")

# Loaded from settings — maps field names to their hex sub-field names.
_HEX_FIELD_NAMES: dict[str, tuple[str, ...]] = {
    k.upper(): tuple(v) for k, v in SETTINGS.get("persona_hex_fields", {}).items()
}
_DICT_PASSTHROUGH_KEYS: set[str] = {k.upper() for k in SETTINGS.get("persona_dict_fields", [])}


def parse_color_value(key: str, raw_value: str) -> str | dict:
    """Parse a raw feature value into a structured color dict or plain string.

    Multi-hex colors (e.g. ``HAIR_COLOR: '#3B2314 #261508'``) are split into
    named hex fields per the persona schema.  Single-hex values are returned
    as plain strings.
    """
    hexes = re.findall(r"#[0-9A-Fa-f]{6}", raw_value)
    if not hexes:
        return raw_value

    field_names = _HEX_FIELD_NAMES.get(key)
    if field_names and len(hexes) >= len(field_names):
        return {fname: hval for fname, hval in zip(field_names, hexes)}

    # Single hex — return as plain string
    return hexes[0]


def marshal_avatar_persona(demographics: dict, advisor: dict, features: dict | None) -> dict:
    """Combine demographics + advisor + features into the ``avatar_persona`` dict."""
    name = demographics.get("name") or (features.get("NAME", "") if features else "")

    persona: dict = {
        "personal": {
            "name": name,
            "gender": demographics["gender"],
            "age": demographics["age"],
        },
        "style": {
            "bg_color": demographics.get("bg_color", "#4A90D9"),
            "fg_color": demographics.get("fg_color", "#FFFFFF"),
        },
        "advisor": {
            "role": advisor.get("role", "Advisor"),
            "education": advisor.get("education", []),
            "experience": advisor.get("experience", []),
            "traits": advisor.get("traits", []),
        },
    }

    if not features:
        persona["appearance"] = {}
        return persona

    appearance: dict = {}
    for key, value in features.items():
        if key == "NAME":
            continue
        snake_key = key.lower()
        if key in _DICT_PASSTHROUGH_KEYS:
            appearance[snake_key] = value
        elif key in _HEX_FIELD_NAMES:
            appearance[snake_key] = (
                parse_color_value(key, value) if isinstance(value, str) else value
            )
        else:
            appearance[snake_key] = value
    persona["appearance"] = appearance

    return persona


def sanitize_str(v: str, max_chars: int = 100) -> str:
    """Strip prompt-injection contamination and truncate a string value."""
    for marker in _INJECTION_MARKERS:
        if marker in v:
            v = v.split(marker)[0].strip()
    v = v.splitlines()[0].strip()
    return v[:max_chars]


def visual_only_persona(persona: dict) -> dict:
    """Return a stripped persona with only visual cues for the image model.

    Removes text-heavy fields (education, experience, traits, name) that
    the image model may render as literal text.  Sanitizes all string values
    to strip any system-prompt contamination that leaked from the text LLM.
    """
    personal = persona.get("personal", {})
    advisor = persona.get("advisor", {})
    appearance = persona.get("appearance", {})

    visual_personal = {}
    for k in ("gender", "age", "appearance_id"):
        v = personal.get(k)
        if v is not None:
            visual_personal[k] = sanitize_str(str(v)) if isinstance(v, str) else v

    visual_advisor = {"role": sanitize_str(str(advisor.get("role", "professional")))}

    _APPEARANCE_EXCLUDE = {"eye_shape"}
    visual_appearance: dict = {}
    for k, v in appearance.items():
        if k in _APPEARANCE_EXCLUDE:
            continue
        if isinstance(v, str):
            visual_appearance[k] = sanitize_str(v)
        elif isinstance(v, dict):
            visual_appearance[k] = {
                sk: sanitize_str(sv) if isinstance(sv, str) else sv for sk, sv in v.items()
            }

    return {
        "personal": visual_personal,
        "advisor": visual_advisor,
        "appearance": visual_appearance,
    }
