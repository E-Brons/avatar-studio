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


def test_random_from_range_color():
    from config.config import _darken_hex

    result = random_from_range_color("#AABBCC", 0.5, _darken_hex)
    assert result.startswith("#")
    assert len(result) == 7


def test_random_from_range_color_pair():
    from config.config import _darken_hex

    result = random_from_range_color("#AABBCC #001122", 0.7, _darken_hex)
    assert result.startswith("#")


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
