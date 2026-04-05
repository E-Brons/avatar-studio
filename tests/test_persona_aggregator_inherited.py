"""Tests for aggregator_inherited.from_inherited."""

import random

from pipeline.persona.aggregator_inherited import from_inherited

_BROWS = {
    "male": ["straight thick", "bushy natural"],
    "female": ["arched dramatic", "pencil thin"],
    "neutral": ["natural"],
}


class TestFromInherited:
    def test_picks_from_male_pool(self):
        rng = random.Random(0)
        result = from_inherited("BROWS_STYLE", _BROWS, {"gender": "male"}, rng)
        assert result in ["straight thick", "bushy natural", "natural"]

    def test_picks_from_female_pool(self):
        rng = random.Random(0)
        result = from_inherited("BROWS_STYLE", _BROWS, {"gender": "female"}, rng)
        assert result in ["arched dramatic", "pencil thin", "natural"]

    def test_list_source_uses_as_is(self):
        rng = random.Random(7)
        pool = ["opt_a", "opt_b", "opt_c"]
        result = from_inherited("foo", pool, {"gender": "male"}, rng)
        assert result in pool

    def test_hard_type_restricts_to_gender_only(self):
        rng = random.Random(0)
        result = from_inherited("BROWS_STYLE", _BROWS, {"gender": "male"}, rng, hard_type=True)
        assert result in ["straight thick", "bushy natural"]
        assert result not in ["natural"]

    def test_deterministic_with_seed(self):
        r1 = from_inherited("x", ["a", "b", "c"], {"gender": "male"}, random.Random(42))
        r2 = from_inherited("x", ["a", "b", "c"], {"gender": "male"}, random.Random(42))
        assert r1 == r2

    def test_missing_gender_falls_back(self):
        # No gender key — pool_by_gender for "" will include all buckets
        rng = random.Random(1)
        result = from_inherited("BROWS_STYLE", _BROWS, {}, rng)
        all_options = _BROWS["male"] + _BROWS["female"] + _BROWS["neutral"]
        assert result in all_options
