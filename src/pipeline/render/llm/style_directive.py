"""Style directive builder — build the system-prompt prefix for image generation."""

from __future__ import annotations


def get_system_prompt(style_entry: dict) -> str:
    """Return the system prompt template for a style entry (create.llm_params.system_prompt_template)."""
    create = style_entry.get("create") or {}
    llm_params = create.get("llm_params") or {}
    return llm_params.get("system_prompt_template") or ""


def build_style_directive(style_entry: dict, bg_color: str = "#F5F0E8") -> str:
    """Substitute ``[BG_COLOR]`` in the style's system prompt template."""
    return get_system_prompt(style_entry).replace("[BG_COLOR]", bg_color)
