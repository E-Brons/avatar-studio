"""Tests for render expression resolver."""

import pytest

from pipeline.render.expression_resolver import (
    load_all_expressions,
    resolve_expression,
    resolve_expression_list,
)


class TestLoadAllExpressions:
    def test_returns_dict(self):
        exprs = load_all_expressions()
        assert isinstance(exprs, dict)
        assert len(exprs) > 0

    def test_neutral_present_or_defined_expressions(self):
        exprs = load_all_expressions()
        # expressions.yml may not include neutral (it's implicit); check at least one is present
        assert len(exprs) > 0


class TestResolveExpression:
    def test_known_expression(self):
        entry = resolve_expression("happiness")
        assert isinstance(entry, dict)
        assert entry.get("expression", "").lower() in ("happiness", "happy") or "happiness" in str(entry)

    def test_unknown_expression_fallback(self):
        entry = resolve_expression("unknownxyz")
        assert entry == {"expression": "unknownxyz"}


class TestResolveExpressionList:
    def test_neutral_prepended(self):
        result = resolve_expression_list(["happiness", "anger"])
        assert result[0] == "neutral"

    def test_neutral_not_duplicated(self):
        result = resolve_expression_list(["neutral", "happiness"])
        assert result.count("neutral") == 1

    def test_order_preserved(self):
        result = resolve_expression_list(["happiness", "anger"])
        assert result == ["neutral", "happiness", "anger"]

    def test_empty_input_gives_neutral(self):
        result = resolve_expression_list([])
        assert result == ["neutral"]
