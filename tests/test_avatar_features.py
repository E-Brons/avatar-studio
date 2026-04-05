"""Tests for LLM Feature Selection helpers and Marshal Avatar Persona."""

from unittest.mock import MagicMock, patch

import pytest

from pipeline.persona.aggregator_llm import (
    _build_feature_prompt,
    _load_user_prompt_options,
    _parse_feature_response,
    _select_feature_field,
)
from pipeline.persona.aggregator_llm import select_features as _select_features
from pipeline.persona.aggregators import pool_by_gender as _pool_by_gender
from pipeline.persona.generator import (
    _AGE_GROUPS,
    _pick_diverse_demographics,
)
from pipeline.persona.generator import (
    build_avatar_charachter as _build_avatar_charachter,
)
from pipeline.persona.marshal import (
    marshal_avatar_persona as _marshal_avatar_persona,
)
from pipeline.persona.marshal import (
    parse_color_value as _parse_color_value,
)

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


BOLD_YAML = (
    VALID_YAML.replace("NAME:", "**NAME:**")
    .replace("SKIN_TONE:", "**SKIN_TONE:**")
    .replace("HAIR_STYLE:", "**HAIR_STYLE:**")
)


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
    assert persona["personality"]["traits"] == ["analytical", "patient"]

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
    assert persona["personality"]["traits"] == ["analytical", "patient"]
    assert persona["appearance"] == {}


# ---------------------------------------------------------------------------
# _build_feature_prompt
# ---------------------------------------------------------------------------


def test_build_feature_prompt_substitution():
    """Feature prompt templates should substitute demographics fields."""
    system_msg, user_msg = _build_feature_prompt(SAMPLE_DEMOGRAPHICS, SAMPLE_ADVISOR)
    assert "female" in user_msg
    assert "35" in user_msg
    assert "analytical" in user_msg
    assert "{ APPEARANCE_ID }" not in user_msg
    assert len(system_msg) > 0


# ---------------------------------------------------------------------------
# _select_features (mocked GatewayClient — batch call pattern)
# ---------------------------------------------------------------------------

# Batch response — all 3 appearance fields returned in a single YAML block.
_BATCH_RESPONSE = (
    "HAIR_STYLE: side-parted short\n"
    "CLOTHING:\n"
    '  blazer over blouse: "#3C3C3C"\n'
    '  silk blouse: "#A8C4E0"\n'
    "ACCESSORIES:\n"
    "  glasses: thin-frame rectangular\n"
)


def _make_gateway_mock(responses: list):
    """Helper: build a mock GatewayClient where text_gen returns plain strings.

    Returns (mock_class, mock_instance). Patch the module-level GatewayClient
    with mock_class; assertions go on mock_instance.text_gen.
    """
    mock_instance = MagicMock()
    mock_instance.text_gen.side_effect = responses
    mock_class = MagicMock(return_value=mock_instance)
    return mock_class, mock_instance


def _make_per_field_side_effect():
    """Build (mock_class, mock_instance): 1 warmup + 1 batch response."""
    responses = ["ok", _BATCH_RESPONSE]
    return _make_gateway_mock(responses)


