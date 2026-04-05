"""Tests for persona request pipeline — normalize, validate, identify, parse."""

import random

import pytest

from pipeline.persona.request import (
    identify_explicits,
    identify_missing,
    normalize_input,
    parse_selectors,
    validate_input,
)
from pipeline.persona.schema import get_schema

# ---------------------------------------------------------------------------
# normalize_input
# ---------------------------------------------------------------------------


class TestNormalizeInput:
    def test_dict_passthrough(self):
        d = {"gender": "male"}
        assert normalize_input(d) is d

    def test_reads_yaml_file(self, tmp_path):
        p = tmp_path / "req.yml"
        p.write_text("gender: female\nage: 30\n")
        result = normalize_input(p)
        assert result == {"gender": "female", "age": 30}

    def test_reads_path_string(self, tmp_path):
        p = tmp_path / "req.yml"
        p.write_text("gender: male\n")
        result = normalize_input(str(p))
        assert result["gender"] == "male"

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            normalize_input(tmp_path / "nonexistent.yml")


# ---------------------------------------------------------------------------
# validate_input
# ---------------------------------------------------------------------------


class TestValidateInput:
    def test_empty_request_is_valid(self):
        errors = validate_input({})
        assert errors == []

    def test_known_key_is_valid(self):
        errors = validate_input({"gender": "male"})
        assert errors == []

    def test_unknown_key_produces_error(self):
        errors = validate_input({"totally_unknown_key_xyz": "value"})
        assert any("totally_unknown_key_xyz" in e for e in errors)

    def test_valid_selector_type_accepted(self):
        schema = get_schema()
        valid_selector = schema.valid_selector_types("gender")[0]
        errors = validate_input({"gender": {"selector": valid_selector, "value": []}})
        assert errors == []

    def test_invalid_selector_type_rejected(self):
        errors = validate_input({"gender": {"selector": "from_llm", "value": []}})
        assert any("from_llm" in e for e in errors)


# ---------------------------------------------------------------------------
# identify_missing
# ---------------------------------------------------------------------------


class TestIdentifyMissing:
    def test_missing_attrs_injected(self):
        result = identify_missing({})
        schema = get_schema()
        for key in schema.keys():
            assert key in result

    def test_existing_key_not_overwritten(self):
        result = identify_missing({"gender": "female"})
        assert result["gender"] == "female"

    def test_injected_has_selector(self):
        result = identify_missing({})
        for key, val in result.items():
            if isinstance(val, dict):
                assert "selector" in val


# ---------------------------------------------------------------------------
# identify_explicits
# ---------------------------------------------------------------------------


class TestIdentifyExplicits:
    def test_plain_value_is_explicit(self):
        explicits, selectors = identify_explicits({"gender": "male"})
        assert "gender" in explicits
        assert "gender" not in selectors

    def test_selector_dict_goes_to_selectors(self):
        req = {"gender": {"selector": "random_from_list", "value": ["male", "female"]}}
        explicits, selectors = identify_explicits(req)
        assert "gender" not in explicits
        assert "gender" in selectors

    def test_mixed_split_correctly(self):
        req = {
            "gender": "male",
            "age": {"selector": "random_from_range", "value": [25, 70]},
        }
        explicits, selectors = identify_explicits(req)
        assert "gender" in explicits
        assert "age" in selectors

    def test_empty_input(self):
        explicits, selectors = identify_explicits({})
        assert explicits == {}
        assert selectors == {}


# ---------------------------------------------------------------------------
# parse_selectors
# ---------------------------------------------------------------------------


