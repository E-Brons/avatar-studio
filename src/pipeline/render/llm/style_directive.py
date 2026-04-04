"""Style directive builder — build the system-prompt prefix for image generation."""

from __future__ import annotations


def build_style_directive(style_entry: dict, bg_color: str = "#F5F0E8") -> str:
    """Substitute ``[BG_COLOR]`` in the style's system_prompt."""
    return (style_entry.get("system_prompt") or "").replace("[BG_COLOR]", bg_color)
