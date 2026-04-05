"""SVG generator — create programmatic avatar SVGs via the vendored Node sub-project."""

from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path

import cairosvg

from pipeline.render.programmatic.expression_mapper import EXPRESSION_OPTIONS

logger = logging.getLogger(__name__)


def _vendor_dir() -> Path:
    """Return the vendor/programmatic-avatar directory, searching upward from this file."""
    candidate = Path(__file__).resolve()
    for _ in range(8):
        candidate = candidate.parent
        gen = candidate / "vendor" / "programmatic-avatar" / "generate.js"
        if gen.exists():
            return gen.parent
    raise FileNotFoundError(
        "vendor/programmatic-avatar/generate.js not found. "
        "Run 'npm ci' inside vendor/programmatic-avatar/ to install dependencies."
    )


def create_programmatic_avatar(
    name: str,
    out_path: Path,
    size: int = 256,
    demographics: dict | None = None,
    expression: str | None = None,
    style: str = "toon-head",
) -> Path:
    """Generate a Programmatic Avatar (PA) SVG and write it to *out_path*.

    Parameters
    ----------
    name:
        Full name of the person — used as the DiceBear seed so the same
        name always produces the same avatar.  Ignored for ``opeeps`` style
        (no seed support).
    out_path:
        Destination ``.svg`` file.  Parent directories are created if
        they do not exist.
    size:
        Pixel dimensions of the rendered SVG canvas (width = height).
    demographics:
        Optional demographics dict.  When provided, the
        following fields are forwarded as style options:

        ============  ========================
        demographics  option
        ============  ========================
        bg_color      backgroundColor (DiceBear) / circle.backgroundColor (opeeps)
        ============  ========================
    expression:
        Optional canonical expression name (case-insensitive).  When
        provided, the eyes/mouth/eyebrows options are pinned to the
        closest available variants for the selected style according to
        :data:`EXPRESSION_OPTIONS`.
    style:
        Avatar style: ``"toon-head"`` (default), ``"avataaars"``,
        ``"bottts"``, ``"micah"``, or ``"opeeps"``.

    Returns
    -------
    Path
        *out_path* after the file has been written.
    """
    logger.info(
        "START — make_programmatic_avatar (name=%s, style=%s, expression=%s)",
        name,
        style,
        expression,
    )

    vendor = _vendor_dir()
    generate_js = vendor / "generate.js"

    # Build option overrides from demographics.
    options: dict = {}
    if demographics:
        bg = demographics.get("bg_color", "")
        if bg:
            hex_val = bg.lstrip("#")
            if style == "opeeps":
                options["circle"] = {"backgroundColor": f"#{hex_val}"}
            else:
                options["backgroundColor"] = [hex_val]

    # Apply expression-specific overrides.
    if expression is not None:
        key = expression.lower()
        style_map = EXPRESSION_OPTIONS.get(style, {})
        expr_opts = style_map.get(key)
        if expr_opts:
            options.update(expr_opts)
        else:
            logger.warning(
                "Unknown expression %r for style %r — skipping. Known: %s",
                expression,
                style,
                ", ".join(style_map),
            )

    cmd = [
        "node",
        str(generate_js),
        "--seed",
        name,
        "--style",
        style,
        "--size",
        str(size),
        "--out",
        str(out_path),
    ]
    if options:
        cmd += ["--options", json.dumps(options)]

    out_path.parent.mkdir(parents=True, exist_ok=True)

    logger.debug("cmd: %s", " ".join(cmd))
    result = subprocess.run(
        cmd,
        check=True,
        capture_output=True,
        text=True,
        cwd=str(vendor),
    )
    if result.stderr:
        logger.debug("stderr: %s", result.stderr.strip())

    logger.info("DONE  — %s", out_path)
    return out_path


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


def svg_to_png(svg_bytes: bytes, out_path: Path) -> None:
    """Render an SVG to a PNG at native viewBox resolution.

    Works around a cairosvg bug where it ignores the viewBox→viewport transform,
    rendering 1 SVG coordinate unit = 1 pixel.  We patch the SVG's width/height
    to match its viewBox so the full image is produced at native resolution.
    """
    text = svg_bytes.decode()
    m = re.search(r'viewBox="0 0 (\d+) (\d+)"', text)
    if m:
        vw, vh = m.group(1), m.group(2)
        text = re.sub(r'\bwidth="\d+"', f'width="{vw}"', text, count=1)
        text = re.sub(r'\bheight="\d+"', f'height="{vh}"', text, count=1)
        svg_bytes = text.encode()
    cairosvg.svg2png(bytestring=svg_bytes, write_to=str(out_path))
