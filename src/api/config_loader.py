"""Config loader — resolves source: refs in attributes.yml to concrete options.

Reads assets/persona/attributes.yml and expands each attribute's source: field
into a typed list of AttributeOptionItem objects.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_ATTRIBUTES_YML = _PROJECT_ROOT / "assets" / "persona" / "attributes.yml"
_PHENOTYPE_SETTINGS = _PROJECT_ROOT / "assets" / "persona" / "phenotype_settings.json"
_PRESENTATION_SETTINGS = _PROJECT_ROOT / "assets" / "persona" / "presentation_settings.json"
_DEMOGRAPHICS_YML = _PROJECT_ROOT / "assets" / "persona" / "demographics.yml"
_STYLES_YML = _PROJECT_ROOT / "assets" / "styles" / "styles.yml"


# ─── Data models (plain dicts for JSON serialisation) ────────────────────────


def _option(id: str, label: str, extra: dict | None = None) -> dict:
    o: dict = {"id": id, "label": label}
    if extra:
        o["extra"] = extra
    return o


def _attr_out(raw: dict, options: list[dict]) -> dict:
    """Build the serialisable attribute dict sent to the client."""
    out: dict[str, Any] = {
        "id": raw["id"],
        "label": raw["label"],
        "category": raw["category"],
        "type": raw["type"],
        "selection_modes": raw["selection_modes"],
        "default_mode": raw["default_mode"],
        "options": options,
    }
    # optional fields
    for key in ("depends_on", "llm_generated", "range", "field_names", "formula", "suggestions"):
        if key in raw:
            out[key] = raw[key]
    return out


# ─── ConfigLoader ─────────────────────────────────────────────────────────────


class ConfigLoader:
    def __init__(self) -> None:
        with open(_ATTRIBUTES_YML) as f:
            self._raw_attrs: list[dict] = yaml.safe_load(f)["attributes"]

        with open(_PHENOTYPE_SETTINGS) as f:
            self._phenotype: dict = json.load(f)

        with open(_PRESENTATION_SETTINGS) as f:
            self._presentation: dict = json.load(f)

        with open(_DEMOGRAPHICS_YML) as f:
            self._demographics: dict = yaml.safe_load(f)

        with open(_STYLES_YML) as f:
            self._styles_data: dict = yaml.safe_load(f)

    # ── Public ────────────────────────────────────────────────────────────────

    def load(self) -> dict:
        """Return the full config response: list of resolved attributes."""
        attributes = [self._resolve_attr(attr) for attr in self._raw_attrs]
        return {"attributes": attributes}

    # ── Private ───────────────────────────────────────────────────────────────

    def _resolve_attr(self, raw: dict) -> dict:
        if "options" in raw:
            # Inline options (e.g. gender)
            options = [_option(o["id"], o["label"]) for o in raw["options"]]
        elif "source" in raw:
            options = self._resolve_options(raw)
        else:
            options = []
        return _attr_out(raw, options)

    def _resolve_options(self, raw: dict) -> list[dict]:
        source: str = raw["source"]
        filename, key_path = source.split(":", 1)

        if filename == "styles.yml":
            return self._load_styles_options()

        # Load from JSON settings file
        if filename == "phenotype_settings.json":
            data = self._phenotype
        elif filename == "presentation_settings.json":
            data = self._presentation
        elif filename == "demographics.yml":
            return self._load_demographics_options(key_path)
        else:
            raise ValueError(f"Unknown source file: {filename}")

        # Navigate key path (supports single-level key only for now)
        value = data
        for part in key_path.split("."):
            value = value[part]

        attr_type = raw.get("type", "choice")
        field_names = raw.get("field_names")

        if attr_type == "integer":
            # age_groups → list of {id, label, extra:{min,max}}
            return self._parse_age_groups(value)

        if isinstance(value, dict):
            # gender-bucketed dict
            return self._parse_gender_bucketed(value, attr_type, field_names)

        if isinstance(value, list):
            if attr_type == "dual_color":
                return self._parse_dual_color_options(value, field_names or ["hex_a", "hex_b"])
            if attr_type == "color":
                return [_option(v, v) for v in value]
            # plain string list
            return [_option(v, v) for v in value]

        return []

    def _parse_age_groups(self, age_groups_dict: dict) -> list[dict]:
        options = []
        for group_id, bounds in age_groups_dict.items():
            lo, hi = bounds
            options.append(
                _option(
                    group_id,
                    f"{group_id.replace('_', ' ').title()} ({lo}–{hi})",
                    {"min": lo, "max": hi},
                )
            )
        return options

    def _parse_gender_bucketed(
        self, bucket_dict: dict, attr_type: str, field_names: list[str] | None
    ) -> list[dict]:
        """Return all items tagged with their gender bucket."""
        options = []
        for bucket in ("male", "female", "neutral"):
            items = bucket_dict.get(bucket, [])
            for item in items:
                extra = {"gender_bucket": bucket}
                if attr_type == "dual_color" and field_names:
                    parts = item.split()
                    if len(parts) >= 2:
                        extra.update({field_names[0]: parts[0], field_names[1]: parts[1], **extra})
                options.append(_option(item, item, extra))
        return options

    def _parse_dual_color_options(self, raw_list: list[str], field_names: list[str]) -> list[dict]:
        """Split '#BASE #SHADOW' strings into extra fields."""
        options = []
        for item in raw_list:
            parts = item.split()
            extra: dict = {}
            if len(parts) >= 2:
                extra = {field_names[0]: parts[0], field_names[1]: parts[1]}
            options.append(_option(item, item, extra))
        return options

    def _load_demographics_options(self, key: str) -> list[dict]:
        """Load options from demographics.yml — items have {id, label, group}."""
        items: list[dict] = self._demographics.get(key, [])
        options = []
        for item in items:
            extra: dict | None = {"group": item["group"]} if "group" in item else None
            options.append(_option(item["id"], item["label"], extra))
        return options

    def _load_styles_options(self) -> list[dict]:
        options = []
        for style in self._styles_data.get("styles", []):
            extra = {
                "engine": style.get("engine", "llm"),
                "icon": style.get("icon", "image"),
                "description": style.get("description", ""),
                "credit": style.get("credit", ""),
                "example_images": style.get("example_images", []),
            }
            options.append(_option(style["id"], style["name"], extra))
        return options