class TestParseSelectors:
    _RNG = random.Random(42)

    def test_fallthrough(self):
        result = parse_selectors(
            {"style": {"selector": "fallthrough", "value": "photorealistic"}},
            {},
            rng=random.Random(1),
        )
        assert result["style"] == "photorealistic"

    def test_random_from_list(self):
        result = parse_selectors(
            {"gender": {"selector": "random_from_list", "value": "genders"}},
            {},
            rng=random.Random(0),
        )
        assert result["gender"] in ["male", "female", "non-binary"]

    def test_random_from_range(self):
        result = parse_selectors(
            {"age": {"selector": "random_from_range", "value": [20, 30]}},
            {},
            rng=random.Random(5),
        )
        assert 20 <= result["age"] <= 30

    def test_random_from_range_color(self):
        result = parse_selectors(
            {
                "BROWS_COLOR": {
                    "selector": "random_from_range_color",
                    "value": {"source": "HAIR_COLOR"},
                }
            },
            {"HAIR_COLOR": "#8B5E3C #5C3D1E"},
            rng=random.Random(1),
        )
        assert result["BROWS_COLOR"].startswith("#")
        assert len(result["BROWS_COLOR"]) == 7

    def test_random_from_range_color_within_ycbcr_range(self):
        """BROWS_COLOR sampled via parse_selectors stays within the HAIR_COLOR YCbCr corridor (±2%)."""

        def _hex_to_ycbcr(h: str) -> tuple[float, float, float]:
            h = h.lstrip("#")
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            y  =  0.299 * r + 0.587 * g + 0.114 * b
            cb = -0.168736 * r - 0.331264 * g + 0.5 * b + 128
            cr =  0.5 * r - 0.418688 * g - 0.081312 * b + 128
            return y, cb, cr

        hair = "#8B5E3C #5C3D1E"
        min_hex, max_hex = hair.split()
        y1, cb1, cr1 = _hex_to_ycbcr(min_hex)
        y2, cb2, cr2 = _hex_to_ycbcr(max_hex)
        tol = 0.02 * 255

        selectors = {
            "BROWS_COLOR": {
                "selector": "random_from_range_color",
                "value": {"source": "HAIR_COLOR"},
            }
        }
        rng = random.Random(0)
        for _ in range(200):
            result = parse_selectors(selectors, {"HAIR_COLOR": hair}, rng=rng)
            ry, rcb, rcr = _hex_to_ycbcr(result["BROWS_COLOR"])
            assert min(y1, y2) - tol <= ry  <= max(y1, y2) + tol, f"Y out of range: {ry}"
            assert min(cb1, cb2) - tol <= rcb <= max(cb1, cb2) + tol, f"Cb out of range: {rcb}"
            assert min(cr1, cr2) - tol <= rcr <= max(cr1, cr2) + tol, f"Cr out of range: {rcr}"

    def test_from_inherited_uses_gender(self):
        result = parse_selectors(
            {"BROWS_STYLE": {"selector": "from_inherited", "value": "brows_styles"}},
            {"gender": "male"},
            rng=random.Random(3),
        )
        assert result["BROWS_STYLE"] is not None

    def test_unknown_selector_returns_none(self):
        result = parse_selectors(
            {"foo": {"selector": "totally_unknown_selector", "value": None}},
            {},
            rng=random.Random(1),
        )
        assert result["foo"] is None

    def test_deterministic_with_seeded_rng(self):
        spec = {"gender": {"selector": "random_from_list", "value": "genders"}}
        r1 = parse_selectors(spec, {}, rng=random.Random(99))
        r2 = parse_selectors(spec, {}, rng=random.Random(99))
        assert r1 == r2

    def test_default_rng_used_when_none(self):
        """Covers the `if rng is None: rng = _random.Random()` branch."""
        result = parse_selectors(
            {"gender": {"selector": "random_from_list", "value": "genders"}},
            {},
            # no rng kwarg
        )
        assert result["gender"] in ["male", "female", "non-binary"]

    def test_random_from_probability(self):
        result = parse_selectors(
            {
                "style": {
                    "selector": "random_from_probability",
                    "value": {"options": ["a", "b"], "weights": [0.8, 0.2]},
                }
            },
            {},
            rng=random.Random(1),
        )
        assert result["style"] in ["a", "b"]

    def test_from_llm_returns_none(self):
        result = parse_selectors(
            {"style": {"selector": "from_llm", "value": ["opt1"]}},
            {},
            rng=random.Random(1),
        )
        assert result["style"] is None

    def test_missing_source_for_range_color_logs_warning(self):
        """Covers the `logger.warning` branch when source key is unresolved."""
        result = parse_selectors(
            {
                "BROWS_COLOR": {
                    "selector": "random_from_range_color",
                    "value": {"source": "HAIR_COLOR", "factor": 0.7},
                }
            },
            {},  # HAIR_COLOR not in resolved
            rng=random.Random(1),
        )
        # Returns nothing for that key (no KeyError)
        assert "BROWS_COLOR" not in result or result.get("BROWS_COLOR") is None

    def test_selector_error_sets_none(self):
        """Covers the exception handler — empty pool causes ValueError → result=None."""
        result = parse_selectors(
            {"gender": {"selector": "random_from_list", "value": []}},
            {},
            rng=random.Random(1),
        )
        assert result.get("gender") is None


# ---------------------------------------------------------------------------
# _resolve_pool
# ---------------------------------------------------------------------------


class TestResolvePool:
    def test_list_returned_as_is(self):
        from pipeline.persona.request import _resolve_pool

        assert _resolve_pool(["a", "b"], {}) == ["a", "b"]

    def test_unknown_str_returns_empty(self):
        from pipeline.persona.request import _resolve_pool

        assert _resolve_pool("nonexistent_key_xyz", {}) == []

    def test_non_list_non_str_returns_empty(self):
        from pipeline.persona.request import _resolve_pool

        assert _resolve_pool(None, {}) == []


# ---------------------------------------------------------------------------
# normalize_input — non-dict YAML raises ValueError
# ---------------------------------------------------------------------------


class TestNormalizeEdgeCases:
    def test_yaml_list_raises_value_error(self, tmp_path):
        p = tmp_path / "list.yml"
        p.write_text("- a\n- b\n")
        with pytest.raises(ValueError, match="expected dict"):
            normalize_input(p)
