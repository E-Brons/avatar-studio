"""Tests for Step B — LLM Feature Selection helpers and B2 — Marshal Avatar Persona."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from avatar_studio.pipeline.step_a_randomise_person import _pick_diverse_demographics, _pool_by_gender
from avatar_studio.pipeline.step_b_generate_cv import _generate_advisor_profile
from avatar_studio.pipeline.step_c_select_features import (
    _SIMPLE_FIELDS,
    _build_feature_prompt,
    _format_profile,
    _load_user_prompt_options,
    _marshal_avatar_persona,
    _parse_color_value,
    _parse_feature_response,
    _select_feature_field,
    _warmup_model,
)
from avatar_studio.pipeline.step_c_select_features import build_avatar_charachter as _build_avatar_charachter
from avatar_studio.pipeline.step_c_select_features import select_features as _select_features

pytestmark = pytest.mark.avatar

# ---------------------------------------------------------------------------
# _parse_feature_response
# ---------------------------------------------------------------------------

VALID_YAML = """\
NAME: Maya Chen
SKIN_TONE: "#C9A96E"
HAIR_STYLE: side-parted short
HAIR_COLOR: "#3B2314 #261508"
EYE_SHAPE: almond
EYE_COLOR: "#6B3A1F #0A0A0A"
BROWS_STYLE: soft arch thick
BROWS_COLOR: "#3B2314"
NOSE_SHAPE: soft L-curve
CHIN_SHAPE: soft rounded
CHEEKS_SHAPE: flat and smooth
CLOTHING:
  blazer: "#3C3C3C"
  collared shirt: "#A8C4E0"
ACCESSORIES:
  glasses: thin-frame rectangular
