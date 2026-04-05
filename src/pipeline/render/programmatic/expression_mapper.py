"""Expression mapper — look up DiceBear/AIS component options per (style, expression)."""

from __future__ import annotations

# Maps canonical expression names (lower-cased) to DiceBear/AIS options per style.
EXPRESSION_OPTIONS: dict[str, dict[str, dict]] = {
    "toon-head": {
        "neutral": {"eyes": ["humble"], "mouth": ["smile"], "eyebrows": ["neutral"]},
        "happiness": {"eyes": ["happy"], "mouth": ["laugh"], "eyebrows": ["happy"]},
        "surprise": {"eyes": ["wide"], "mouth": ["agape"], "eyebrows": ["raised"]},
        "anger": {"eyes": ["bow"], "mouth": ["angry"], "eyebrows": ["angry"]},
        "sadness": {"eyes": ["humble"], "mouth": ["sad"], "eyebrows": ["sad"]},
        "contempt": {"eyes": ["wink"], "mouth": ["smile"], "eyebrows": ["neutral"]},
    },
    "avataaars": {
        "neutral": {"eyes": ["default"], "mouth": ["default"], "eyebrows": ["default"]},
        "happiness": {"eyes": ["happy"], "mouth": ["smile"], "eyebrows": ["raisedExcited"]},
        "surprise": {
            "eyes": ["surprised"],
            "mouth": ["screamOpen"],
            "eyebrows": ["raisedExcitedNatural"],
        },
        "anger": {"eyes": ["squint"], "mouth": ["grimace"], "eyebrows": ["angryNatural"]},
        "sadness": {"eyes": ["cry"], "mouth": ["sad"], "eyebrows": ["sadConcernedNatural"]},
        "contempt": {"eyes": ["side"], "mouth": ["serious"], "eyebrows": ["upDown"]},
    },
    "bottts": {
        "neutral": {"eyes": ["sensor"], "mouth": ["smile01"]},
        "happiness": {"eyes": ["happy"], "mouth": ["smile02"]},
        "surprise": {"eyes": ["bulging"], "mouth": ["bite"]},
        "anger": {"eyes": ["robocop"], "mouth": ["grill01"]},
        "sadness": {"eyes": ["shade01"], "mouth": ["diagram"]},
        "contempt": {"eyes": ["eva"], "mouth": ["grill02"]},
    },
    "micah": {
        "neutral": {"eyes": ["eyes"], "mouth": ["smile"], "eyebrows": ["up"]},
        "happiness": {"eyes": ["smiling"], "mouth": ["laughing"], "eyebrows": ["eyelashesUp"]},
        "surprise": {"eyes": ["round"], "mouth": ["surprised"], "eyebrows": ["up"]},
        "anger": {"eyes": ["eyesShadow"], "mouth": ["frown"], "eyebrows": ["down"]},
        "sadness": {"eyes": ["eyesShadow"], "mouth": ["sad"], "eyebrows": ["eyelashesDown"]},
        "contempt": {"eyes": ["smilingShadow"], "mouth": ["smirk"], "eyebrows": ["eyelashesDown"]},
    },
    "opeeps": {
        "neutral": {"eye": "Round", "mouth": "Smile", "eyebrow": "Up"},
        "happiness": {"eye": "Smiling", "mouth": "Laughing", "eyebrow": "EyelashesUp"},
        "surprise": {"eye": "Round", "mouth": "Surprised", "eyebrow": "Up"},
        "anger": {"eye": "Ellipse", "mouth": "Frown", "eyebrow": "Down"},
        "sadness": {"eye": "EllipseShadow", "mouth": "Sad", "eyebrow": "Down"},
        "contempt": {"eye": "Round", "mouth": "Smirk", "eyebrow": "EyelashesUp"},
    },
}

SUPPORTED_STYLES = list(EXPRESSION_OPTIONS.keys())
SUPPORTED_EXPRESSIONS = list(next(iter(EXPRESSION_OPTIONS.values())).keys())


def get_expression_options(style: str, expression: str) -> dict | None:
    """Return the component override dict for *(style, expression)*.

    Returns ``None`` when the combination is unknown.
    """
    style_map = EXPRESSION_OPTIONS.get(style)
    if style_map is None:
        return None
    return style_map.get(expression.lower())
