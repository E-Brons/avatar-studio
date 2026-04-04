"""SVG generator — thin wrapper around create_programmatic_avatar."""

from __future__ import annotations

from pathlib import Path

from pipeline.step_d_make_programmatic_avatar import create_programmatic_avatar


def generate_svg(
    name: str,
    out_path: Path,
    *,
    style: str = "toon-head",
    expression: str | None = None,
    size: int = 256,
    demographics: dict | None = None,
) -> Path:
    """Generate a programmatic avatar SVG and write it to *out_path*."""
    return create_programmatic_avatar(
        name,
        out_path,
        size=size,
        demographics=demographics,
        expression=expression,
        style=style,
    )