"""


def test_parse_valid_yaml():
    result = _parse_feature_response(VALID_YAML)
    assert result["HAIR_STYLE"] == "side-parted short"
    assert result["CLOTHING"] == {"blazer": "#3C3C3C", "collared shirt": "#A8C4E0"}
    assert result["ACCESSORIES"] == {"glasses": "thin-frame rectangular"}
    assert len(result) == 3


def test_parse_yaml_with_code_fences():
    fenced = f"```yaml\n{VALID_YAML}```"
    result = _parse_feature_response(fenced)
    assert result["HAIR_STYLE"] == "side-parted short"
    assert len(result) == 3


def test_parse_yaml_with_backtick_fences():
    fenced = f"```\n{VALID_YAML}\n```"
    result = _parse_feature_response(fenced)
    assert len(result) == 3


def test_parse_missing_keys():
    incomplete = "SKIN_TONE: warm olive #C9A96E\nHAIR_STYLE: short cropped\n"
    with pytest.raises(ValueError, match="Missing required feature keys"):
        _parse_feature_response(incomplete)


def test_parse_non_dict():
    with pytest.raises(ValueError, match="Expected YAML dict"):
        _parse_feature_response("- item1\n- item2\n")


def test_parse_extra_keys_ignored():
    extra = VALID_YAML + "EXTRA_KEY: should be ignored\n"
    result = _parse_feature_response(extra)
    assert "EXTRA_KEY" not in result
    assert len(result) == 3


BOLD_YAML = VALID_YAML.replace("NAME:", "**NAME:**").replace(
    "SKIN_TONE:", "**SKIN_TONE:**"
).replace("HAIR_STYLE:", "**HAIR_STYLE:**")


def test_parse_yaml_with_markdown_bold_keys():
    """LLMs sometimes wrap keys in **bold** — parser must strip them."""
    result = _parse_feature_response(BOLD_YAML)
    assert result["HAIR_STYLE"] == "side-parted short"
    assert len(result) == 3


# ---------------------------------------------------------------------------
# _parse_color_value
# ---------------------------------------------------------------------------


def test_parse_color_single_hex():
    result = _parse_color_value("SKIN_TONE", "warm olive #C9A96E")
    assert result == "#C9A96E"


def test_parse_color_hair_dual_hex():
    result = _parse_color_value("HAIR_COLOR", "dark brown #3B2314 #261508")
    assert result == {"hex_base": "#3B2314", "hex_shadow": "#261508"}


def test_parse_color_eye_dual_hex():
    result = _parse_color_value("EYE_COLOR", "warm brown #6B3A1F #0A0A0A")
    assert result == {"hex_iris": "#6B3A1F", "hex_pupil": "#0A0A0A"}


def test_parse_color_brows_single_hex():
    result = _parse_color_value("BROWS_COLOR", "dark brown #3B2314")
    assert result == "#3B2314"


def test_parse_color_no_hex():
    result = _parse_color_value("HAIR_STYLE", "side-parted short")
    assert result == "side-parted short"


# ---------------------------------------------------------------------------
# _marshal_avatar_persona
# ---------------------------------------------------------------------------

SAMPLE_ADVISOR = {
    "role": "Financial Advisor",
    "education": ["MBA Finance"],
    "experience": ["10 years wealth management"],
    "traits": ["analytical", "patient"],
}

SAMPLE_DEMOGRAPHICS = {
    "gender": "female",
    "age": 35,
    "name": "Maya Chen",
    "style": "flat-vector-2D",
    "bg_color": "#4A90D9",
    "fg_color": "#FFFFFF",
    "SKIN_TONE": "#C9A96E",
    "HAIR_COLOR": "#3B2314 #261508",
    "EYE_COLOR": "#6B3A1F #0A0A0A",
    "BROWS_COLOR": "#3B2314",
    "EYE_SHAPE": "almond",
    "BROWS_STYLE": "soft arch thick",
    "NOSE_SHAPE": "soft L-curve",
    "CHIN_SHAPE": "soft rounded",
    "CHEEKS_SHAPE": "flat and smooth",
}

SAMPLE_FEATURES = {
    "NAME": "Maya Chen",
    "SKIN_TONE": "#C9A96E",
    "HAIR_STYLE": "shoulder-length wavy",
    "HAIR_COLOR": "#3B2314 #261508",
    "EYE_SHAPE": "almond",
    "EYE_COLOR": "#6B3A1F #0A0A0A",
    "BROWS_STYLE": "soft arch thick",
    "BROWS_COLOR": "#3B2314",
    "NOSE_SHAPE": "soft L-curve",
    "CHIN_SHAPE": "soft rounded",
    "CHEEKS_SHAPE": "flat and smooth",
    "CLOTHING": {"blazer": "#3C3C3C", "collared shirt": "#A8C4E0"},
    "ACCESSORIES": {"glasses": "thin-frame rectangular"},
}


def test_marshal_full_features():
    persona = _marshal_avatar_persona(SAMPLE_DEMOGRAPHICS, SAMPLE_ADVISOR, SAMPLE_FEATURES)

    assert persona["personal"]["gender"] == "female"
    assert persona["personal"]["age"] == 35
    assert persona["style"]["bg_color"] == "#4A90D9"
    assert persona["style"]["fg_color"] == "#FFFFFF"
    assert persona["personal"]["name"] == "Maya Chen"
    assert persona["advisor"]["role"] == "Financial Advisor"
    assert persona["advisor"]["education"] == ["MBA Finance"]
    assert persona["advisor"]["traits"] == ["analytical", "patient"]

    app = persona["appearance"]
    assert app["skin_tone"] == "#C9A96E"
    assert app["hair_style"] == "shoulder-length wavy"
    assert app["hair_color"] == {"hex_base": "#3B2314", "hex_shadow": "#261508"}
    assert app["eye_shape"] == "almond"
    assert app["eye_color"] == {"hex_iris": "#6B3A1F", "hex_pupil": "#0A0A0A"}
    assert app["brows_color"] == "#3B2314"
    assert app["clothing"] == {"blazer": "#3C3C3C", "collared shirt": "#A8C4E0"}
    assert app["accessories"] == {"glasses": "thin-frame rectangular"}
    # NAME must NOT appear in appearance (it belongs in personal)
    assert "name" not in app


def test_marshal_none_features():
    persona = _marshal_avatar_persona(SAMPLE_DEMOGRAPHICS, SAMPLE_ADVISOR, None)

    assert persona["personal"]["gender"] == "female"
    assert persona["advisor"]["role"] == "Financial Advisor"
    assert persona["appearance"] == {}


# ---------------------------------------------------------------------------
# _build_feature_prompt
# ---------------------------------------------------------------------------


def test_build_feature_prompt_substitution():
    """Feature prompt templates should substitute demographics and advisor fields."""
    system_msg, user_msg = _build_feature_prompt(SAMPLE_DEMOGRAPHICS, SAMPLE_ADVISOR)
    assert "female" in user_msg
    assert "35" in user_msg
    assert "Financial Advisor" in user_msg
    assert "analytical" in user_msg
    # Appearance is no longer passed to the prompt
    assert "{ APPEARANCE_ID }" not in user_msg
    # System message should be non-empty
    assert len(system_msg) > 0


# ---------------------------------------------------------------------------
# _select_features (mocked litellm — per-field call pattern)
# ---------------------------------------------------------------------------

# Per-field responses — NAME, colors, and shape fields are now pre-seeded from
# §A demographics.  Only 3 LLM-selected fields remain.
_PER_FIELD_RESPONSES = [
    "side-parted short",                                    # HAIR_STYLE
    'blazer over blouse: "#3C3C3C"\nsilk blouse: "#A8C4E0"',  # CLOTHING (YAML dict)
    "glasses: thin-frame rectangular",                      # ACCESSORIES (YAML dict)
]


def _make_llm_response(content: str):
    """Helper: build a mock litellm response with given content."""
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    return resp


def _make_per_field_side_effect():
    """Build a side_effect list: 1 warmup + 3 per-field responses."""
    warmup = _make_llm_response("ok")
    return [warmup] + [_make_llm_response(r) for r in _PER_FIELD_RESPONSES]


def test_select_features_success():
    """Step B should parse per-field LLM responses into the feature dict."""
    side_effect = _make_per_field_side_effect()

    with patch("avatar_studio.pipeline.step_c_select_features.litellm.completion", side_effect=side_effect) as mock_completion:
        result = _select_features(
            SAMPLE_DEMOGRAPHICS,
            SAMPLE_ADVISOR,
            ollama_text_model="ollama/llama3.1",
            ollama_text_model_api_base="http://localhost:11434",
        )

    assert result is not None
    # NAME and all phenotype fields come from §A demographics (SAMPLE_DEMOGRAPHICS)
    assert result["NAME"] == "Maya Chen"
    assert result["SKIN_TONE"] == "#C9A96E"
    assert result["HAIR_COLOR"] == "#3B2314 #261508"
    assert result["EYE_COLOR"] == "#6B3A1F #0A0A0A"
    assert result["BROWS_COLOR"] == "#3B2314"
    assert result["EYE_SHAPE"] == "almond"
    assert result["BROWS_STYLE"] == "soft arch thick"
    assert result["NOSE_SHAPE"] == "soft L-curve"
    assert result["CHIN_SHAPE"] == "soft rounded"
    assert result["CHEEKS_SHAPE"] == "flat and smooth"
    # Presentation fields are LLM-selected
    assert result["HAIR_STYLE"] == "side-parted short"
    assert result["CLOTHING"] == {"blazer over blouse": "#3C3C3C", "silk blouse": "#A8C4E0"}
    assert result["ACCESSORIES"] == {"glasses": "thin-frame rectangular"}

    # 1 warmup + 3 field calls = 4 total (NAME + colors + shapes pre-seeded from §A)
    assert mock_completion.call_count == 4

    # Verify model and api_base on the first field call (index 1 = HAIR_STYLE, after warmup)
    call_kwargs = mock_completion.call_args_list[1][1]
    assert call_kwargs["model"] == "ollama/llama3.1"
    assert call_kwargs["api_base"] == "http://localhost:11434"
    assert call_kwargs["temperature"] == 0.5
    assert call_kwargs["timeout"] == 30


def test_select_features_retry_on_empty_response():
    """Step C should retry a field when the LLM returns empty content."""
    warmup = _make_llm_response("ok")
    empty_resp = _make_llm_response("")
    good_hair = _make_llm_response("side-parted short")
    # Empty first, then good on retry for HAIR_STYLE, then rest of fields normal
    rest = [_make_llm_response(r) for r in _PER_FIELD_RESPONSES[1:]]

    with patch("avatar_studio.pipeline.step_c_select_features.litellm.completion", side_effect=[warmup, empty_resp, good_hair] + rest) as mock_completion:
        result = _select_features(
            SAMPLE_DEMOGRAPHICS,
            SAMPLE_ADVISOR,
            ollama_text_model="ollama/llama3.1",
        )

    assert result["HAIR_STYLE"] == "side-parted short"
    # 1 warmup + 1 empty + 1 good HAIR_STYLE + 2 other fields = 5
    assert mock_completion.call_count == 5


def test_select_features_exhausts_retries():
    """Step C should raise after max_retries of empty responses for a field."""
    warmup = _make_llm_response("ok")
    empty = _make_llm_response("")

    with patch("avatar_studio.pipeline.step_c_select_features.litellm.completion", side_effect=[warmup] + [empty] * 10):
        with pytest.raises(ValueError, match="Failed to select HAIR_STYLE"):
            _select_features(
                SAMPLE_DEMOGRAPHICS,
                SAMPLE_ADVISOR,
                ollama_text_model="ollama/llama3.1",
                max_retries=10,
            )


def test_select_features_llm_error_raises():
    """Step B should raise when the LLM call itself fails (warmup succeeds, first field fails)."""
    warmup = _make_llm_response("ok")

    with patch("avatar_studio.pipeline.step_c_select_features.litellm.completion", side_effect=[warmup, RuntimeError("connection refused")]):
        with pytest.raises(RuntimeError, match="connection refused"):
            _select_features(
                SAMPLE_DEMOGRAPHICS,
                SAMPLE_ADVISOR,
                ollama_text_model="ollama/llama3.1",
                max_retries=1,
            )


def test_select_features_no_api_base():
    """Step B should not set api_base when ollama_text_model_api_base is None."""
    side_effect = _make_per_field_side_effect()

    with patch("avatar_studio.pipeline.step_c_select_features.litellm.completion", side_effect=side_effect) as mock_completion:
        _select_features(
            SAMPLE_DEMOGRAPHICS,
            SAMPLE_ADVISOR,
            ollama_text_model="ollama/llama3.1",
            ollama_text_model_api_base=None,
        )

    # Check a field call (not warmup) has no api_base
    call_kwargs = mock_completion.call_args_list[1][1]
    assert "api_base" not in call_kwargs


def test_select_features_context_accumulates():
    """Later field prompts should include the marshalled persona from earlier picks."""
    side_effect = _make_per_field_side_effect()

    with patch("avatar_studio.pipeline.step_c_select_features.litellm.completion", side_effect=side_effect) as mock_completion:
        _select_features(
            SAMPLE_DEMOGRAPHICS,
            SAMPLE_ADVISOR,
            ollama_text_model="ollama/llama3.1",
        )

    # The HAIR_STYLE field call (index 1, after warmup) should contain the
    # marshalled persona built from the pre-seeded §A demographics.
    hair_style_call = mock_completion.call_args_list[1]
    user_msg = hair_style_call[1]["messages"][1]["content"]
    assert "Maya Chen" in user_msg
    assert "skin_tone" in user_msg
    assert "Current persona so far" in user_msg


def test_warmup_failure_does_not_block():
    """Warmup failure should not prevent feature selection."""
    field_responses = [_make_llm_response(r) for r in _PER_FIELD_RESPONSES]

    def warmup_fails_then_fields(*args, **kwargs):
        # Can't use side_effect easily here, so use a different approach
        pass

    side_effect = [RuntimeError("warmup failed")] + field_responses

    with patch("avatar_studio.pipeline.step_c_select_features.litellm.completion", side_effect=side_effect):
        result = _select_features(
            SAMPLE_DEMOGRAPHICS,
            SAMPLE_ADVISOR,
            ollama_text_model="ollama/llama3.1",
        )

    assert result["NAME"] == "Maya Chen"
    assert len(result) == 13


# ---------------------------------------------------------------------------
# _select_feature_field unit tests
# ---------------------------------------------------------------------------


def test_select_feature_field_simple():
    """A simple field should return a matching option value."""
    resp = _make_llm_response("side-parted short")
    with patch("avatar_studio.pipeline.step_c_select_features.litellm.completion", return_value=resp):
        result = _select_feature_field(
            "HAIR_STYLE", "Gender: female\nAge: 35\nAppearance: olive\nRole: Advisor",
            "system prompt", ["short cropped", "side-parted short", "swept back"], {},
            SAMPLE_DEMOGRAPHICS, SAMPLE_ADVISOR,
            ollama_text_model="ollama/test",
        )
    assert result == "side-parted short"


def test_select_feature_field_name():
    """NAME field should strip quotes and return the name."""
    resp = _make_llm_response('"Elena Vasquez"')
    with patch("avatar_studio.pipeline.step_c_select_features.litellm.completion", return_value=resp):
        result = _select_feature_field(
            "NAME", "profile", "system", None, {},
            SAMPLE_DEMOGRAPHICS, SAMPLE_ADVISOR,
            ollama_text_model="ollama/test",
        )
    assert result == "Elena Vasquez"


def test_select_feature_field_clothing_yaml():
    """CLOTHING should parse YAML dict response."""
    resp = _make_llm_response('blazer: "#3C3C3C"\nshirt: "#A8C4E0"')
    with patch("avatar_studio.pipeline.step_c_select_features.litellm.completion", return_value=resp):
        result = _select_feature_field(
            "CLOTHING", "profile", "system", ["blazer", "shirt"], {},
            SAMPLE_DEMOGRAPHICS, SAMPLE_ADVISOR,
            ollama_text_model="ollama/test",
        )
    assert result == {"blazer": "#3C3C3C", "shirt": "#A8C4E0"}


def test_select_feature_field_accessories_none():
    """ACCESSORIES with 'none' response should return empty dict."""
    resp = _make_llm_response("none")
    with patch("avatar_studio.pipeline.step_c_select_features.litellm.completion", return_value=resp):
        result = _select_feature_field(
            "ACCESSORIES", "profile", "system", ["glasses", "earring"], {},
            SAMPLE_DEMOGRAPHICS, SAMPLE_ADVISOR,
            ollama_text_model="ollama/test",
        )
    assert result == {}


def test_select_feature_field_accessories_yaml_list():
    """ACCESSORIES returned as YAML list items should be merged into a dict."""
    resp = _make_llm_response("- glasses: thin-frame rectangular\n- earring: small gold stud")
    with patch("avatar_studio.pipeline.step_c_select_features.litellm.completion", return_value=resp):
        result = _select_feature_field(
            "ACCESSORIES", "profile", "system", ["glasses", "earring"], {},
            SAMPLE_DEMOGRAPHICS, SAMPLE_ADVISOR,
            ollama_text_model="ollama/test",
        )
    assert result == {"glasses": "thin-frame rectangular", "earring": "small gold stud"}


def test_select_feature_field_clothing_trailing_garbage():
    """CLOTHING response with trailing non-YAML text should still parse."""
    resp = _make_llm_response('blazer: "#3C3C3C"\nshirt: "#A8C4E0"\n\nyou are: a senior graphics designer')
    with patch("avatar_studio.pipeline.step_c_select_features.litellm.completion", return_value=resp):
        result = _select_feature_field(
            "CLOTHING", "profile", "system", ["blazer", "shirt"], {},
            SAMPLE_DEMOGRAPHICS, SAMPLE_ADVISOR,
            ollama_text_model="ollama/test",
        )
    assert result == {"blazer": "#3C3C3C", "shirt": "#A8C4E0"}


def test_select_feature_field_filters_none_values():
    """ACCESSORIES with 'none' values should be filtered out."""
    resp = _make_llm_response("glasses: thin-frame rectangular\nearring: none")
    with patch("avatar_studio.pipeline.step_c_select_features.litellm.completion", return_value=resp):
        result = _select_feature_field(
            "ACCESSORIES", "profile", "system", ["glasses", "earring"], {},
            SAMPLE_DEMOGRAPHICS, SAMPLE_ADVISOR,
            ollama_text_model="ollama/test",
        )
    assert result == {"glasses": "thin-frame rectangular"}
    assert "earring" not in result


# ---------------------------------------------------------------------------
# Pipeline wiring test: _select_features → _build_avatar_charachter
#
# This catches the real bug: Stage B returning valid features but the
# persona ending up with empty appearance because of wiring failures.
# ---------------------------------------------------------------------------


def test_pipeline_features_to_avatar_persona():
    """Full pipeline: mocked per-field LLM → features → avatar_persona with name + appearance."""
    side_effect = _make_per_field_side_effect()

    with patch("avatar_studio.pipeline.step_c_select_features.litellm.completion", side_effect=side_effect):
        features = _select_features(
            SAMPLE_DEMOGRAPHICS,
            SAMPLE_ADVISOR,
            ollama_text_model="ollama/llama3.1:8b",
        )

    assert features is not None, "features must not be None"

    avatar = _build_avatar_charachter(SAMPLE_ADVISOR, SAMPLE_DEMOGRAPHICS, features)
    persona = avatar["avatar_persona"]

    # Name must be present in personal section
    assert persona["personal"].get("name"), "personal.name must be set by Stage B"

    # Appearance must be non-empty with all visual keys
    appearance = persona.get("appearance", {})
    assert len(appearance) >= 12, (
        f"appearance has only {len(appearance)} keys — "
        f"expected 12+. Stage B features did not flow through. "
        f"Keys present: {list(appearance.keys())}"
    )

    # Spot-check a few critical fields
    assert "skin_tone" in appearance
    assert "hair_style" in appearance
    assert "clothing" in appearance


def test_pipeline_features_none_gives_empty_appearance():
    """When features is None (LLM failed), appearance must be empty dict, not crash."""
    avatar = _build_avatar_charachter(SAMPLE_ADVISOR, SAMPLE_DEMOGRAPHICS, None)
    persona = avatar["avatar_persona"]

    assert persona["appearance"] == {}
    assert "name" not in persona["advisor"]


# ---------------------------------------------------------------------------
# _generate_advisor_profile
# ---------------------------------------------------------------------------

_PROFILE_YAML_RESPONSE = """\
education:
  - MBA Finance
  - CFA Level III
