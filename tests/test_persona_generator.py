"""Tests for persona/aggregator_llm.py and persona/generator.py — mocked."""

from __future__ import annotations

from unittest.mock import patch

# ---------------------------------------------------------------------------
# aggregator_llm
# ---------------------------------------------------------------------------


class TestFromLlm:
    def test_returns_selected_value(self):
        with patch(
            "pipeline.persona.aggregator_llm._select_feature_field",
            return_value="analytical",
        ):
            from pipeline.persona.aggregator_llm import from_llm

            result = from_llm(
                "HAIR_STYLE",
                ["curly", "straight"],
                {"gender": "female", "age": 35},
            )
            assert result == "analytical"

    def test_returns_none_on_exception(self):
        with patch(
            "pipeline.persona.aggregator_llm._select_feature_field",
            side_effect=RuntimeError("gateway down"),
        ):
            from pipeline.persona.aggregator_llm import from_llm

            result = from_llm("HAIR_STYLE", ["curly"], {"gender": "male", "age": 30})
            assert result is None

    def test_extracts_demographics_from_resolved(self):
        calls = []

        def _capture(*args, **kwargs):
            calls.append(args)
            return "bob"

        with patch(
            "pipeline.persona.aggregator_llm._select_feature_field",
            side_effect=_capture,
        ):
            from pipeline.persona.aggregator_llm import from_llm

            from_llm("NAME", ["alice", "bob"], {"gender": "male", "age": 40, "style": "clay"})
            # First positional arg is attr name
            assert calls[0][0] == "NAME"

    def test_gateway_url_forwarded(self):
        with patch(
            "pipeline.persona.aggregator_llm._select_feature_field",
            return_value="straight",
        ) as mock_sel:
            from pipeline.persona.aggregator_llm import from_llm

            from_llm(
                "HAIR_STYLE",
                ["straight"],
                {"gender": "female", "age": 28},
                gateway_url="http://custom:9999",
            )
            call_kwargs = mock_sel.call_args.kwargs
            assert call_kwargs.get("gateway_url") == "http://custom:9999"


# ---------------------------------------------------------------------------
# generator
# ---------------------------------------------------------------------------

_FAKE_DEMOGRAPHICS = {
    "gender": "female",
    "age": 35,
    "style": "photorealistic",
    "bg_color": "#FFFFFF",
    "HAIR_COLOR": "#8B5E3C",
}

_FAKE_ADVISOR = {
    "traits": ["analytical"],
}

_FAKE_AVATAR = {
    "personal": {"name": "Alice Smith", "gender": "female"},
    "personality": _FAKE_ADVISOR,
    "appearance": {},
}


class TestGeneratePersona:
    def test_returns_dict(self):
        with (
            patch(
                "pipeline.persona.generator.pick_demographics",
                return_value=_FAKE_DEMOGRAPHICS.copy(),
            ),
            patch("pipeline.persona.aggregator_llm.select_features", return_value={}),
            patch(
                "pipeline.persona.generator.build_avatar_charachter",
                return_value=_FAKE_AVATAR.copy(),
            ),
        ):
            from pipeline.persona.generator import generate_persona

            result = generate_persona()
            assert isinstance(result, dict)

    def test_with_explicit_request_dict(self):
        with (
            patch(
                "pipeline.persona.generator.pick_demographics",
                return_value=_FAKE_DEMOGRAPHICS.copy(),
            ),
            patch("pipeline.persona.aggregator_llm.select_features", return_value={}),
            patch(
                "pipeline.persona.generator.build_avatar_charachter",
                return_value=_FAKE_AVATAR.copy(),
            ),
        ):
            from pipeline.persona.generator import generate_persona

            result = generate_persona({"gender": "male"})
            assert isinstance(result, dict)

    def test_with_yaml_request_file(self, tmp_path):
        persona_file = tmp_path / "req.yml"
        persona_file.write_text("gender: female\n")

        with (
            patch(
                "pipeline.persona.generator.pick_demographics",
                return_value=_FAKE_DEMOGRAPHICS.copy(),
            ),
            patch("pipeline.persona.aggregator_llm.select_features", return_value={}),
            patch(
                "pipeline.persona.generator.build_avatar_charachter",
                return_value=_FAKE_AVATAR.copy(),
            ),
        ):
            from pipeline.persona.generator import generate_persona

            result = generate_persona(persona_file)
            assert isinstance(result, dict)

    def test_feature_selection_failure_graceful(self):
        with (
            patch(
                "pipeline.persona.generator.pick_demographics",
                return_value=_FAKE_DEMOGRAPHICS.copy(),
            ),
            patch("pipeline.persona.aggregator_llm.select_features", return_value={}),
            patch(
                "pipeline.persona.generator.build_avatar_charachter",
                return_value=_FAKE_AVATAR.copy(),
            ),
        ):
            from pipeline.persona.generator import generate_persona

            result = generate_persona()
            assert isinstance(result, dict)

    def test_select_features_failure_graceful(self):
        with (
            patch(
                "pipeline.persona.generator.pick_demographics",
                return_value=_FAKE_DEMOGRAPHICS.copy(),
            ),
            patch(
                "pipeline.persona.aggregator_llm.select_features",
                side_effect=RuntimeError("feature selection down"),
            ),
            patch(
                "pipeline.persona.generator.build_avatar_charachter",
                return_value=_FAKE_AVATAR.copy(),
            ),
        ):
            from pipeline.persona.generator import generate_persona

            result = generate_persona()
            assert isinstance(result, dict)

    def test_session_dir_used_when_provided(self, tmp_path):
        select_calls = []

        def _capture_select(*args, **kwargs):
            select_calls.append(kwargs.get("session_dir"))
            return {}

        with (
            patch(
                "pipeline.persona.generator.pick_demographics",
                return_value=_FAKE_DEMOGRAPHICS.copy(),
            ),
            patch("pipeline.persona.aggregator_llm.select_features", side_effect=_capture_select),
            patch(
                "pipeline.persona.generator.build_avatar_charachter",
                return_value=_FAKE_AVATAR.copy(),
            ),
        ):
            from pipeline.persona.generator import generate_persona

            generate_persona(session_dir=tmp_path)
            assert select_calls and select_calls[0] == tmp_path
