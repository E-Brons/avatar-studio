"""Style resolver — look up a style entry from styles.yml."""

from __future__ import annotations

from pathlib import Path

import yaml

from pipeline.render.llm.style_directive import build_style_directive

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
STYLES_YML = _PROJECT_ROOT / "assets" / "styles" / "styles.yml"


def resolve_style(
    style_name: str, bg_color: str = "#F5F0E8", styles_yml: Path = STYLES_YML
) -> tuple[dict, str]:
    """Return (style_entry, style_directive) for *style_name*.

    *style_directive* is the system_prompt_template with ``[BG_COLOR]`` substituted.
    Returns an empty entry and empty directive for unknown styles.
    """
    with open(styles_yml) as f:
        data = yaml.safe_load(f)
    entry = {s["id"]: s for s in data.get("styles", [])}.get(style_name, {})
    directive = build_style_directive(entry, bg_color)
    return entry, directive