experience:
  - 10 years wealth management
  - 5 years private banking
traits:
  - analytical
  - patient
  - detail-oriented
"""


def test_generate_advisor_profile_success():
    """Profile generation should parse YAML response with education/experience/traits."""
    resp = _make_llm_response(_PROFILE_YAML_RESPONSE)
    with patch("avatar_studio.pipeline.step_b_generate_cv.litellm.completion", return_value=resp):
        result = _generate_advisor_profile(
            "Financial Advisor",
            SAMPLE_DEMOGRAPHICS,
            ollama_text_model="ollama/test",
        )

    assert result["education"] == ["MBA Finance", "CFA Level III"]
    assert result["experience"] == ["10 years wealth management", "5 years private banking"]
    assert result["traits"] == ["analytical", "patient", "detail-oriented"]


def test_generate_advisor_profile_with_code_fences():
    """Profile generation should strip code fences."""
    resp = _make_llm_response(f"```yaml\n{_PROFILE_YAML_RESPONSE}```")
    with patch("avatar_studio.pipeline.step_b_generate_cv.litellm.completion", return_value=resp):
        result = _generate_advisor_profile(
            "Advisor",
            SAMPLE_DEMOGRAPHICS,
            ollama_text_model="ollama/test",
        )
    assert len(result["education"]) == 2
    assert len(result["traits"]) == 3


def test_generate_advisor_profile_truncates_long_lists():
    """Education and experience are capped at 2 items, traits at 3."""
    yaml_resp = """\
