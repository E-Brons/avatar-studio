"""Tests for pipeline/persona/skin_tones.py."""

from __future__ import annotations

import random

import pytest


class TestLoadSkinTones:
    def test_returns_dict(self):
        from pipeline.persona.skin_tones import load_skin_tones

        tones = load_skin_tones()
        assert isinstance(tones, dict)

    def test_expected_count(self):
        from pipeline.persona.skin_tones import load_skin_tones

        tones = load_skin_tones()
        assert len(tones) == 120, f"Expected 120 skin tones, got {len(tones)}"

    def test_all_have_required_fields(self):
        from pipeline.persona.skin_tones import _REQUIRED_FIELDS, load_skin_tones

        tones = load_skin_tones()
        for tid, entry in tones.items():
            missing = _REQUIRED_FIELDS - entry.keys()
            assert not missing, f"Skin tone '{tid}' missing fields: {missing}"

    def test_ids_are_unique(self):
        from pipeline.persona.skin_tones import load_skin_tones, skin_tone_id

        tones = load_skin_tones()
        # The dict keys are already unique by construction — verify they match skin_tone_id()
        for tid, entry in tones.items():
            assert tid == skin_tone_id(entry), f"Key mismatch: {tid!r} != {skin_tone_id(entry)!r}"

    def test_id_format(self):
        from pipeline.persona.skin_tones import load_skin_tones

        tones = load_skin_tones()
        for tid in tones:
            assert "/" in tid, f"ID '{tid}' missing '/' separator"
            parts = tid.split("/", 1)
            assert all(p.strip() for p in parts), f"ID '{tid}' has empty component"

    def test_fitzpatrick_values_valid(self):
        from pipeline.persona.skin_tones import load_skin_tones

        valid = {"I", "II", "III", "IV", "V", "VI"}
        tones = load_skin_tones()
        for tid, entry in tones.items():
            fitz = entry["fitzpatrick-scale"]
            assert fitz in valid, f"Skin tone '{tid}' has invalid Fitzpatrick value: {fitz!r}"

    def test_tone_hex_format(self):
        from pipeline.persona.skin_tones import load_skin_tones

        tones = load_skin_tones()
        hex_fields = ("tone", "undertone", "surface", "shadow", "lip")
        for tid, entry in tones.items():
            for field in hex_fields:
                val = entry[field]
                assert isinstance(val, str), f"'{tid}'.{field} must be str, got {type(val)}"
                assert val.startswith("#") and len(val) == 7, (
                    f"'{tid}'.{field} invalid hex: {val!r}"
                )

    def test_shine_is_integer(self):
        from pipeline.persona.skin_tones import load_skin_tones

        tones = load_skin_tones()
        for tid, entry in tones.items():
            assert isinstance(entry["shine"], int), (
                f"'{tid}'.shine must be int, got {type(entry['shine'])}"
            )

    def test_all_fitzpatrick_types_represented(self):
        from pipeline.persona.skin_tones import load_skin_tones

        tones = load_skin_tones()
        fitzpatrick_types = {entry["fitzpatrick-scale"] for entry in tones.values()}
        assert fitzpatrick_types == {"I", "II", "III", "IV", "V", "VI"}

    def test_all_monk_scales_represented(self):
        from pipeline.persona.skin_tones import load_skin_tones

        tones = load_skin_tones()
        monk_scales = {entry["monk-scale"] for entry in tones.values()}
        expected = {f"MST-{i:02d}" for i in range(1, 11)}
        assert monk_scales == expected


class TestSkinToneId:
    def test_basic(self):
        from pipeline.persona.skin_tones import skin_tone_id

        entry = {"tone-name": "porcelain", "undertone-name": "cool pink"}
        assert skin_tone_id(entry) == "porcelain/cool pink"

    def test_no_spaces(self):
        from pipeline.persona.skin_tones import skin_tone_id

        entry = {"tone-name": "espresso", "undertone-name": "warm golden"}
        assert skin_tone_id(entry) == "espresso/warm golden"


class TestTonesByFitzpatrick:
    def test_returns_only_matching_fitzpatrick(self):
        from pipeline.persona.skin_tones import tones_by_fitzpatrick

        for fitz in ("I", "II", "III", "IV", "V", "VI"):
            subset = tones_by_fitzpatrick(fitz)
            assert len(subset) > 0, f"No tones found for Fitzpatrick {fitz}"
            for tid, entry in subset.items():
                assert entry["fitzpatrick-scale"] == fitz, (
                    f"Entry '{tid}' has wrong Fitzpatrick scale"
                )

    def test_unknown_fitzpatrick_returns_empty(self):
        from pipeline.persona.skin_tones import tones_by_fitzpatrick

        assert tones_by_fitzpatrick("VII") == {}

    def test_total_adds_up_to_120(self):
        from pipeline.persona.skin_tones import tones_by_fitzpatrick

        total = sum(len(tones_by_fitzpatrick(f)) for f in ("I", "II", "III", "IV", "V", "VI"))
        assert total == 120


class TestPickSkinTone:
    def test_returns_valid_entry(self):
        from pipeline.persona.skin_tones import pick_skin_tone

        rng = random.Random(42)
        probs = {"porcelain/cool pink": 0.5, "porcelain/neutral": 0.5}
        entry = pick_skin_tone(probs, rng)
        assert "tone" in entry
        assert "fitzpatrick-scale" in entry

    def test_respects_weights_roughly(self):
        from pipeline.persona.skin_tones import pick_skin_tone

        rng = random.Random(0)
        # 100% weight on one entry
        probs = {"porcelain/cool pink": 1.0, "porcelain/neutral": 0.0}
        for _ in range(20):
            entry = pick_skin_tone(probs, rng)
            assert entry["tone-name"] == "porcelain"
            assert entry["undertone-name"] == "cool pink"

    def test_empty_probs_raises(self):
        from pipeline.persona.skin_tones import pick_skin_tone

        rng = random.Random()
        with pytest.raises(ValueError):
            pick_skin_tone({}, rng)

    def test_unknown_id_raises(self):
        from pipeline.persona.skin_tones import pick_skin_tone

        rng = random.Random()
        with pytest.raises(KeyError):
            pick_skin_tone({"nonexistent/made up": 1.0}, rng)

    def test_deterministic_with_seed(self):
        from pipeline.persona.skin_tones import pick_skin_tone

        probs = {
            "porcelain/cool pink": 0.3,
            "cream/warm golden": 0.4,
            "sienna/warm golden": 0.3,
        }
        e1 = pick_skin_tone(probs, random.Random(123))
        e2 = pick_skin_tone(probs, random.Random(123))
        assert e1["tone-name"] == e2["tone-name"]
        assert e1["undertone-name"] == e2["undertone-name"]
