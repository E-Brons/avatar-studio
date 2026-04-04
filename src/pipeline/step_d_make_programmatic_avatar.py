"""Stage D — Programmatic Avatar (PA) generator (multi-style, vendored Node sub-project).

Calls the Node.js wrapper in ``vendor/programmatic-avatar/generate.js`` via subprocess
and writes the resulting SVG to ``out_path``.

Attribution (CC BY 4.0)
-----------------------
  "Custom Avatar" art by Johan Melin (toon-head), Pablo Stanley (avataaars),
  Micah Lanier (avatar-illustration-system / micah),
  DiceBear contributors (bottts).
  Rendered by DiceBear (https://dicebear.com) — licensed under CC BY 4.0.
  © 2026 MyBoard & Elkana Bronstein — remix permitted with attribution.

Styles
------
  toon-head  (default) @dicebear/toon-head
  avataaars            @dicebear/avataaars
  bottts               @dicebear/bottts
  micah                @dicebear/micah
  opeeps               @opeepsfun/avatar-illustration-system

Expression mapping
------------------
See docs/plans/2026-04-04-programmatic-avatar.md
"""

import json
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Maps canonical expression names (lower-cased) to DiceBear/AIS options per style.
EXPRESSION_OPTIONS: dict[str, dict[str, dict]] = {
    "toon-head": {
        "neutral":   {"eyes": ["humble"],  "mouth": ["smile"],  "eyebrows": ["neutral"]},
        "happiness": {"eyes": ["happy"],   "mouth": ["laugh"],  "eyebrows": ["happy"]},
        "surprise":  {"eyes": ["wide"],    "mouth": ["agape"],  "eyebrows": ["raised"]},
        "anger":     {"eyes": ["bow"],     "mouth": ["angry"],  "eyebrows": ["angry"]},
        "sadness":   {"eyes": ["humble"],  "mouth": ["sad"],    "eyebrows": ["sad"]},
        "contempt":  {"eyes": ["wink"],    "mouth": ["smile"],  "eyebrows": ["neutral"]},
    },
    "avataaars": {
        "neutral":   {"eyes": ["default"],   "mouth": ["default"],    "eyebrows": ["default"]},
        "happiness": {"eyes": ["happy"],     "mouth": ["smile"],      "eyebrows": ["raisedExcited"]},
        "surprise":  {"eyes": ["surprised"], "mouth": ["screamOpen"], "eyebrows": ["raisedExcitedNatural"]},
        "anger":     {"eyes": ["squint"],    "mouth": ["grimace"],    "eyebrows": ["angryNatural"]},
        "sadness":   {"eyes": ["cry"],       "mouth": ["sad"],        "eyebrows": ["sadConcernedNatural"]},
        "contempt":  {"eyes": ["side"],      "mouth": ["serious"],    "eyebrows": ["upDown"]},
    },
    "bottts": {
        "neutral":   {"eyes": ["sensor"],  "mouth": ["smile01"]},
        "happiness": {"eyes": ["happy"],   "mouth": ["smile02"]},
        "surprise":  {"eyes": ["bulging"], "mouth": ["bite"]},
        "anger":     {"eyes": ["robocop"], "mouth": ["grill01"]},
        "sadness":   {"eyes": ["shade01"], "mouth": ["diagram"]},
        "contempt":  {"eyes": ["eva"],     "mouth": ["grill02"]},
    },
    "micah": {
        "neutral":   {"eyes": ["eyes"],         "mouth": ["smile"],     "eyebrows": ["up"]},
        "happiness": {"eyes": ["smiling"],      "mouth": ["laughing"],  "eyebrows": ["eyelashesUp"]},
        "surprise":  {"eyes": ["round"],        "mouth": ["surprised"], "eyebrows": ["up"]},
        "anger":     {"eyes": ["eyesShadow"],   "mouth": ["frown"],     "eyebrows": ["down"]},
        "sadness":   {"eyes": ["eyesShadow"],   "mouth": ["sad"],       "eyebrows": ["eyelashesDown"]},
        "contempt":  {"eyes": ["smilingShadow"],"mouth": ["smirk"],     "eyebrows": ["eyelashesDown"]},
    },
    "opeeps": {
        "neutral":   {"eye": "Round",         "mouth": "Smile",     "eyebrow": "Up"},
        "happiness": {"eye": "Smiling",       "mouth": "Laughing",  "eyebrow": "EyelashesUp"},
        "surprise":  {"eye": "Round",         "mouth": "Surprised", "eyebrow": "Up"},
        "anger":     {"eye": "Ellipse",       "mouth": "Frown",     "eyebrow": "Down"},
        "sadness":   {"eye": "EllipseShadow", "mouth": "Sad",       "eyebrow": "Down"},
        "contempt":  {"eye": "Round",         "mouth": "Smirk",     "eyebrow": "EyelashesUp"},
    },
}


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
        Optional demographics dict from Step A.  When provided, the
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
        "[Step D] START — make_programmatic_avatar (name=%s, style=%s, expression=%s)",
        name, style, expression,
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
                "[Step D] Unknown expression %r for style %r — skipping. Known: %s",
                expression, style, ", ".join(style_map),
            )

    cmd = [
        "node",
        str(generate_js),
        "--seed", name,
        "--style", style,
        "--size", str(size),
        "--out", str(out_path),
    ]
    if options:
        cmd += ["--options", json.dumps(options)]

    out_path.parent.mkdir(parents=True, exist_ok=True)

    logger.debug("[Step D] cmd: %s", " ".join(cmd))
    result = subprocess.run(
        cmd,
        check=True,
        capture_output=True,
        text=True,
        cwd=str(vendor),
    )
    if result.stderr:
        logger.debug("[Step D] stderr: %s", result.stderr.strip())

    logger.info("[Step D] DONE  — %s", out_path)
    return out_path