education:
  - MBA
  - CFA
  - PhD Economics
experience:
  - 10 years banking
  - 5 years consulting
  - 3 years audit
traits:
  - analytical
  - patient
  - precise
  - empathetic
"""
    resp = _make_llm_response(yaml_resp)
    with patch("avatar_studio.pipeline.step_b_generate_cv.litellm.completion", return_value=resp):
        result = _generate_advisor_profile(
            "Advisor",
            SAMPLE_DEMOGRAPHICS,
            ollama_text_model="ollama/test",
        )
    assert len(result["education"]) == 2
    assert len(result["experience"]) == 3  # capped at 3
    assert len(result["traits"]) == 3


def test_generate_advisor_profile_retry_on_empty():
    """Profile generation should retry on empty response."""
    empty = _make_llm_response("")
    good = _make_llm_response(_PROFILE_YAML_RESPONSE)
    with patch("avatar_studio.pipeline.step_b_generate_cv.litellm.completion", side_effect=[empty, good]) as mock:
        result = _generate_advisor_profile(
            "Advisor",
            SAMPLE_DEMOGRAPHICS,
            ollama_text_model="ollama/test",
        )
    assert result["education"] == ["MBA Finance", "CFA Level III"]
    assert mock.call_count == 2


def test_generate_advisor_profile_exhausts_retries():
    """Profile generation should raise after max retries."""
    empty = _make_llm_response("")
    with patch("avatar_studio.pipeline.step_b_generate_cv.litellm.completion", return_value=empty):
        with pytest.raises(ValueError, match="Failed to generate advisor profile"):
            _generate_advisor_profile(
                "Advisor",
                SAMPLE_DEMOGRAPHICS,
                ollama_text_model="ollama/test",
                max_retries=3,
            )


def test_generate_advisor_profile_missing_fields_retries():
    """Profile generation retries when required fields are missing."""
    missing = _make_llm_response("education:\n  - MBA\n")
    good = _make_llm_response(_PROFILE_YAML_RESPONSE)
    with patch("avatar_studio.pipeline.step_b_generate_cv.litellm.completion", side_effect=[missing, good]) as mock:
        result = _generate_advisor_profile(
            "Advisor",
            SAMPLE_DEMOGRAPHICS,
            ollama_text_model="ollama/test",
        )
    assert mock.call_count == 2
    assert len(result["traits"]) == 3


# ---------------------------------------------------------------------------
# _pick_diverse_demographics
# ---------------------------------------------------------------------------


def test_diverse_demographics_returns_correct_count():
    result = _pick_diverse_demographics(4)
    assert len(result) == 4


def test_diverse_demographics_gender_coverage():
    """All 3 genders appear at least once."""
    result = _pick_diverse_demographics(4)
    genders = {d["gender"] for d in result}
    assert "male" in genders
    assert "female" in genders
    assert "non-binary" in genders


def test_diverse_demographics_age_group_coverage():
    """At least 3 distinct age groups are represented."""
    result = _pick_diverse_demographics(4)
    age_groups = set()
    for d in result:
        age = d["age"]
        if 25 <= age <= 35:
            age_groups.add("25-35")
        elif 36 <= age <= 45:
            age_groups.add("36-45")
        elif 46 <= age <= 55:
            age_groups.add("46-55")
        elif 56 <= age <= 70:
            age_groups.add("56-70")
    assert len(age_groups) >= 3


def test_diverse_demographics_skin_tones_distinct():
    """All 4 skin tones are distinct."""
    result = _pick_diverse_demographics(4)
    skin_tones = [d["SKIN_TONE"] for d in result]
    assert len(set(skin_tones)) == 4


def test_diverse_demographics_has_required_keys():
    """Each demographics dict has all required keys."""
    result = _pick_diverse_demographics(4)
    required = {"gender", "age", "name", "style", "bg_color", "fg_color",
                "SKIN_TONE", "HAIR_COLOR", "EYE_COLOR", "BROWS_COLOR"}
    for d in result:
        assert required.issubset(d.keys())


def test_diverse_demographics_stability():
    """Run 50 times — diversity constraints hold every time."""
    for _ in range(50):
        result = _pick_diverse_demographics(4)
        genders = {d["gender"] for d in result}
        assert len(genders) >= 3
        skin_tones = [d["SKIN_TONE"] for d in result]
        assert len(set(skin_tones)) == 4


# ---------------------------------------------------------------------------
# hard_type_gender — _pool_by_gender strict-bucket mode
# ---------------------------------------------------------------------------

_SAMPLE_BUCKETED = {
    "male": ["m1", "m2"],
    "female": ["f1", "f2"],
    "neutral": ["n1", "n2"],
}


def test_pool_by_gender_default_male_includes_neutral():
    pool = _pool_by_gender(_SAMPLE_BUCKETED, "male")
    assert "m1" in pool and "n1" in pool
    assert "f1" not in pool


def test_pool_by_gender_default_female_includes_neutral():
    pool = _pool_by_gender(_SAMPLE_BUCKETED, "female")
    assert "f1" in pool and "n1" in pool
    assert "m1" not in pool


def test_pool_by_gender_default_nonbinary_includes_all():
    pool = _pool_by_gender(_SAMPLE_BUCKETED, "non-binary")
    assert "m1" in pool and "f1" in pool and "n1" in pool


def test_pool_by_gender_hard_type_male_only():
    pool = _pool_by_gender(_SAMPLE_BUCKETED, "male", hard_type=True)
    assert pool == ["m1", "m2"]
    assert "n1" not in pool
    assert "f1" not in pool


def test_pool_by_gender_hard_type_female_only():
    pool = _pool_by_gender(_SAMPLE_BUCKETED, "female", hard_type=True)
    assert pool == ["f1", "f2"]
    assert "n1" not in pool
    assert "m1" not in pool


def test_pool_by_gender_hard_type_nonbinary_neutral_only():
    pool = _pool_by_gender(_SAMPLE_BUCKETED, "non-binary", hard_type=True)
    assert pool == ["n1", "n2"]
    assert "m1" not in pool
    assert "f1" not in pool


def test_pool_by_gender_flat_list_unaffected_by_hard_type():
    """Plain list inputs are returned as-is regardless of hard_type."""
    flat = ["a", "b", "c"]
    assert _pool_by_gender(flat, "male", hard_type=True) == flat
    assert _pool_by_gender(flat, "male", hard_type=False) == flat


# ---------------------------------------------------------------------------
# hard_type_gender — _load_user_prompt_options strict-bucket mode
# ---------------------------------------------------------------------------


def test_load_user_prompt_options_default_male_has_neutral_entries():
    """Default mode: male options include both male and neutral items."""
    opts = _load_user_prompt_options("male")
    # At least one list must be non-empty (settings must have male/neutral data)
    non_empty = [v for v in opts.values() if v]
    assert non_empty, "Expected at least one non-empty option list"


def test_load_user_prompt_options_hard_type_male_excludes_female():
    """Hard-type male: options must not contain items from female bucket."""
    opts_default = _load_user_prompt_options("male", hard_type=False)
    opts_hard = _load_user_prompt_options("male", hard_type=True)
    # Hard-typed pool must be a subset of (or equal to) the default pool
    for key in opts_hard:
        for item in opts_hard[key]:
            assert item in opts_default[key], (
                f"{key}: hard-type item '{item}' not in default pool"
            )


def test_load_user_prompt_options_hard_type_female_excludes_male():
    """Hard-type female: options must not contain items from male bucket."""
    opts_default = _load_user_prompt_options("female", hard_type=False)
    opts_hard = _load_user_prompt_options("female", hard_type=True)
    for key in opts_hard:
        for item in opts_hard[key]:
            assert item in opts_default[key], (
                f"{key}: hard-type item '{item}' not in default pool"
            )


def test_load_user_prompt_options_hard_type_nonbinary_is_subset_of_default():
    """Hard-type non-binary: options must be a subset of the default (all-buckets) pool."""
    opts_default = _load_user_prompt_options("non-binary", hard_type=False)
    opts_hard = _load_user_prompt_options("non-binary", hard_type=True)
    for key in opts_hard:
        for item in opts_hard[key]:
            assert item in opts_default[key], (
                f"{key}: hard-type non-binary item '{item}' not in default pool"
            )


def test_load_user_prompt_options_hard_type_reduces_or_equals_pool():
    """Hard-typed pool is never larger than the default pool for any gender."""
    for gender in ("male", "female", "non-binary"):
        opts_default = _load_user_prompt_options(gender, hard_type=False)
        opts_hard = _load_user_prompt_options(gender, hard_type=True)
        for key in opts_hard:
            assert len(opts_hard[key]) <= len(opts_default[key]), (
                f"{key}/{gender}: hard-type pool ({len(opts_hard[key])}) "
                f"larger than default pool ({len(opts_default[key])})"
            )
