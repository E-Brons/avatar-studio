"""Expression mapper — look up DiceBear/AIS component options per (style, expression)."""

from __future__ import annotations

from pipeline.step_d_make_programmatic_avatar import EXPRESSION_OPTIONS

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
