"""Persona sanitizer for the image model — strip text-heavy fields."""

from __future__ import annotations

from pipeline.persona.marshal import visual_only_persona


def sanitize_persona(persona: dict) -> dict:
    """Return a visual-only persona dict suitable for the image prompt."""
    return visual_only_persona(persona)