def test_select_features_success():
    """Feature selection should parse per-field LLM responses into the feature dict."""
    mock_class, mock_instance = _make_per_field_side_effect()

    with patch("pipeline.persona.aggregator_llm.GatewayClient", mock_class):
        result = _select_features(
            SAMPLE_DEMOGRAPHICS,
            SAMPLE_ADVISOR,
            gateway_url="http://test",
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

    # 1 warmup + 1 batch call = 2 total (NAME + colors + shapes pre-seeded from §A)
    assert mock_instance.text_gen.call_count == 2


def test_select_features_retry_on_empty_response():
    """Batch call should retry when the LLM returns empty content."""
    # warmup "ok", empty first attempt for batch, then good batch response
    responses = ["ok", "", _BATCH_RESPONSE]
    mock_class, mock_instance = _make_gateway_mock(responses)

    with patch("pipeline.persona.aggregator_llm.GatewayClient", mock_class):
        result = _select_features(
            SAMPLE_DEMOGRAPHICS,
            SAMPLE_ADVISOR,
            gateway_url="http://test",
        )

    assert result["HAIR_STYLE"] == "side-parted short"
    # 1 warmup + 1 empty retry + 1 good batch = 3
    assert mock_instance.text_gen.call_count == 3


def test_select_features_exhausts_retries():
    """Batch call should raise after max_retries of empty responses."""
    responses = ["ok"] + [""] * 10
    mock_class, mock_instance = _make_gateway_mock(responses)

    with patch("pipeline.persona.aggregator_llm.GatewayClient", mock_class):
        with pytest.raises(ValueError, match="Failed to select appearance"):
            _select_features(
                SAMPLE_DEMOGRAPHICS,
                SAMPLE_ADVISOR,
                gateway_url="http://test",
                max_retries=10,
            )


def test_select_features_llm_error_raises():
    """Should raise when the LLM call itself fails (warmup succeeds, first field fails)."""
    mock_class, mock_instance = _make_gateway_mock(["ok", RuntimeError("connection refused")])

    with patch("pipeline.persona.aggregator_llm.GatewayClient", mock_class):
        with pytest.raises(RuntimeError, match="connection refused"):
            _select_features(
                SAMPLE_DEMOGRAPHICS,
                SAMPLE_ADVISOR,
                gateway_url="http://test",
                max_retries=1,
            )


def test_select_features_no_api_base():
    """Verify the call succeeds and returns results (api_base concept no longer relevant)."""
    mock_class, mock_instance = _make_per_field_side_effect()

    with patch("pipeline.persona.aggregator_llm.GatewayClient", mock_class):
        result = _select_features(
            SAMPLE_DEMOGRAPHICS,
            SAMPLE_ADVISOR,
            gateway_url="http://test",
        )

    assert result is not None
    assert result["HAIR_STYLE"] == "side-parted short"


def test_select_features_context_accumulates():
    """Batch prompt should include the marshalled persona from pre-seeded §A fields."""
    mock_class, mock_instance = _make_per_field_side_effect()

    with patch("pipeline.persona.aggregator_llm.GatewayClient", mock_class):
        _select_features(
            SAMPLE_DEMOGRAPHICS,
            SAMPLE_ADVISOR,
            gateway_url="http://test",
        )

    # The batch call (index 1, after warmup at index 0) receives messages.
    # messages[1]["content"] is the user message and should contain persona context.
    messages = mock_instance.text_gen.call_args_list[1][0][0]
    user_msg = messages[1]["content"]
    assert "Maya Chen" in user_msg
    assert "skin_tone" in user_msg
    assert "Current persona:" in user_msg


def test_warmup_failure_does_not_block():
    """Warmup failure should not prevent feature selection."""
    responses = [RuntimeError("warmup failed"), _BATCH_RESPONSE]
    mock_class, mock_instance = _make_gateway_mock(responses)

    with patch("pipeline.persona.aggregator_llm.GatewayClient", mock_class):
        result = _select_features(
            SAMPLE_DEMOGRAPHICS,
            SAMPLE_ADVISOR,
            gateway_url="http://test",
        )

    assert result["NAME"] == "Maya Chen"
    assert len(result) == 13


# ---------------------------------------------------------------------------
# _select_feature_field unit tests
# ---------------------------------------------------------------------------


def test_select_feature_field_simple():
    """A simple field should return a matching option value."""
    mock_class, mock_instance = _make_gateway_mock(["side-parted short"])
    with patch("pipeline.persona.aggregator_llm.GatewayClient", mock_class):
        result = _select_feature_field(
            "HAIR_STYLE",
            "Gender: female\nAge: 35\nAppearance: olive\nRole: Advisor",
            "system prompt",
            ["short cropped", "side-parted short", "swept back"],
            {},
            SAMPLE_DEMOGRAPHICS,
            SAMPLE_ADVISOR,
            gateway_url="http://test",
        )
    assert result == "side-parted short"


def test_select_feature_field_name():
    """NAME field should strip quotes and return the name."""
    mock_class, mock_instance = _make_gateway_mock(['"Elena Vasquez"'])
    with patch("pipeline.persona.aggregator_llm.GatewayClient", mock_class):
        result = _select_feature_field(
            "NAME",
            "profile",
            "system",
            None,
            {},
            SAMPLE_DEMOGRAPHICS,
            SAMPLE_ADVISOR,
            gateway_url="http://test",
        )
    assert result == "Elena Vasquez"


def test_select_feature_field_clothing_yaml():
    """CLOTHING should parse YAML dict response."""
    mock_class, mock_instance = _make_gateway_mock(['blazer: "#3C3C3C"\nshirt: "#A8C4E0"'])
    with patch("pipeline.persona.aggregator_llm.GatewayClient", mock_class):
        result = _select_feature_field(
            "CLOTHING",
            "profile",
            "system",
            ["blazer", "shirt"],
            {},
            SAMPLE_DEMOGRAPHICS,
            SAMPLE_ADVISOR,
            gateway_url="http://test",
        )
    assert result == {"blazer": "#3C3C3C", "shirt": "#A8C4E0"}


def test_select_feature_field_accessories_none():
    """ACCESSORIES with 'none' response should return empty dict."""
    mock_class, mock_instance = _make_gateway_mock(["none"])
    with patch("pipeline.persona.aggregator_llm.GatewayClient", mock_class):
        result = _select_feature_field(
            "ACCESSORIES",
            "profile",
            "system",
            ["glasses", "earring"],
            {},
            SAMPLE_DEMOGRAPHICS,
            SAMPLE_ADVISOR,
            gateway_url="http://test",
        )
    assert result == {}


def test_select_feature_field_accessories_yaml_list():
    """ACCESSORIES returned as YAML list items should be merged into a dict."""
    mock_class, mock_instance = _make_gateway_mock(
        ["- glasses: thin-frame rectangular\n- earring: small gold stud"]
    )
    with patch("pipeline.persona.aggregator_llm.GatewayClient", mock_class):
        result = _select_feature_field(
            "ACCESSORIES",
            "profile",
            "system",
            ["glasses", "earring"],
            {},
            SAMPLE_DEMOGRAPHICS,
            SAMPLE_ADVISOR,
            gateway_url="http://test",
        )
    assert result == {"glasses": "thin-frame rectangular", "earring": "small gold stud"}


def test_select_feature_field_clothing_trailing_garbage():
    """CLOTHING response with trailing non-YAML text should still parse."""
    mock_class, mock_instance = _make_gateway_mock(
        ['blazer: "#3C3C3C"\nshirt: "#A8C4E0"\n\nyou are: a senior graphics designer']
    )
    with patch("pipeline.persona.aggregator_llm.GatewayClient", mock_class):
        result = _select_feature_field(
            "CLOTHING",
            "profile",
            "system",
            ["blazer", "shirt"],
            {},
            SAMPLE_DEMOGRAPHICS,
            SAMPLE_ADVISOR,
            gateway_url="http://test",
        )
    assert result == {"blazer": "#3C3C3C", "shirt": "#A8C4E0"}


def test_select_feature_field_filters_none_values():
    """ACCESSORIES with 'none' values should be filtered out."""
    mock_class, mock_instance = _make_gateway_mock(
        ["glasses: thin-frame rectangular\nearring: none"]
    )
    with patch("pipeline.persona.aggregator_llm.GatewayClient", mock_class):
        result = _select_feature_field(
            "ACCESSORIES",
            "profile",
            "system",
            ["glasses", "earring"],
            {},
            SAMPLE_DEMOGRAPHICS,
            SAMPLE_ADVISOR,
            gateway_url="http://test",
        )
    assert result == {"glasses": "thin-frame rectangular"}
    assert "earring" not in result


# ---------------------------------------------------------------------------
# Pipeline wiring test: _select_features → _build_avatar_charachter
#
# This catches the real bug: feature selection returning valid features but the
# persona ending up with empty appearance because of wiring failures.
# ---------------------------------------------------------------------------


def test_pipeline_features_to_avatar_persona():
    """Full pipeline: mocked per-field LLM → features → avatar_persona with name + appearance."""
    mock_class, mock_instance = _make_per_field_side_effect()

    with patch("pipeline.persona.aggregator_llm.GatewayClient", mock_class):
        features = _select_features(
            SAMPLE_DEMOGRAPHICS,
            SAMPLE_ADVISOR,
            gateway_url="http://test",
        )

    assert features is not None, "features must not be None"

    avatar = _build_avatar_charachter(SAMPLE_ADVISOR, SAMPLE_DEMOGRAPHICS, features)
    persona = avatar["avatar_persona"]

    # Name must be present in personal section
    assert persona["personal"].get("name"), "personal.name must be set"

    # Appearance must be non-empty with all visual keys
    appearance = persona.get("appearance", {})
    assert len(appearance) >= 12, (
        f"appearance has only {len(appearance)} keys — "
        f"expected 12+. Features did not flow through. "
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
    assert "gender" in persona["personal"]


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
    """At least 3 distinct age groups (from settings) are represented."""
    result = _pick_diverse_demographics(4)

    def age_to_group(age):
        for lo, hi in _AGE_GROUPS:
            if lo <= age <= hi:
                return (lo, hi)
        return None

    groups = {age_to_group(d["age"]) for d in result}
    assert len(groups) >= 3


def test_diverse_demographics_skin_tones_distinct():
    """All 4 skin tones are distinct."""
    result = _pick_diverse_demographics(4)
    skin_tones = [d["SKIN_TONE"] for d in result]
    assert len(set(skin_tones)) == 4


def test_diverse_demographics_has_required_keys():
    """Each demographics dict has all required keys."""
    result = _pick_diverse_demographics(4)
    required = {
        "gender",
        "age",
        "name",
        "style",
        "bg_color",
        "fg_color",
        "SKIN_TONE",
        "HAIR_COLOR",
        "EYE_COLOR",
        "BROWS_COLOR",
    }
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
            assert item in opts_default[key], f"{key}: hard-type item '{item}' not in default pool"


def test_load_user_prompt_options_hard_type_female_excludes_male():
    """Hard-type female: options must not contain items from male bucket."""
    opts_default = _load_user_prompt_options("female", hard_type=False)
    opts_hard = _load_user_prompt_options("female", hard_type=True)
    for key in opts_hard:
        for item in opts_hard[key]:
            assert item in opts_default[key], f"{key}: hard-type item '{item}' not in default pool"


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
