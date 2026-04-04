"""Persona schema — load and expose the pipeline-facing attribute schema."""

from __future__ import annotations

from pathlib import Path

import yaml

_SCHEMA_PATH = Path(__file__).resolve().parent.parent.parent.parent / "assets" / "persona" / "persona_schema.yml"


class PersonaSchema:
    """Loaded persona_schema.yml, keyed by attribute name."""

    def __init__(self, path: Path = _SCHEMA_PATH) -> None:
        with open(path) as f:
            raw = yaml.safe_load(f)
        self._attrs: dict = raw.get("attributes", {})

    @property
    def attributes(self) -> dict:
        return self._attrs

    def __contains__(self, key: str) -> bool:
        return key in self._attrs

    def get(self, key: str) -> dict | None:
        return self._attrs.get(key)

    def keys(self) -> list[str]:
        return list(self._attrs.keys())

    def valid_selector_types(self, key: str) -> list[str]:
        entry = self._attrs.get(key, {})
        return entry.get("selector_types", [])

    def default_selector(self, key: str) -> str | None:
        entry = self._attrs.get(key, {})
        return entry.get("default_selector")

    def default_value(self, key: str):
        entry = self._attrs.get(key, {})
        return entry.get("default_value")


# Module-level singleton — loaded once.
_schema: PersonaSchema | None = None


def get_schema() -> PersonaSchema:
    global _schema
    if _schema is None:
        _schema = PersonaSchema()
    return _schema
