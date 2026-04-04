"""Programmatic avatar orchestrator — generates one SVG per expression."""

from __future__ import annotations

import logging
from pathlib import Path

from pipeline.render.programmatic.svg_generator import generate_svg

logger = logging.getLogger(__name__)


def render_programmatic(
    name: str,
    out_dir: Path,
    slug: str,
    expressions: list[str],
    *,
    style: str = "toon-head",
    size: int = 256,
    demographics: dict | None = None,
) -> dict[str, str | None]:
    """Generate one SVG per expression and return expression → filename map."""
    results: dict[str, str | None] = {}
    for expr in expressions:
        filename = f"{slug}-pa-{expr}.svg"
        out_path = out_dir / filename
        try:
            generate_svg(
                name,
                out_path,
                style=style,
                expression=expr,
                size=size,
                demographics=demographics,
            )
            results[expr] = filename
        except Exception as exc:
            logger.warning("[render_programmatic] %s/%s failed: %s", style, expr, exc)
            results[expr] = None
    return results
