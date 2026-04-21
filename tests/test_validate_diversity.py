"""Tests for tuning/validate_diversity.py — DeepFace validator (mocked)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tuning.validate_diversity import (
    DiversityReport,
    FieldValidation,
    _fitzpatrick_adjacent,
    validate_avatar_diversity,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_FAKE_DEEPFACE_RESULT = {
    "age": 35,
    "dominant_gender": "Man",
    "gender": {"Man": 92.0, "Woman": 8.0},
    "dominant_race": "white",
    "race": {
        "asian": 1.0,
        "indian": 0.5,
        "black": 0.5,
        "white": 95.0,
        "middle eastern": 2.0,
        "latino hispanic": 1.0,
    },
}

_PERSONA_SCANDINAVIAN = {
    "personal": {
        "age": 33,
        "gender": "male",
        "ethnicity": "scandinavian",
    },
    "appearance": {
        "skin_tone": "#F2D4CC",  # cream/cool pink → Fitzpatrick II
        "fitzpatrick_type": "II",
    },
}


# ---------------------------------------------------------------------------
# DiversityReport
# ---------------------------------------------------------------------------


class TestDiversityReport:
    def test_score_all_pass(self):
        report = DiversityReport(
            validations=[
                FieldValidation("age", "35", "35", match=True, confidence=1.0),
                FieldValidation("gender", "male", "male", match=True, confidence=0.9),
                FieldValidation("race", "white", "white", match=True, confidence=0.95),
                FieldValidation("fitzpatrick_type", "II", "II", match=True, confidence=1.0),
            ]
        )
        assert report.score == pytest.approx(1.0)

    def test_score_all_fail(self):
        report = DiversityReport(
            validations=[
                FieldValidation("age", "35", "60", match=False, confidence=1.0),
                FieldValidation("gender", "male", "female", match=False, confidence=0.9),
                FieldValidation("race", "white", "black", match=False, confidence=0.5),
                FieldValidation("fitzpatrick_type", "II", "V", match=False, confidence=1.0),
            ]
        )
        assert report.score == pytest.approx(0.0)

    def test_score_partial(self):
        report = DiversityReport(
            validations=[
                FieldValidation("age", "35", "35", match=True, confidence=1.0),
                FieldValidation("gender", "male", "female", match=False, confidence=0.9),
                FieldValidation("race", "white", "white", match=True, confidence=0.95),
                FieldValidation("fitzpatrick_type", "II", "II", match=True, confidence=1.0),
            ]
        )
        # age=0.15, gender=0.25(fail), race=0.35, fitzpatrick=0.25 → earned=0.75
        assert 0.70 < report.score < 0.85

    def test_mismatches_lists_failed(self):
        report = DiversityReport(
            validations=[
                FieldValidation("age", "35", "35", match=True, confidence=1.0),
                FieldValidation("gender", "male", "female", match=False, confidence=0.9),
            ]
        )
        mismatches = report.mismatches
        assert len(mismatches) == 1
        assert "gender" in mismatches[0]
        assert "female" in mismatches[0]

    def test_empty_report_score_is_zero(self):
        report = DiversityReport()
        assert report.score == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# _fitzpatrick_adjacent
# ---------------------------------------------------------------------------


class TestFitzpatrickAdjacent:
    def test_same_type(self):
        assert _fitzpatrick_adjacent("II", "II")

    def test_adjacent_types(self):
        assert _fitzpatrick_adjacent("II", "I")
        assert _fitzpatrick_adjacent("II", "III")
        assert _fitzpatrick_adjacent("V", "VI")

    def test_non_adjacent(self):
        assert not _fitzpatrick_adjacent("I", "III")
        assert not _fitzpatrick_adjacent("I", "VI")

    def test_invalid_type(self):
        assert not _fitzpatrick_adjacent("I", "VII")


# ---------------------------------------------------------------------------
# validate_avatar_diversity — mocked DeepFace
# ---------------------------------------------------------------------------


class TestValidateAvatarDiversity:
    def _call(self, persona=None, deepface_result=None):
        if persona is None:
            persona = _PERSONA_SCANDINAVIAN
        if deepface_result is None:
            deepface_result = _FAKE_DEEPFACE_RESULT.copy()

        fake_image = b"\xff\xd8\xff\xe0" + b"\x00" * 100  # minimal JPEG-ish bytes

        with patch("tuning.validate_diversity.DeepFace", create=True) as mock_df:
            mock_df.analyze.return_value = deepface_result
            report = validate_avatar_diversity(fake_image, persona)
        return report

    def test_returns_diversity_report(self):
        report = self._call()
        assert isinstance(report, DiversityReport)

    def test_age_validation_pass(self):
        report = self._call()
        age_v = next(v for v in report.validations if v.field_name == "age")
        assert age_v.match  # |33 - 35| = 2 ≤ 10

    def test_age_validation_fail(self):
        persona = {
            "personal": {"age": 70, "gender": "male", "ethnicity": "scandinavian"},
            "appearance": {"skin_tone": "#F2D4CC", "fitzpatrick_type": "II"},
        }
        report = self._call(persona=persona)
        age_v = next(v for v in report.validations if v.field_name == "age")
        assert not age_v.match  # |70 - 35| = 35 > 10

    def test_gender_validation_male_pass(self):
        report = self._call()
        g_v = next(v for v in report.validations if v.field_name == "gender")
        assert g_v.match

    def test_gender_validation_non_binary_always_pass(self):
        persona = {
            "personal": {"age": 33, "gender": "non-binary", "ethnicity": "scandinavian"},
            "appearance": {"skin_tone": "#F2D4CC", "fitzpatrick_type": "II"},
        }
        report = self._call(persona=persona)
        g_v = next(v for v in report.validations if v.field_name == "gender")
        assert g_v.match  # non-binary always passes

    def test_race_validation_pass(self):
        report = self._call()
        r_v = next(v for v in report.validations if v.field_name == "race")
        assert r_v.match  # scandinavian → white, deepface → white

    def test_race_validation_fail(self):
        persona = {
            "personal": {"age": 33, "gender": "male", "ethnicity": "west_african"},
            "appearance": {"skin_tone": "#7A4C28", "fitzpatrick_type": "V"},
        }
        report = self._call(persona=persona, deepface_result=_FAKE_DEEPFACE_RESULT.copy())
        r_v = next(v for v in report.validations if v.field_name == "race")
        assert not r_v.match  # west_african → black, deepface → white

    def test_fitzpatrick_validation_pass(self):
        report = self._call()
        fitz_vs = [v for v in report.validations if v.field_name == "fitzpatrick_type"]
        assert fitz_vs  # validation was performed
        assert fitz_vs[0].match  # cream/cool pink → ITA→II, declared II ✓

    def test_deepface_raw_stored(self):
        report = self._call()
        assert report.deepface_raw.get("age") is not None

    def test_list_result_handled(self):
        """DeepFace sometimes returns a list — validator should unwrap it."""
        fake_image = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        with patch("tuning.validate_diversity.DeepFace", create=True) as mock_df:
            mock_df.analyze.return_value = [_FAKE_DEEPFACE_RESULT.copy()]
            report = validate_avatar_diversity(fake_image, _PERSONA_SCANDINAVIAN)
        assert isinstance(report, DiversityReport)

    def test_missing_ethnicity_skips_race(self):
        persona = {
            "personal": {"age": 33, "gender": "male"},
            "appearance": {"skin_tone": "#F2D4CC", "fitzpatrick_type": "II"},
        }
        report = self._call(persona=persona)
        race_vs = [v for v in report.validations if v.field_name == "race"]
        assert not race_vs  # no race validation without ethnicity

    def test_ita_value_set(self):
        report = self._call()
        assert report.ita_value is not None
        assert isinstance(report.ita_value, float)

    def test_deepface_analyze_called_once(self):
        fake_image = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        with patch("tuning.validate_diversity.DeepFace", create=True) as mock_df:
            mock_df.analyze.return_value = _FAKE_DEEPFACE_RESULT.copy()
            validate_avatar_diversity(fake_image, _PERSONA_SCANDINAVIAN)
            assert mock_df.analyze.call_count == 1

    def test_temp_file_cleaned_up(self, tmp_path):
        """No temp files left after validation."""
        import tempfile

        original_mkstemp = tempfile.mkstemp
        created_paths = []

        def tracking_mkstemp(*args, **kwargs):
            fd, path = original_mkstemp(*args, **kwargs)
            created_paths.append(path)
            return fd, path

        fake_image = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        with (
            patch("tuning.validate_diversity.DeepFace") as mock_df,
            patch("tempfile.mkstemp", side_effect=tracking_mkstemp),
        ):
            mock_df.analyze.return_value = _FAKE_DEEPFACE_RESULT.copy()
            validate_avatar_diversity(fake_image, _PERSONA_SCANDINAVIAN)

        # Temp files created should no longer exist
        import os

        for path in created_paths:
            assert not os.path.exists(path), f"Temp file not cleaned up: {path}"

    def test_deepface_import_error_message(self):
        """If DeepFace is not installed, the error should propagate clearly."""
        fake_image = b"\xff\xd8\xff\xe0" + b"\x00" * 100

        def _bad_import(name, *args, **kwargs):
            if "deepface" in name.lower():
                raise ImportError("No module named 'deepface'")
            return MagicMock()

        with patch("builtins.__import__", side_effect=_bad_import):
            with pytest.raises(ImportError, match="deepface"):
                validate_avatar_diversity(fake_image, _PERSONA_SCANDINAVIAN)
