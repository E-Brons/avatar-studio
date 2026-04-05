"""Tests for pure persona aggregator functions."""

import random

import pytest

from pipeline.persona.aggregators import (
    fallthrough,
    pool_by_gender,
    random_from_list,
    random_from_probability,
    random_from_range,
    random_from_range_color,
)


def test_fallthrough_string():
    assert fallthrough("hello") == "hello"


def test_fallthrough_none():
    assert fallthrough(None) is None


def test_fallthrough_dict():
    d = {"a": 1}
    assert fallthrough(d) is d


def test_random_from_list_seeded():
    rng = random.Random(42)
    pool = ["a", "b", "c"]
    result = random_from_list(pool, rng)
    assert result in pool


def test_random_from_list_deterministic():
    rng1 = random.Random(99)
    rng2 = random.Random(99)
    pool = ["x", "y", "z"]
    assert random_from_list(pool, rng1) == random_from_list(pool, rng2)


def test_random_from_list_empty_raises():
    with pytest.raises(ValueError, match="empty"):
        random_from_list([], random.Random(1))


def test_random_from_range_in_bounds():
    rng = random.Random(0)
    for _ in range(50):
        v = random_from_range(10, 20, rng)
        assert 10 <= v <= 20


def test_random_from_range_deterministic():
    assert random_from_range(1, 100, random.Random(7)) == random_from_range(1, 100, random.Random(7))


def test_random_from_range_color_valid_hex():
    result = random_from_range_color("#8B5E3C", "#5C3D1E", random.Random(42))
    assert result.startswith("#")
    assert len(result) == 7


def test_random_from_range_color_deterministic():
    assert (
        random_from_range_color("#AABBCC", "#001122", random.Random(7))
        == random_from_range_color("#AABBCC", "#001122", random.Random(7))
    )


def test_random_from_range_color_within_ycbcr_range():
    """Sampled colors must lie within the YCbCr corridor of the two endpoints (±2% tolerance)."""

    def _hex_to_ycbcr(h: str) -> tuple[float, float, float]:
        h = h.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        y  =  0.299 * r + 0.587 * g + 0.114 * b
        cb = -0.168736 * r - 0.331264 * g + 0.5 * b + 128
        cr =  0.5 * r - 0.418688 * g - 0.081312 * b + 128
        return y, cb, cr

    min_hex, max_hex = "#8B5E3C", "#5C3D1E"
    y1, cb1, cr1 = _hex_to_ycbcr(min_hex)
    y2, cb2, cr2 = _hex_to_ycbcr(max_hex)
    tol = 0.02 * 255  # 2% of full channel range

    rng = random.Random(0)
    for _ in range(200):
        result = random_from_range_color(min_hex, max_hex, rng)
        ry, rcb, rcr = _hex_to_ycbcr(result)
        assert min(y1, y2) - tol <= ry  <= max(y1, y2) + tol, f"Y out of range: {ry}"
        assert min(cb1, cb2) - tol <= rcb <= max(cb1, cb2) + tol, f"Cb out of range: {rcb}"
        assert min(cr1, cr2) - tol <= rcr <= max(cr1, cr2) + tol, f"Cr out of range: {rcr}"


def test_random_from_probability_seeded():
    rng = random.Random(5)
    result = random_from_probability(["a", "b", "c"], [1.0, 0.0, 0.0], rng)
    assert result == "a"


def test_random_from_probability_weights_mismatch():
    with pytest.raises(ValueError):
        random_from_probability(["a", "b"], [1.0], random.Random(1))


class TestPoolByGender:
    _DICT = {
        "male": ["M1", "M2"],
        "female": ["F1"],
        "neutral": ["N1", "N2"],
    }

    def test_list_passthrough(self):
        lst = ["x", "y"]
        assert pool_by_gender(lst, "male") == lst

    def test_male_default(self):
        result = pool_by_gender(self._DICT, "male")
        assert set(result) == {"M1", "M2", "N1", "N2"}

    def test_female_default(self):
        result = pool_by_gender(self._DICT, "female")
        assert set(result) == {"F1", "N1", "N2"}

    def test_nonbinary_default(self):
        result = pool_by_gender(self._DICT, "non-binary")
        assert set(result) == {"M1", "M2", "F1", "N1", "N2"}

    def test_male_hardtype(self):
        result = pool_by_gender(self._DICT, "male", hard_type=True)
        assert set(result) == {"M1", "M2"}

    def test_female_hardtype(self):
        result = pool_by_gender(self._DICT, "female", hard_type=True)
        assert set(result) == {"F1"}

    def test_nonbinary_hardtype(self):
        result = pool_by_gender(self._DICT, "non-binary", hard_type=True)
        assert set(result) == {"N1", "N2"}
