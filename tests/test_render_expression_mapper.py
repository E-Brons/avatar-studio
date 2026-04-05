"""Tests for programmatic expression mapper."""

from pipeline.render.programmatic.expression_mapper import (
    SUPPORTED_EXPRESSIONS,
    SUPPORTED_STYLES,
    get_expression_options,
)


class TestGetExpressionOptions:
    def test_known_style_and_expression(self):
        opts = get_expression_options("toon-head", "happiness")
        assert opts is not None
        assert isinstance(opts, dict)

    def test_unknown_style_returns_none(self):
        assert get_expression_options("nonexistent_style", "happiness") is None

    def test_unknown_expression_returns_none(self):
        assert get_expression_options("toon-head", "nonexistent_expression") is None

    def test_case_insensitive_expression(self):
        opts = get_expression_options("toon-head", "Happiness")
        assert opts is not None

    def test_all_supported_styles(self):
        for style in SUPPORTED_STYLES:
            for expr in SUPPORTED_EXPRESSIONS:
                opts = get_expression_options(style, expr)
                # All defined combos must return a dict
                assert opts is not None, f"Missing: {style}/{expr}"

    def test_supported_styles_not_empty(self):
        assert len(SUPPORTED_STYLES) > 0

    def test_supported_expressions_not_empty(self):
        assert len(SUPPORTED_EXPRESSIONS) > 0
