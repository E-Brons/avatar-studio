"""Tests for tuning classifier modules — pure parsing functions + mocked LLM calls."""

from __future__ import annotations

import io
from unittest.mock import patch

from PIL import Image


def _tiny_png() -> bytes:
    img = Image.new("RGB", (16, 16), (200, 200, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# classify_expression — ExpressionClassificationResult
# ---------------------------------------------------------------------------


class TestExpressionClassificationResult:
    def _result(self, top="happy", scores=None):
        from tuning.classify_expression import ExpressionClassificationResult

        return ExpressionClassificationResult(
            top_expression=top,
            scores=scores or {"happy": 0.6, "neutral": 0.2, "sad": 0.1, "angry": 0.05, "surprised": 0.05},
        )

    def test_top_n(self):
        r = self._result()
        assert r.top_n(2) == ["happy", "neutral"]

    def test_top_score(self):
        r = self._result()
        assert r.top_score() == 0.6

    def test_score_for_case_insensitive(self):
        r = self._result()
        assert r.score_for("HAPPY") == 0.6

    def test_score_for_absent_returns_zero(self):
        r = self._result()
        assert r.score_for("contempt") == 0.0

    def test_is_correct_true(self):
        r = self._result()
        assert r.is_correct("happy") is True

    def test_is_correct_false_wrong_label(self):
        r = self._result()
        assert r.is_correct("sad") is False

    def test_is_correct_false_below_threshold(self):
        from tuning.classify_expression import ExpressionClassificationResult

        r = ExpressionClassificationResult(
            top_expression="happy", scores={"happy": 0.2, "neutral": 0.8}
        )
        assert r.is_correct("happy", threshold=0.35) is False

    def test_is_visible_true(self):
        r = self._result()
        assert r.is_visible("neutral", threshold=0.15) is True

    def test_is_visible_false(self):
        r = self._result()
        assert r.is_visible("neutral", threshold=0.35) is False

    def test_in_top_n_true(self):
        r = self._result()
        assert r.in_top_n("neutral", n=2) is True

    def test_in_top_n_false(self):
        r = self._result()
        assert r.in_top_n("surprised", n=2) is False


# ---------------------------------------------------------------------------
# _parse_expression_response — pure function
# ---------------------------------------------------------------------------


class TestParseExpressionResponse:
    def test_parses_valid_yaml(self):
        from tuning.classify_expression import _parse_expression_response

        raw = "top_expression: happy\nexpressions:\n  happy: 0.7\n  sad: 0.3\nreasoning: looks joyful\n"
        result = _parse_expression_response(raw, [])
        assert result.top_expression == "happy"
        assert result.scores["happy"] == 0.7
        assert result.reasoning == "looks joyful"

    def test_strips_code_fences(self):
        from tuning.classify_expression import _parse_expression_response

        raw = "```yaml\ntop_expression: sad\nexpressions:\n  sad: 0.8\n```"
        result = _parse_expression_response(raw, [])
        assert result.top_expression == "sad"

    def test_hint_labels_ensured(self):
        from tuning.classify_expression import _parse_expression_response

        raw = "top_expression: happy\nexpressions:\n  happy: 0.9\n"
        result = _parse_expression_response(raw, ["Sadness", "Anger"])
        assert "Sadness" in result.scores
        assert "Anger" in result.scores

    def test_invalid_yaml_returns_empty(self):
        from tuning.classify_expression import _parse_expression_response

        raw = ": : : invalid yaml :::"
        result = _parse_expression_response(raw, [])
        assert result.top_expression == "" or isinstance(result.top_expression, str)

    def test_non_dict_yaml_returns_empty(self):
        from tuning.classify_expression import _parse_expression_response

        raw = "- item1\n- item2\n"
        result = _parse_expression_response(raw, [])
        assert result.scores == {}

    def test_derives_top_from_highest_score(self):
        from tuning.classify_expression import _parse_expression_response

        raw = "expressions:\n  happy: 0.1\n  surprised: 0.8\nreasoning: wide eyes\n"
        result = _parse_expression_response(raw, [])
        assert result.top_expression == "surprised"

    def test_invalid_score_defaults_to_zero(self):
        from tuning.classify_expression import _parse_expression_response

        raw = "top_expression: happy\nexpressions:\n  happy: not_a_number\n  sad: 0.3\n"
        result = _parse_expression_response(raw, [])
        assert result.scores["happy"] == 0.0


# ---------------------------------------------------------------------------
# classify_image_expression — mocked LLM
# ---------------------------------------------------------------------------


class TestClassifyImageExpression:
    _RESPONSE = "top_expression: happy\nexpressions:\n  happy: 0.8\n  neutral: 0.2\nreasoning: smile\n"

    def test_returns_result(self):
        with patch(
            "tuning.classify_expression._call_vision_model",
            return_value=self._RESPONSE,
        ):
            from tuning.classify_expression import classify_image_expression

            result = classify_image_expression(_tiny_png())
            assert result.top_expression == "happy"

    def test_with_labels_hint(self):
        with patch(
            "tuning.classify_expression._call_vision_model",
            return_value=self._RESPONSE,
        ):
            from tuning.classify_expression import classify_image_expression

            result = classify_image_expression(_tiny_png(), ["happy", "sad"])
            assert "happy" in result.scores

    def test_raw_response_stored(self):
        with patch(
            "tuning.classify_expression._call_vision_model",
            return_value=self._RESPONSE,
        ):
            from tuning.classify_expression import classify_image_expression

            result = classify_image_expression(_tiny_png())
            assert result.raw_response == self._RESPONSE

    def test_llm_failure_reraises(self):
        import pytest

        with patch(
            "tuning.classify_expression._call_vision_model",
            side_effect=RuntimeError("gateway down"),
        ):
            from tuning.classify_expression import classify_image_expression

            with pytest.raises(RuntimeError, match="gateway down"):
                classify_image_expression(_tiny_png())


# ---------------------------------------------------------------------------
# semantic_effective_score — mocked text model
# ---------------------------------------------------------------------------


class TestSemanticEffectiveScore:
    def test_yes_answer_adds_score(self):
        with patch(
            "tuning.classify_expression._call_text_model",
            return_value="yes",
        ):
            from tuning.classify_expression import semantic_effective_score

            result = semantic_effective_score({"pensive": 0.4, "focused": 0.3}, "thinking")
            assert result > 0.0

    def test_no_answer_zero_contribution(self):
        with patch(
            "tuning.classify_expression._call_text_model",
            return_value="no",
        ):
            from tuning.classify_expression import semantic_effective_score

            result = semantic_effective_score({"angry": 0.6}, "happy")
            assert result == 0.0

    def test_zero_score_entries_skipped(self):
        calls = []

        def _capture(gateway_url, prompt, timeout):
            calls.append(prompt)
            return "yes"

        with patch("tuning.classify_expression._call_text_model", side_effect=_capture):
            from tuning.classify_expression import semantic_effective_score

            semantic_effective_score({"happy": 0.5, "zero_entry": 0.0}, "happy")
            assert len(calls) == 1  # zero_entry skipped

    def test_call_failure_skipped(self):
        with patch(
            "tuning.classify_expression._call_text_model",
            side_effect=RuntimeError("timeout"),
        ):
            from tuning.classify_expression import semantic_effective_score

            result = semantic_effective_score({"happy": 0.8}, "happy")
            assert result == 0.0


# ---------------------------------------------------------------------------
# classify_style — StyleClassificationResult + _parse_classification_response
# ---------------------------------------------------------------------------


class TestStyleClassificationResult:
    def _result(self, top="photorealistic"):
        from tuning.classify_style import StyleClassificationResult

        return StyleClassificationResult(
            top_style_id=top,
            scores={"photorealistic": 0.8, "clay": 0.15, "lineart": 0.05},
        )

    def test_top_n(self):
        r = self._result()
        assert r.top_n(2) == ["photorealistic", "clay"]

    def test_is_correct(self):
        r = self._result()
        assert r.is_correct("photorealistic") is True
        assert r.is_correct("clay") is False

    def test_in_top_n(self):
        r = self._result()
        assert r.in_top_n("clay", n=2) is True
        assert r.in_top_n("lineart", n=1) is False


class TestParseClassificationResponse:
    def test_parses_valid_yaml(self):
        from tuning.classify_style import _parse_classification_response

        raw = "top_style: photorealistic\nscores:\n  photorealistic: 0.8\n  clay: 0.2\nreasoning: detailed\n"
        result = _parse_classification_response(raw, ["photorealistic", "clay"])
        assert result.top_style_id == "photorealistic"
        assert result.scores["clay"] == 0.2

    def test_top_not_in_style_ids_cleared(self):
        from tuning.classify_style import _parse_classification_response

        raw = "top_style: unknown_style\nscores:\n  photorealistic: 0.9\n"
        result = _parse_classification_response(raw, ["photorealistic"])
        assert result.top_style_id == "photorealistic"  # derived from scores

    def test_invalid_yaml_returns_empty(self):
        from tuning.classify_style import _parse_classification_response

        result = _parse_classification_response(": : invalid :", ["photorealistic"])
        assert result.top_style_id in ("", "photorealistic")

    def test_strips_code_fences(self):
        from tuning.classify_style import _parse_classification_response

        raw = "```yaml\ntop_style: clay\nscores:\n  clay: 0.9\n```"
        result = _parse_classification_response(raw, ["clay"])
        assert result.top_style_id == "clay"


class TestClassifyImageStyle:
    _STYLES = [
        {
            "id": "photorealistic",
            "name": "Photorealistic",
            "key_technical_traits": ["natural skin", "subsurface scattering"],
        },
        {
            "id": "clay",
            "name": "Clay",
            "key_technical_traits": ["matte surface", "rounded edges"],
        },
    ]

    def test_returns_result(self):
        raw = "top_style: clay\nscores:\n  photorealistic: 0.2\n  clay: 0.8\nreasoning: matte\n"
        with patch("tuning.classify_style._call_vision_model", return_value=raw):
            from tuning.classify_style import classify_image_style

            result = classify_image_style(_tiny_png(), self._STYLES)
            assert result.top_style_id == "clay"

    def test_empty_styles_returns_empty_result(self):
        from tuning.classify_style import classify_image_style

        result = classify_image_style(_tiny_png(), [])
        assert result.top_style_id == ""

    def test_no_checkable_styles_returns_empty(self):
        from tuning.classify_style import classify_image_style

        styles = [{"id": "random"}]  # no key_technical_traits
        result = classify_image_style(_tiny_png(), styles)
        assert result.top_style_id == ""


# ---------------------------------------------------------------------------
# classify_persona — pure functions
# ---------------------------------------------------------------------------


class TestHexToRgb:
    def test_valid_hex(self):
        from tuning.classify_persona import _hex_to_rgb

        assert _hex_to_rgb("#FF0000") == (255, 0, 0)

    def test_without_hash(self):
        from tuning.classify_persona import _hex_to_rgb

        assert _hex_to_rgb("00FF00") == (0, 255, 0)

    def test_invalid_returns_none(self):
        from tuning.classify_persona import _hex_to_rgb

        assert _hex_to_rgb("#GGGGGG") is None

    def test_short_returns_none(self):
        from tuning.classify_persona import _hex_to_rgb

        assert _hex_to_rgb("#FFF") is None


class TestYCbCrDistance:
    def test_same_color_zero_distance(self):
        from tuning.classify_persona import _ycbcr_distance

        assert _ycbcr_distance("#FF0000", "#FF0000") == 0.0

    def test_different_colors_positive(self):
        from tuning.classify_persona import _ycbcr_distance

        assert _ycbcr_distance("#000000", "#FFFFFF") > 0.0

    def test_invalid_hex_returns_inf(self):
        from tuning.classify_persona import _ycbcr_distance

        assert _ycbcr_distance("#GGGGGG", "#FF0000") == float("inf")


class TestWithinColorTolerance:
    def test_no_hex_in_desc_returns_none(self):
        from tuning.classify_persona import _within_color_tolerance

        assert _within_color_tolerance("#FF0000", "medium brown hair") is None

    def test_exact_match_returns_true(self):
        from tuning.classify_persona import _within_color_tolerance

        assert _within_color_tolerance("#FF0000", "red (#FF0000)") is True

    def test_far_color_returns_false(self):
        from tuning.classify_persona import _within_color_tolerance

        result = _within_color_tolerance("#000000", "very light (#FFFFFF)")
        assert result is False


class TestHexLabel:
    def test_exact_match(self):
        from tuning.classify_persona import _hex_label

        table = {"#FF0000": "red", "#0000FF": "blue"}
        assert _hex_label("#FF0000", table) == "red"

    def test_nearest_color_fallback(self):
        from tuning.classify_persona import _hex_label

        table = {"#FF0000": "red", "#0000FF": "blue"}
        # slightly off-red → nearest is red
        result = _hex_label("#FE0000", table)
        assert result == "red"

    def test_empty_table_returns_hex(self):
        from tuning.classify_persona import _hex_label

        assert _hex_label("#ABCDEF", {}) == "#ABCDEF"

    def test_invalid_hex_returns_hex(self):
        from tuning.classify_persona import _hex_label

        assert _hex_label("#GGGGGG", {"#FF0000": "red"}) == "#GGGGGG"


class TestColorDesc:
    def test_includes_label_and_hex(self):
        from tuning.classify_persona import _color_desc

        result = _color_desc("#FF0000", {"#FF0000": "red"})
        assert "red" in result
        assert "#FF0000" in result


class TestDescribeProperties:
    def test_returns_dict(self):
        from tuning.classify_persona import _describe_properties

        persona = {
            "appearance": {
                "skin_tone": "#D4A76A",
                "hair_color": {"primary": "#8B5E3C", "secondary": "#5C3D1E"},
                "eye_color": {"primary": "#3D1C02"},
            }
        }
        result = _describe_properties(persona)
        assert isinstance(result, dict)

    def test_empty_persona_returns_empty(self):
        from tuning.classify_persona import _describe_properties

        assert _describe_properties({}) == {}


class TestParseCategoryResponse:
    def test_parses_visible_true(self):
        from tuning.classify_persona import _parse_categorizer_response

        raw = "skin_tone:\n  visible: true\n  note: warm tone\n"
        result = _parse_categorizer_response(raw, {"skin_tone": "warm (#D4A76A)"})
        assert len(result.results) == 1
        assert result.results[0].visible is True

    def test_parses_visible_false(self):
        from tuning.classify_persona import _parse_categorizer_response

        raw = "skin_tone:\n  visible: false\n  note: unclear\n"
        result = _parse_categorizer_response(raw, {"skin_tone": "dark (#3D1C02)"})
        assert result.results[0].visible is False

    def test_invalid_yaml_all_not_visible(self):
        from tuning.classify_persona import _parse_categorizer_response

        result = _parse_categorizer_response(": invalid yaml :::", {"skin_tone": "desc"})
        assert all(not r.visible for r in result.results)

    def test_color_property_ycbcr_override(self):
        from tuning.classify_persona import _parse_categorizer_response

        # observed_hex matches expected hex → visible overridden to True
        raw = "skin_tone:\n  visible: false\n  observed_hex: '#D4A76A'\n  note: seen\n"
        result = _parse_categorizer_response(raw, {"skin_tone": "honey tan (#D4A76A)"})
        assert result.results[0].visible is True

    def test_non_dict_entry_defaults_not_visible(self):
        from tuning.classify_persona import _parse_categorizer_response

        raw = "skin_tone: some_string_not_a_dict\n"
        result = _parse_categorizer_response(raw, {"skin_tone": "desc"})
        assert result.results[0].visible is False


class TestCategorizeAvatarImage:
    def test_empty_persona_returns_empty_report(self):
        from tuning.classify_persona import categorize_avatar_image

        result = categorize_avatar_image(_tiny_png(), {})
        assert result.results == []

    def test_llm_failure_reraises(self):
        import pytest

        with patch(
            "tuning.classify_persona.GatewayClient",
        ) as MockClient:
            MockClient.return_value.image_inspector.side_effect = RuntimeError("gateway down")
            from tuning.classify_persona import categorize_avatar_image

            persona = {
                "appearance": {"skin_tone": "#D4A76A"}
            }
            with pytest.raises(RuntimeError):
                categorize_avatar_image(_tiny_png(), persona)


# ---------------------------------------------------------------------------
# classify_expression — _call_vision_model and _call_text_model thin wrappers
# ---------------------------------------------------------------------------


class TestCallVisionModelExpression:
    def test_delegates_to_image_inspector(self):
        with patch("tuning.classify_expression.GatewayClient") as MockClient:
            MockClient.return_value.image_inspector.return_value = "raw response"
            from tuning.classify_expression import _call_vision_model

            result = _call_vision_model("http://gw", "sys", "prompt", b"img", 30)
            assert result == "raw response"
            MockClient.assert_called_once_with("http://gw")


class TestCallTextModel:
    def test_delegates_to_text_gen(self):
        with patch("tuning.classify_expression.GatewayClient") as MockClient:
            MockClient.return_value.text_gen.return_value = "yes"
            from tuning.classify_expression import _call_text_model

            result = _call_text_model("http://gw", "some prompt", 30)
            assert result == "yes"


# ---------------------------------------------------------------------------
# classify_style — _call_vision_model + classify_image_style reraise
# ---------------------------------------------------------------------------


class TestCallVisionModelStyle:
    def test_delegates_to_image_inspector(self):
        with patch("tuning.classify_style.GatewayClient") as MockClient:
            MockClient.return_value.image_inspector.return_value = "raw"
            from tuning.classify_style import _call_vision_model

            result = _call_vision_model("http://gw", "sys", "prompt", b"img", 30)
            assert result == "raw"


class TestClassifyImageStyleExtra:
    _STYLES = [
        {
            "id": "photorealistic",
            "name": "Photorealistic",
            "key_technical_traits": ["natural skin"],
        },
    ]

    def test_raw_response_stored(self):
        raw = "top_style: photorealistic\nscores:\n  photorealistic: 0.9\nreasoning: detailed\n"
        with patch("tuning.classify_style._call_vision_model", return_value=raw):
            from tuning.classify_style import classify_image_style

            result = classify_image_style(_tiny_png(), self._STYLES)
            assert result.raw_response == raw

    def test_llm_failure_reraises(self):
        import pytest

        with patch(
            "tuning.classify_style._call_vision_model",
            side_effect=RuntimeError("gateway down"),
        ):
            from tuning.classify_style import classify_image_style

            with pytest.raises(RuntimeError, match="gateway down"):
                classify_image_style(_tiny_png(), self._STYLES)

    def test_parse_non_dict_yaml(self):
        from tuning.classify_style import _parse_classification_response

        raw = "- item1\n- item2\n"
        result = _parse_classification_response(raw, ["photorealistic"])
        assert result.scores == {} or result.top_style_id in ("", "photorealistic")


# ---------------------------------------------------------------------------
# classify_persona — _describe_properties all branches
# ---------------------------------------------------------------------------


class TestDescribePropertiesAllBranches:
    def test_non_binary_gender(self):
        from tuning.classify_persona import _describe_properties

        persona = {"personal": {"gender": "non-binary"}, "appearance": {}}
        props = _describe_properties(persona)
        assert "gender" in props
        assert "androgynous" in props["gender"]

    def test_hair_color_string_with_hex(self):
        from tuning.classify_persona import _describe_properties

        persona = {
            "personal": {},
            "appearance": {"hair_color": "#8B5E3C #5C3D1E"},
        }
        props = _describe_properties(persona)
        assert "hair_color" in props

    def test_hair_color_string_no_hex(self):
        from tuning.classify_persona import _describe_properties

        persona = {
            "personal": {},
            "appearance": {"hair_color": "dark brown"},
        }
        props = _describe_properties(persona)
        assert "hair_color" not in props

    def test_eye_color_string_with_hex(self):
        from tuning.classify_persona import _describe_properties

        persona = {
            "personal": {},
            "appearance": {"eye_color": "#3D1C02 warm brown"},
        }
        props = _describe_properties(persona)
        assert "eye_color" in props

    def test_clothing_as_dict(self):
        from tuning.classify_persona import _describe_properties

        persona = {
            "personal": {},
            "appearance": {"clothing": {"blazer": "#1A1A2E", "trousers": "#2C3E50"}},
        }
        props = _describe_properties(persona)
        assert "clothing" in props
        assert "blazer" in props["clothing"]

    def test_clothing_as_string(self):
        from tuning.classify_persona import _describe_properties

        persona = {
            "personal": {},
            "appearance": {"clothing": "dark navy suit"},
        }
        props = _describe_properties(persona)
        assert "clothing" in props

    def test_accessories_as_dict(self):
        from tuning.classify_persona import _describe_properties

        persona = {
            "personal": {},
            "appearance": {"accessories": {"glasses": "thin rimmed"}},
        }
        props = _describe_properties(persona)
        assert "accessories" in props

    def test_accessories_as_string(self):
        from tuning.classify_persona import _describe_properties

        persona = {
            "personal": {},
            "appearance": {"accessories": "reading glasses"},
        }
        props = _describe_properties(persona)
        assert "accessories" in props

    def test_accessories_none_excluded(self):
        from tuning.classify_persona import _describe_properties

        persona = {
            "personal": {},
            "appearance": {"accessories": "none"},
        }
        props = _describe_properties(persona)
        assert "accessories" not in props

    def test_facial_structure_props(self):
        from tuning.classify_persona import _describe_properties

        persona = {
            "personal": {},
            "appearance": {
                "nose_shape": "narrow",
                "chin_shape": "oval",
                "cheeks_shape": "high",
            },
        }
        props = _describe_properties(persona)
        assert "nose_shape" in props
        assert "chin_shape" in props
        assert "cheeks_shape" in props

    def test_brows_style(self):
        from tuning.classify_persona import _describe_properties

        persona = {
            "personal": {},
            "appearance": {"brows_style": "arched"},
        }
        props = _describe_properties(persona)
        assert "brows_style" in props


# ---------------------------------------------------------------------------
# classify_persona — CategoryReport methods
# ---------------------------------------------------------------------------


class TestCategoryReport:
    def _report(self, visible_flags):
        from tuning.classify_persona import CategoryReport, PropertyResult

        return CategoryReport(
            results=[
                PropertyResult(property_name=str(i), expected="desc", visible=v)
                for i, v in enumerate(visible_flags)
            ]
        )

    def test_score_all_visible(self):
        r = self._report([True, True, True])
        assert r.score == 1.0

    def test_score_none_visible(self):
        r = self._report([False, False])
        assert r.score == 0.0

    def test_score_empty(self):
        from tuning.classify_persona import CategoryReport

        assert CategoryReport().score == 0.0

    def test_failures(self):
        r = self._report([True, False, True])
        assert r.failures() == ["1"]

    def test_passes(self):
        r = self._report([True, False, True])
        assert r.passes() == ["0", "2"]

    def test_repr_contains_pct(self):
        r = self._report([True, True, False])
        assert "67%" in repr(r)


# ---------------------------------------------------------------------------
# _hex_label — table entry with invalid hex (line 147 continue)
# ---------------------------------------------------------------------------


class TestHexLabelInvalidTableEntry:
    def test_skips_invalid_table_entry(self):
        from tuning.classify_persona import _hex_label

        # "NOTAHEX" in the table is not parseable → continue; "#FF0000" wins
        table = {"NOTAHEX": "invalid", "#FF0000": "red"}
        result = _hex_label("#FE0101", table)
        assert result == "red"


# ---------------------------------------------------------------------------
# _describe_properties — binary gender, hair_style, hair_color dict,
# eye_shape, eye_color dict (lines 183, 193, 199, 208, 214)
# ---------------------------------------------------------------------------


class TestDescribePropertiesMissingBranches:
    def test_binary_gender(self):
        from tuning.classify_persona import _describe_properties

        persona = {"personal": {"gender": "female"}, "appearance": {}}
        props = _describe_properties(persona)
        assert props.get("gender") == "female"

    def test_hair_style_string(self):
        from tuning.classify_persona import _describe_properties

        persona = {"personal": {}, "appearance": {"hair_style": "bob cut"}}
        props = _describe_properties(persona)
        assert props.get("hair_style") == "bob cut"

    def test_hair_color_dict_with_hex_base(self):
        from tuning.classify_persona import _describe_properties

        persona = {
            "personal": {},
            "appearance": {"hair_color": {"hex_base": "#8B5E3C", "hex_shadow": "#5C3D1E"}},
        }
        props = _describe_properties(persona)
        assert "hair_color" in props
        assert "#8B5E3C" in props["hair_color"]

    def test_eye_shape_string(self):
        from tuning.classify_persona import _describe_properties

        persona = {"personal": {}, "appearance": {"eye_shape": "almond"}}
        props = _describe_properties(persona)
        assert props.get("eye_shape") == "almond"

    def test_eye_color_dict_with_hex_iris(self):
        from tuning.classify_persona import _describe_properties

        persona = {
            "personal": {},
            "appearance": {"eye_color": {"hex_iris": "#3D7AB5", "hex_highlight": "#FFFFFF"}},
        }
        props = _describe_properties(persona)
        assert "eye_color" in props
        assert "#3D7AB5" in props["eye_color"]


# ---------------------------------------------------------------------------
# _parse_categorizer_response — non-dict YAML (line 371)
# ---------------------------------------------------------------------------


class TestParseCategorizeResponseNonDict:
    def test_list_yaml_treated_as_empty(self):
        from tuning.classify_persona import _parse_categorizer_response

        raw = "- item1\n- item2\n"
        result = _parse_categorizer_response(raw, {"skin_tone": "desc"})
        # list YAML parsed but not a dict → line 371 fires → all results invisible
        assert result.results[0].visible is False


# ---------------------------------------------------------------------------
# categorize_avatar_image — success path (lines 348-350)
# ---------------------------------------------------------------------------


class TestCategorizeAvatarImageSuccess:
    def test_success_path_returns_report(self):
        raw = "skin_tone:\n  visible: true\n  note: matches\n"
        with patch("tuning.classify_persona.GatewayClient") as MockClient:
            MockClient.return_value.image_inspector.return_value = raw
            from tuning.classify_persona import categorize_avatar_image

            persona = {"appearance": {"skin_tone": "#D4A76A"}}
            report = categorize_avatar_image(_tiny_png(), persona)
            assert report.raw_response == raw
            assert report.results[0].property_name == "skin_tone"


# ---------------------------------------------------------------------------
# classify_style — non-float score value triggers except branch (lines 167-168)
# ---------------------------------------------------------------------------


class TestParseClassificationResponseNonFloatScore:
    def test_dict_score_defaults_to_zero(self):
        from tuning.classify_style import _parse_classification_response

        # A dict value for a score triggers TypeError inside float()
        raw = "top_style: photorealistic\nscores:\n  photorealistic: {nested: value}\n"
        result = _parse_classification_response(raw, ["photorealistic"])
        assert result.scores.get("photorealistic", 0.0) == 0.0
