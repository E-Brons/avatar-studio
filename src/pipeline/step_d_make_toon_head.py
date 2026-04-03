"""Stage D — ToonHead avatar generator (DiceBear big-smile, vendored Node sub-project).

Calls the Node.js wrapper in ``vendor/toon-head/generate.js`` via subprocess
and writes the resulting SVG to ``out_path``.

Attribution (CC BY 4.0)
-----------------------
  "Custom Avatar" art by Ashley Seo (https://www.figma.com/community/file/881358461963645496)
  Rendered by DiceBear (https://dicebear.com) — licensed under CC BY 4.0.
  © 2026 MyBoard & Elkana Bronstein — remix permitted with attribution.
"""

import json
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Resolved once at import time so callers don't have to know the repo layout.
_VENDOR_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent / "vendor" / "toon-head"
_GENERATE_JS = _VENDOR_DIR / "generate.js"


def _vendor_dir() -> Path:
    """Return the vendor/toon-head directory, searching upward from this file."""
    candidate = Path(__file__).resolve()
    for _ in range(8):
        candidate = candidate.parent
        gen = candidate / "vendor" / "toon-head" / "generate.js"
        if gen.exists():
            return gen.parent
    raise FileNotFoundError(
        "vendor/toon-head/generate.js not found. "
        "Run 'npm ci' inside vendor/toon-head/ to install dependencies."
    )


def create_toon_head_avatar(
    name: str,
    out_path: Path,
    size: int = 256,
    demographics: dict | None = None,
) -> Path:
    """Generate a ToonHead SVG avatar and write it to *out_path*.

    Parameters
    ----------
    name:
        Full name of the person — used as the DiceBear seed so the same
        name always produces the same avatar.
    out_path:
        Destination ``.svg`` file.  Parent directories are created if
        they do not exist.
    size:
        Pixel dimensions of the rendered SVG canvas (width = height).
    demographics:
        Optional demographics dict from Step A.  When provided, the
        following fields are forwarded to DiceBear as style options:

        ============  ========================
        demographics  DiceBear option
        ============  ========================
        bg_color      backgroundColor (array)
        ============  ========================

    Returns
    -------
    Path
        *out_path* after the file has been written.

    Raises
    ------
    FileNotFoundError
        If ``vendor/toon-head/generate.js`` cannot be located.
    subprocess.CalledProcessError
        If the Node.js process exits with a non-zero status.
    """
    logger.info("[Step D] START — make_toon_head (name=%s)", name)

    try:
        vendor = _vendor_dir()
    except FileNotFoundError:
        raise

    generate_js = vendor / "generate.js"

    # Build DiceBear option overrides from demographics.
    options: dict = {}
    if demographics:
        bg = demographics.get("bg_color", "")
        if bg:
            # DiceBear expects hex values without the leading '#'.
            options["backgroundColor"] = [bg.lstrip("#")]

    cmd = [
        "node",
        str(generate_js),
        "--seed",
        name,
        "--size",
        str(size),
        "--out",
        str(out_path),
    ]
    if options:
        cmd += ["--options", json.dumps(options)]

    out_path.parent.mkdir(parents=True, exist_ok=True)

    logger.debug("[Step D] toon_head cmd: %s", " ".join(cmd))
    result = subprocess.run(
        cmd,
        check=True,
        capture_output=True,
        text=True,
        cwd=str(vendor),
    )
    if result.stderr:
        logger.debug("[Step D] toon_head stderr: %s", result.stderr.strip())

    logger.info("[Step D] DONE  — toon_head %s", out_path)
    return out_path
