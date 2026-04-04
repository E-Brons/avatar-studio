"""SVG to PNG converter using cairosvg."""

from __future__ import annotations

from pathlib import Path


def svg_to_png(svg_path: Path, out_path: Path, *, size: int = 256) -> Path:
    """Convert an SVG file to a PNG using cairosvg."""
    try:
        import cairosvg
    except ImportError as exc:
        raise ImportError(
            "cairosvg is required for SVG→PNG conversion. "
            "Install it with: pip install cairosvg"
        ) from exc

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cairosvg.svg2png(
        url=str(svg_path),
        write_to=str(out_path),
        output_width=size,
        output_height=size,
    )
    return out_path
