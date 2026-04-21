"""Tests for pipeline/persona/ethnicity.py."""

from __future__ import annotations

import json
import random

import pytest
import yaml

from pipeline.persona.ethnicity import (
    all_ethnicity_ids,
    get_deepface_race_id,
    get_race_for_ethnicity,
    load_ethnicity_config,
    pick_ethnicity_from_nationality,
    pick_weighted_feature,
)
from pipeline.persona.skin_tones import load_skin_tones


class TestLoadEthnicityConfig:
    def test_has_required_top_level_keys(self):
        cfg = load_ethnicity_config()
        for key in ("races", "ethnicities", "nationality_map", "regional_defaults"):
            assert key in cfg, f"Missing top-level key: {key!r}"

    def test_races_count(self):
        cfg = load_ethnicity_config()
        assert len(cfg["races"]) == 7

    def test_races_have_deepface_race_id(self):
        cfg = load_ethnicity_config()
        for race_id, race in cfg["races"].items():
            assert "deepface_race_id" in race, f"Race '{race_id}' missing deepface_race_id"

    def test_ethnicities_count(self):
        cfg = load_ethnicity_config()
        assert len(cfg["ethnicities"]) >= 40, (
            f"Expected ≥40 ethnicities, got {len(cfg['ethnicities'])}"
        )

    def test_each_ethnicity_has_required_fields(self):
        cfg = load_ethnicity_config()
        required = {"label", "race", "skin_tones", "eye_shape_weights", "nose_shape_weights"}
        for eth_id, eth in cfg["ethnicities"].items():
            missing = required - eth.keys()
            assert not missing, f"Ethnicity '{eth_id}' missing: {missing}"

    def test_skin_tone_probs_sum_at_most_one(self):
        cfg = load_ethnicity_config()
        for eth_id, eth in cfg["ethnicities"].items():
            total = sum(eth["skin_tones"].values())
            assert total <= 1.01, f"Ethnicity '{eth_id}' skin_tones sum {total:.3f} > 1.0"

    def test_skin_ids_reference_valid_tones(self):
        cfg = load_ethnicity_config()
        valid_ids = set(load_skin_tones().keys())
        for eth_id, eth in cfg["ethnicities"].items():
            for sid in eth["skin_tones"]:
                assert sid in valid_ids, (
                    f"Ethnicity '{eth_id}' references unknown skin_tone_id: {sid!r}"
                )

    def test_eye_shape_weights_sum_at_most_one(self):
        cfg = load_ethnicity_config()
        for eth_id, eth in cfg["ethnicities"].items():
            total = sum(eth["eye_shape_weights"].values())
            assert total <= 1.01, f"Ethnicity '{eth_id}' eye_shape_weights sum {total:.3f} > 1.0"

    def test_nose_shape_weights_sum_at_most_one(self):
        cfg = load_ethnicity_config()
        for eth_id, eth in cfg["ethnicities"].items():
            total = sum(eth["nose_shape_weights"].values())
            assert total <= 1.01, f"Ethnicity '{eth_id}' nose_shape_weights sum {total:.3f} > 1.0"

    def test_race_references_valid(self):
        cfg = load_ethnicity_config()
        valid_races = set(cfg["races"].keys())
        for eth_id, eth in cfg["ethnicities"].items():
            r = eth["race"]
            assert r in valid_races, f"Ethnicity '{eth_id}' references unknown race: {r!r}"


class TestPickEthnicityFromNationality:
    def test_returns_valid_ethnicity_id(self):
        valid = set(all_ethnicity_ids())
        rng = random.Random(42)
        for nat in ("nigerian", "japanese", "french", "american", "brazilian"):
            result = pick_ethnicity_from_nationality(nat, rng)
            assert result in valid, f"Nationality '{nat}' → invalid ethnicity '{result}'"

    def test_deterministic_with_seed(self):
        e1 = pick_ethnicity_from_nationality("nigerian", random.Random(1))
        e2 = pick_ethnicity_from_nationality("nigerian", random.Random(1))
        assert e1 == e2

    def test_nigerian_resolves_to_west_african(self):
        # nigerian: {west_african: 1.0} — must always resolve to west_african
        for seed in range(10):
            result = pick_ethnicity_from_nationality("nigerian", random.Random(seed))
            assert result == "west_african"

    def test_japanese_resolves_to_japanese(self):
        for seed in range(10):
            result = pick_ethnicity_from_nationality("japanese", random.Random(seed))
            assert result == "japanese"

    def test_unknown_nationality_uses_universal_fallback(self):
        valid = set(all_ethnicity_ids())
        rng = random.Random(7)
        result = pick_ethnicity_from_nationality("__totally_unknown__", rng)
        assert result in valid

    def test_all_demographics_nationalities_resolve(self):
        """Every non-group nationality in demographics.yml must resolve to a valid ethnicity."""
        with open("assets/persona/demographics.yml") as f:
            demo = yaml.safe_load(f)

        valid = set(all_ethnicity_ids())
        rng = random.Random(0)
        for entry in demo["nationality"]:
            if not entry.get("group"):
                nat_id = entry["id"]
                result = pick_ethnicity_from_nationality(nat_id, rng)
                assert result in valid, (
                    f"Nationality '{nat_id}' resolved to invalid ethnicity '{result}'"
                )


class TestGetRaceForEthnicity:
    def test_known_ethnicity(self):
        assert get_race_for_ethnicity("scandinavian") == "white"
        assert get_race_for_ethnicity("west_african") == "black"
        assert get_race_for_ethnicity("han_chinese") == "east_asian"

    def test_unknown_raises_key_error(self):
        with pytest.raises(KeyError):
            get_race_for_ethnicity("__nonexistent__")


class TestGetDeepfaceRaceId:
    def test_known_ethnicities(self):
        assert get_deepface_race_id("scandinavian") == "white"
        assert get_deepface_race_id("west_african") == "black"
        assert get_deepface_race_id("korean") == "asian"
        assert get_deepface_race_id("north_indian") == "indian"
        assert get_deepface_race_id("levantine") == "middle eastern"
        assert get_deepface_race_id("mestizo") == "latino hispanic"


class TestPickWeightedFeature:
    def test_returns_valid_eye_shape(self):
        with open("assets/persona/phenotype_settings.json") as f:
            ps = json.load(f)
        valid = set(ps["eye_shapes"])
        rng = random.Random(42)
        for _ in range(20):
            result = pick_weighted_feature(
                "scandinavian", "eye_shape_weights", ps["eye_shapes"], rng
            )
            assert result in valid

    def test_returns_valid_nose_shape(self):
        with open("assets/persona/phenotype_settings.json") as f:
            ps = json.load(f)
        valid = set(ps["nose_shapes"])
        rng = random.Random(42)
        for _ in range(20):
            result = pick_weighted_feature(
                "west_african", "nose_shape_weights", ps["nose_shapes"], rng
            )
            assert result in valid

    def test_falls_back_for_unknown_weight_key(self):
        with open("assets/persona/phenotype_settings.json") as f:
            ps = json.load(f)
        rng = random.Random(0)
        result = pick_weighted_feature("scandinavian", "__no_such_key__", ps["eye_shapes"], rng)
        assert result in ps["eye_shapes"]


class TestAllEthnicityIds:
    def test_returns_sorted_list(self):
        ids = all_ethnicity_ids()
        assert isinstance(ids, list)
        assert ids == sorted(ids)
        assert len(ids) >= 40
