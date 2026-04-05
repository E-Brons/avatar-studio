"""Tests for api.server — helper functions and process_advisor."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml
from PIL import Image

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_png() -> bytes:
    img = Image.new("RGBA", (64, 64), (100, 150, 200, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


_DEMO = {
    "gender": "female",
    "age": 30,
    "name": "Alice Smith",
    "bg_color": "#4A90D9",
    "fg_color": "#FFFFFF",
    "style": "photorealistic",
}

_ADVISOR = {
    "name": "Alice Smith",
    "role": "Advisor",
    "traits": ["analytical"],
    "education": ["MBA"],
    "experience": ["5 years"],
}


# ---------------------------------------------------------------------------
# _ollama_available_models
# ---------------------------------------------------------------------------


class TestOllamaAvailableModels:
    def test_returns_model_names_on_success(self):
        from api.server import _ollama_available_models

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"models": [{"name": "phi3:latest"}, {"name": "flux2:4b"}]}
        mock_resp.raise_for_status.return_value = None
        with patch("api.server.requests.get", return_value=mock_resp):
            result = _ollama_available_models()
        assert "phi3:latest" in result
        assert "flux2:4b" in result

    def test_returns_empty_set_on_connection_error(self):
        from api.server import _ollama_available_models

        with patch("api.server.requests.get", side_effect=ConnectionError("refused")):
            result = _ollama_available_models()
        assert result == set()

    def test_returns_empty_set_on_http_error(self):
        from api.server import _ollama_available_models

        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("404")
        with patch("api.server.requests.get", return_value=mock_resp):
            result = _ollama_available_models()
        assert result == set()


# ---------------------------------------------------------------------------
# _resolve_default_model
# ---------------------------------------------------------------------------


class TestResolveDefaultModel:
    def test_exact_match(self):
        from api.server import _resolve_default_model

        available = {"phi3:latest", "flux2:4b"}
        assert _resolve_default_model("phi3:latest", available, "text") == "phi3:latest"

    def test_strips_ollama_prefix(self):
        from api.server import _resolve_default_model

        available = {"phi3:latest"}
        assert _resolve_default_model("ollama/phi3:latest", available, "text") == "phi3:latest"

    def test_bare_name_matches_versioned(self):
        from api.server import _resolve_default_model

        available = {"phi3:latest"}
        assert _resolve_default_model("phi3", available, "text") == "phi3:latest"

    def test_returns_none_when_not_found(self):
        from api.server import _resolve_default_model

        assert _resolve_default_model("unknown_model", {"phi3:latest"}, "text") is None


# ---------------------------------------------------------------------------
# _build_demographics_for_gender
# ---------------------------------------------------------------------------


class TestBuildDemographicsForGender:
    def test_forces_gender(self):
        from api.server import _build_demographics_for_gender

        with patch("api.server.pick_demographics", return_value=dict(_DEMO)):
            result = _build_demographics_for_gender("male")
        assert result["gender"] == "male"

    def test_passes_seed(self):
        from api.server import _build_demographics_for_gender

        with patch("api.server.pick_demographics", return_value=dict(_DEMO)) as mock_pick:
            _build_demographics_for_gender("female", seed=42)
        mock_pick.assert_called_once_with(seed=42)


# ---------------------------------------------------------------------------
# process_advisor
# ---------------------------------------------------------------------------


class TestProcessAdvisor:
    def _write_advisor(self, tmp_path: Path) -> Path:
        p = tmp_path / "advisor.yml"
        p.write_text(yaml.dump(_ADVISOR))
        return p

    def _mock_gen(self, *args, **kwargs):
        """create_face_avatar returns (expr_map, demographics)."""
        return ({"neutral": "alice-smith-neutral.png"}, dict(_DEMO))

    def test_writes_picture_to_advisor_yml(self, tmp_path):
        from api.server import process_advisor

        advisor_path = self._write_advisor(tmp_path)
        neutral_png = tmp_path / "alice-smith-neutral.png"
        neutral_png.write_bytes(_make_png())

        with (
            patch(
                "api.server.create_face_avatar",
                return_value=({"neutral": "alice-smith-neutral.png"}, dict(_DEMO)),
            ),
            patch("api.server.create_abbreviation_avatar"),
            patch("api.server.create_programmatic_avatar"),
        ):
            process_advisor(advisor_path, tmp_path, gateway_url="http://gw")

        updated = yaml.safe_load(advisor_path.read_text())
        assert "picture" in updated
        assert "abbreviation" in updated["picture"]

    def test_pa_failure_non_fatal(self, tmp_path):
        """Programmatic avatar failure → warning logged, picture dict still written."""
        from api.server import process_advisor

        advisor_path = self._write_advisor(tmp_path)

        with (
            patch(
                "api.server.create_face_avatar",
                return_value=({"neutral": "alice-smith-neutral.png"}, dict(_DEMO)),
            ),
            patch("api.server.create_abbreviation_avatar"),
            patch("api.server.create_programmatic_avatar", side_effect=RuntimeError("node fail")),
        ):
            process_advisor(advisor_path, tmp_path, gateway_url="http://gw")

        updated = yaml.safe_load(advisor_path.read_text())
        assert "picture" in updated
        # pa_filename is None → not in picture
        assert "programmatic_avatar" not in updated["picture"]

    def test_neutral_prepended_when_missing(self, tmp_path):
        """If 'neutral' not in expressions, it gets prepended."""
        from api.server import process_advisor

        advisor_path = self._write_advisor(tmp_path)
        captured = {}

        def _capture_face(advisor, expressions, *args, **kwargs):
            captured["expressions"] = expressions
            return ({"neutral": "x.png"}, dict(_DEMO))

        with (
            patch("api.server.create_face_avatar", side_effect=_capture_face),
            patch("api.server.create_abbreviation_avatar"),
            patch("api.server.create_programmatic_avatar"),
        ):
            process_advisor(advisor_path, tmp_path, expressions=["happiness"])

        assert captured["expressions"][0] == "neutral"
        assert "happiness" in captured["expressions"]


# ---------------------------------------------------------------------------
# _load_expression_ids (lines 62-64)
# ---------------------------------------------------------------------------


class TestLoadExpressionIds:
    def test_returns_list_of_strings(self):
        from pipeline.render.expression_resolver import load_expression_ids

        result = load_expression_ids()
        assert isinstance(result, list)
        assert len(result) > 0
        assert all(isinstance(x, str) for x in result)
