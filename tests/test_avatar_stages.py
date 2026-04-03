"""Unit tests for avatar stage modules not covered by test_avatar_features.py.

Covers:
  - avatar_studio.config.config   — WCAG utilities, hex helpers, palette filtering
  - avatar_studio.pipeline.step_a_randomise_person — _pick_colors, _pick_name, _pick_demographics
  - avatar_studio.pipeline.step_d_make_abbreviation — create_abbreviation_avatar, apply_circle_frame
  - avatar_studio.pipeline.step_ef_generate_image — _build_expression_prompt, create_face_avatar
"""

import io
import random as _random
import re
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from config.config import (
    _FRAME_FG_COLOR,
    _WCAG_MIN_CONTRAST,
    PALETTE,
    VALID_BG_PALETTE,
    _color_for_name,
    _contrast_ratio,
    _darken_hex,
    _hex_to_rgb,
    _initials,
    _relative_luminance,
    _slug,
)
from pipeline.step_a_randomise_person import (
    _GENDERS,
    _HAIR_COLORS,
    _LAST_NAMES,
    _SKIN_TONES,
    _pick_colors,
    _pick_demographics,
    _pick_name,
)
from pipeline.step_d_make_abbreviation import (
    apply_circle_frame,
    create_abbreviation_avatar,
)
from pipeline.step_ef_generate_image import create_face_avatar

pytestmark = pytest.mark.avatar

# ---------------------------------------------------------------------------
# avatar_studio.config.config — _relative_luminance
# ---------------------------------------------------------------------------


def test_relative_luminance_black():
    assert _relative_luminance("#000000") == pytest.approx(0.0)


def test_relative_luminance_white():
    assert _relative_luminance("#FFFFFF") == pytest.approx(1.0, abs=1e-4)


def test_relative_luminance_midgrey():
    # #808080 ≈ 0.2158 per WCAG formula
    val = _relative_luminance("#808080")
    assert 0.20 < val < 0.23


def test_relative_luminance_ignores_hash_case():
    assert _relative_luminance("#aabbcc") == pytest.approx(_relative_luminance("#AABBCC"))


# ---------------------------------------------------------------------------
# avatar_studio.config.config — _contrast_ratio
# ---------------------------------------------------------------------------


def test_contrast_ratio_black_white():
    ratio = _contrast_ratio("#000000", "#FFFFFF")
    assert ratio == pytest.approx(21.0, abs=0.1)


def test_contrast_ratio_same_color():
    assert _contrast_ratio("#FF0000", "#FF0000") == pytest.approx(1.0)


def test_contrast_ratio_is_symmetric():
    assert _contrast_ratio("#123456", "#ABCDEF") == pytest.approx(
        _contrast_ratio("#ABCDEF", "#123456")
    )


def test_contrast_ratio_always_gte_one():
    for color in ["#000000", "#FFFFFF", "#FF5733", "#123456"]:
        assert _contrast_ratio(color, "#FFFFFF") >= 1.0


# ---------------------------------------------------------------------------
# avatar_studio.config.config — VALID_BG_PALETTE
# ---------------------------------------------------------------------------


def test_valid_bg_palette_all_pass_wcag():
    """Every color in VALID_BG_PALETTE must exceed _WCAG_MIN_CONTRAST against
    the frame foreground color."""
    for color in VALID_BG_PALETTE:
        ratio = _contrast_ratio(color, _FRAME_FG_COLOR)
        assert ratio >= _WCAG_MIN_CONTRAST, f"{color} contrast {ratio:.2f} < {_WCAG_MIN_CONTRAST}"


def test_valid_bg_palette_non_empty():
    assert len(VALID_BG_PALETTE) > 0


def test_valid_bg_palette_subset_of_palette():
    palette_set = set(PALETTE)
    for color in VALID_BG_PALETTE:
        assert color in palette_set


# ---------------------------------------------------------------------------
# avatar_studio.config.config — _hex_to_rgb
# ---------------------------------------------------------------------------


def test_hex_to_rgb_white():
    assert _hex_to_rgb("#FFFFFF") == (255, 255, 255)


def test_hex_to_rgb_black():
    assert _hex_to_rgb("#000000") == (0, 0, 0)


def test_hex_to_rgb_known_color():
    assert _hex_to_rgb("#FF8000") == (255, 128, 0)


def test_hex_to_rgb_without_hash():
    assert _hex_to_rgb("FF8000") == (255, 128, 0)


# ---------------------------------------------------------------------------
# avatar_studio.config.config — _darken_hex
# ---------------------------------------------------------------------------


def test_darken_hex_reduces_channels():
    r, g, b = _hex_to_rgb(_darken_hex("#FFFFFF", factor=0.5))
    assert r == 127
    assert g == 127
    assert b == 127


def test_darken_hex_black_stays_black():
    assert _darken_hex("#000000", factor=0.7) == "#000000"


def test_darken_hex_default_factor():
    result = _darken_hex("#FFFFFF")
    r, g, b = _hex_to_rgb(result)
    assert r == int(255 * 0.7)


# ---------------------------------------------------------------------------
# avatar_studio.config.config — _initials
# ---------------------------------------------------------------------------


def test_initials_two_names():
    assert _initials("John Doe") == "JD"


def test_initials_single_word():
    assert _initials("Maya") == "MA"


def test_initials_three_names_uses_first_and_last():
    assert _initials("John Michael Doe") == "JD"


def test_initials_lowercase_input_uppercased():
    assert _initials("john doe") == "JD"


# ---------------------------------------------------------------------------
# avatar_studio.config.config — _slug
# ---------------------------------------------------------------------------


def test_slug_replaces_spaces():
    assert _slug("John Doe") == "john-doe"


def test_slug_already_lowercase():
    assert _slug("maya") == "maya"


# ---------------------------------------------------------------------------
# avatar_studio.config.config — _color_for_name
# ---------------------------------------------------------------------------


def test_color_for_name_is_deterministic():
    assert _color_for_name("Alice") == _color_for_name("Alice")


def test_color_for_name_differs_by_name():
    # Very unlikely to collide
    colors = {_color_for_name(n) for n in ["Alice", "Bob", "Charlie", "Diana"]}
    assert len(colors) > 1


def test_color_for_name_in_palette():
    assert _color_for_name("Test Name") in PALETTE


# ---------------------------------------------------------------------------
# avatar_studio.pipeline.step_a_randomise_person — _pick_name
# ---------------------------------------------------------------------------


def test_pick_name_male_returns_two_words():
    rng = _random.Random(42)
    name = _pick_name("male", rng)
    assert len(name.split()) == 2


def test_pick_name_female_returns_two_words():
    rng = _random.Random(99)
    name = _pick_name("female", rng)
    assert len(name.split()) == 2


def test_pick_name_nonbinary_returns_two_words():
    rng = _random.Random(7)
    name = _pick_name("non-binary", rng)
    assert len(name.split()) == 2


def test_pick_name_last_name_from_pool():
    rng = _random.Random(0)
    name = _pick_name("male", rng)
    last = name.split()[-1]
    assert last in _LAST_NAMES


def test_pick_name_seeded_is_deterministic():
    name1 = _pick_name("female", _random.Random(5))
    name2 = _pick_name("female", _random.Random(5))
    assert name1 == name2


# ---------------------------------------------------------------------------
# avatar_studio.pipeline.step_a_randomise_person — _pick_colors
# ---------------------------------------------------------------------------


def test_pick_colors_returns_required_keys():
    result = _pick_colors()
    for key in ("SKIN_TONE", "HAIR_COLOR", "EYE_COLOR", "BROWS_COLOR"):
        assert key in result


def test_pick_colors_skin_tone_from_list():
    result = _pick_colors()
    assert result["SKIN_TONE"] in _SKIN_TONES


def test_pick_colors_hair_color_from_list():
    result = _pick_colors()
    assert result["HAIR_COLOR"] in _HAIR_COLORS


def test_pick_colors_brows_color_is_hex():
    result = _pick_colors()
    assert re.match(r"^#[0-9A-Fa-f]{6}$", result["BROWS_COLOR"])


def test_pick_colors_seeded_is_deterministic():
    rng = _random.Random(42)
    c1 = _pick_colors(rng)
    rng = _random.Random(42)
    c2 = _pick_colors(rng)
    assert c1 == c2


def test_pick_colors_brows_derived_from_hair():
    """BROWS_COLOR must be a darkened version of the HAIR_COLOR base hex."""
    rng = _random.Random(10)
    result = _pick_colors(rng)
    hair_base = result["HAIR_COLOR"].split()[0]
    expected = _darken_hex(hair_base, factor=0.7)
    assert result["BROWS_COLOR"] == expected


# ---------------------------------------------------------------------------
# avatar_studio.pipeline.step_a_randomise_person — _pick_demographics
# ---------------------------------------------------------------------------


def test_pick_demographics_returns_required_keys():
    d = _pick_demographics()
    for key in (
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
    ):
        assert key in d, f"Missing key: {key}"


def test_pick_demographics_gender_valid():
    d = _pick_demographics()
    assert d["gender"] in _GENDERS


def test_pick_demographics_age_in_range():
    d = _pick_demographics()
    assert 25 <= d["age"] <= 70


def test_pick_demographics_seeded_is_deterministic():
    d1 = _pick_demographics(seed=1234)
    d2 = _pick_demographics(seed=1234)
    assert d1 == d2


def test_pick_demographics_different_seeds_differ():
    d1 = _pick_demographics(seed=1)
    d2 = _pick_demographics(seed=2)
    assert d1 != d2


def test_pick_demographics_bg_color_passes_wcag():
    """bg_color must be drawn from VALID_BG_PALETTE."""
    for seed in range(20):
        d = _pick_demographics(seed=seed)
        ratio = _contrast_ratio(d["bg_color"], d["fg_color"])
        assert ratio >= _WCAG_MIN_CONTRAST, f"seed={seed}: {d['bg_color']} contrast {ratio:.2f}"


def test_pick_demographics_style_propagated():
    d = _pick_demographics(style="custom-style")
    assert d["style"] == "custom-style"


def test_pick_demographics_name_has_two_parts():
    d = _pick_demographics(seed=42)
    assert len(d["name"].split()) == 2


# ---------------------------------------------------------------------------
# avatar_studio.pipeline.step_d_make_abbreviation — create_abbreviation_avatar
# ---------------------------------------------------------------------------


def test_create_abbreviation_avatar_creates_file():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "avatar.png"
        result = create_abbreviation_avatar("John Doe", out, size=64)
        assert result == out
        assert out.exists()
        assert out.stat().st_size > 0


def test_create_abbreviation_avatar_is_valid_png():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "avatar.png"
        create_abbreviation_avatar("Jane Smith", out, size=64)
        img = Image.open(out)
        assert img.format == "PNG"


def test_create_abbreviation_avatar_correct_size():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "avatar.png"
        create_abbreviation_avatar("Alex Ray", out, size=128)
        img = Image.open(out)
        assert img.size == (128, 128)


def test_create_abbreviation_avatar_custom_color():
    """Passing an explicit color should not raise."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "avatar.png"
        create_abbreviation_avatar("Sam Lee", out, size=64, color="#4A90D9")
        assert out.exists()


def test_create_abbreviation_avatar_single_word_name():
    """Single-word name should use the first two letters as initials."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "avatar.png"
        create_abbreviation_avatar("Maya", out, size=64)
        assert out.exists()


def test_create_abbreviation_avatar_creates_parent_dirs():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "nested" / "deep" / "avatar.png"
        create_abbreviation_avatar("Test User", out, size=32)
        assert out.exists()


# ---------------------------------------------------------------------------
# avatar_studio.pipeline.step_d_make_abbreviation — apply_circle_frame
# ---------------------------------------------------------------------------


def _make_test_image_bytes(size: int = 64, color: tuple = (200, 100, 50)) -> bytes:
    """Return PNG bytes for a solid-color RGBA image."""
    img = Image.new("RGB", (size, size), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_apply_circle_frame_returns_bytes():
    result = apply_circle_frame(_make_test_image_bytes(), "#4A90D9", 64)
    assert isinstance(result, bytes)
    assert len(result) > 0


def test_apply_circle_frame_output_is_valid_png():
    result = apply_circle_frame(_make_test_image_bytes(), "#4A90D9", 64)
    img = Image.open(io.BytesIO(result))
    assert img.format == "PNG"


def test_apply_circle_frame_output_size():
    result = apply_circle_frame(_make_test_image_bytes(100), "#4A90D9", 80)
    img = Image.open(io.BytesIO(result))
    assert img.size == (80, 80)


def test_apply_circle_frame_is_rgba():
    result = apply_circle_frame(_make_test_image_bytes(), "#4A90D9", 64)
    img = Image.open(io.BytesIO(result))
    assert img.mode == "RGBA"


def test_apply_circle_frame_corners_are_transparent():
    """Outside-circle pixels (corners) must be fully transparent."""
    result = apply_circle_frame(_make_test_image_bytes(), "#FFFFFF", 64)
    img = Image.open(io.BytesIO(result)).convert("RGBA")
    # Top-left corner pixel
    assert img.getpixel((0, 0))[3] == 0


def test_apply_circle_frame_center_is_opaque():
    """Center pixel must be fully opaque."""
    result = apply_circle_frame(_make_test_image_bytes(), "#4A90D9", 64)
    img = Image.open(io.BytesIO(result)).convert("RGBA")
    cx, cy = 32, 32
    assert img.getpixel((cx, cy))[3] == 255


def test_apply_circle_frame_upscales_small_input():
    """Input smaller than requested size should be upscaled without error."""
    small = _make_test_image_bytes(size=32)
    result = apply_circle_frame(small, "#4A90D9", 128)
    img = Image.open(io.BytesIO(result))
    assert img.size == (128, 128)


def test_apply_circle_frame_has_white_border():
    """The sticker border ring just outside the colored circle must be white."""
    result = apply_circle_frame(_make_test_image_bytes(128), "#123456", 256)
    img = Image.open(io.BytesIO(result)).convert("RGBA")
    cx = cy = 128
    circle_r = int(256 * 0.33)
    border_sample_x = cx + circle_r + 3  # inside the white border ring
    r, g, b, a = img.getpixel((border_sample_x, cy))
    assert r > 230 and g > 230 and b > 230, "Border ring should be white"


def test_apply_circle_frame_png_magic_bytes():
    """Output must start with the PNG magic bytes."""
    result = apply_circle_frame(_make_test_image_bytes(), "#4A90D9", 128)
    assert result[:4] == b"\x89PNG"


# ---------------------------------------------------------------------------
# avatar_studio.pipeline.step_ef_generate_image — create_face_avatar
# ---------------------------------------------------------------------------


def _make_png_bytes(size: int = 64) -> bytes:
    return _make_test_image_bytes(size=size)


def test_create_face_avatar_neutral_failure_returns_null_map():
    """If portrait generation fails, all expression slots are None."""
    advisor = {"name": "Test Advisor", "role": "Advisor", "traits": []}

    with (
        patch("pipeline.step_ef_generate_image.pick_demographics") as mock_demo,
        patch("pipeline.step_ef_generate_image.select_features") as mock_feat,
        patch("pipeline.step_ef_generate_image.generate_avatar_image") as mock_img,
    ):
        mock_demo.return_value = {
            "gender": "male",
            "age": 40,
            "name": "Test Advisor",
            "style": "flat-vector-2D",
            "bg_color": "#4A90D9",
            "fg_color": "#FFFFFF",
            "SKIN_TONE": "#C9A96E",
            "HAIR_COLOR": "#3B2314 #261508",
            "EYE_COLOR": "#6B3A1F #0A0A0A",
            "BROWS_COLOR": "#3B2314",
        }
        mock_feat.return_value = {}
        mock_img.side_effect = RuntimeError("Ollama unavailable")

        with tempfile.TemporaryDirectory() as tmp:
            expr_map, _ = create_face_avatar(
                advisor,
                ["neutral", "happy", "sad"],
                Path(tmp),
                "test-slug",
                gateway_url="http://test",
            )

    assert expr_map == {"neutral": None, "happy": None, "sad": None}


def test_create_face_avatar_success_returns_filenames():
    """Happy path: portrait succeeds, expressions succeed."""
    advisor = {"name": "Test Advisor", "role": "Advisor", "traits": []}

    def fake_generate_image(persona_path, *, out_path, **kwargs):
        Image.new("RGB", (64, 64), (200, 100, 50)).save(str(out_path))
        return out_path

    with (
        patch("pipeline.step_ef_generate_image.pick_demographics") as mock_demo,
        patch("pipeline.step_ef_generate_image.select_features") as mock_feat,
        patch(
            "pipeline.step_ef_generate_image.generate_avatar_image",
            side_effect=fake_generate_image,
        ),
    ):
        mock_demo.return_value = {
            "gender": "female",
            "age": 30,
            "name": "Test Advisor",
            "style": "flat-vector-2D",
            "bg_color": "#4A90D9",
            "fg_color": "#FFFFFF",
            "SKIN_TONE": "#C9A96E",
            "HAIR_COLOR": "#3B2314 #261508",
            "EYE_COLOR": "#6B3A1F #0A0A0A",
            "BROWS_COLOR": "#3B2314",
        }
        mock_feat.return_value = {}

        with tempfile.TemporaryDirectory() as tmp:
            expr_map, demographics = create_face_avatar(
                advisor,
                ["neutral", "happy"],
                Path(tmp),
                "test-slug",
                gateway_url="http://test",
            )

    assert expr_map["neutral"] == "test-slug-neutral.png"
    assert expr_map["happy"] == "test-slug-happy.png"
    assert demographics["gender"] == "female"


def test_create_face_avatar_expression_failure_sets_none():
    """Neutral succeeds but one expression fails — that slot is None."""
    advisor = {"name": "Test Advisor", "role": "Advisor", "traits": []}
    call_count = {"n": 0}

    def fake_generate_image(persona_path, *, out_path, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # neutral — succeeds
            Image.new("RGB", (64, 64)).save(str(out_path))
            return out_path
        else:
            raise RuntimeError("Expression failed")

    with (
        patch("pipeline.step_ef_generate_image.pick_demographics") as mock_demo,
        patch("pipeline.step_ef_generate_image.select_features") as mock_feat,
        patch(
            "pipeline.step_ef_generate_image.generate_avatar_image",
            side_effect=fake_generate_image,
        ),
    ):
        mock_demo.return_value = {
            "gender": "male",
            "age": 45,
            "name": "Test Advisor",
            "style": "flat-vector-2D",
            "bg_color": "#4A90D9",
            "fg_color": "#FFFFFF",
            "SKIN_TONE": "#C9A96E",
            "HAIR_COLOR": "#3B2314 #261508",
            "EYE_COLOR": "#6B3A1F #0A0A0A",
            "BROWS_COLOR": "#3B2314",
        }
        mock_feat.return_value = {}

        with tempfile.TemporaryDirectory() as tmp:
            expr_map, _ = create_face_avatar(
                advisor,
                ["neutral", "happy"],
                Path(tmp),
                "test-slug",
                gateway_url="http://test",
            )

    assert expr_map["neutral"] == "test-slug-neutral.png"
    assert expr_map["happy"] is None


def test_create_face_avatar_feature_failure_does_not_abort():
    """Feature selection failure is non-fatal; portrait still generated."""
    advisor = {"name": "Test Advisor", "role": "Advisor", "traits": []}

    def fake_generate_image(persona_path, *, out_path, **kwargs):
        Image.new("RGB", (64, 64)).save(str(out_path))
        return out_path

    with (
        patch("pipeline.step_ef_generate_image.pick_demographics") as mock_demo,
        patch("pipeline.step_ef_generate_image.select_features") as mock_feat,
        patch(
            "pipeline.step_ef_generate_image.generate_avatar_image",
            side_effect=fake_generate_image,
        ),
    ):
        mock_demo.return_value = {
            "gender": "male",
            "age": 35,
            "name": "Test Advisor",
            "style": "flat-vector-2D",
            "bg_color": "#4A90D9",
            "fg_color": "#FFFFFF",
            "SKIN_TONE": "#C9A96E",
            "HAIR_COLOR": "#3B2314 #261508",
            "EYE_COLOR": "#6B3A1F #0A0A0A",
            "BROWS_COLOR": "#3B2314",
        }
        mock_feat.side_effect = RuntimeError("LLM unavailable")

        with tempfile.TemporaryDirectory() as tmp:
            expr_map, _ = create_face_avatar(
                advisor,
                ["neutral"],
                Path(tmp),
                "test-slug",
                gateway_url="http://test",
            )

    assert expr_map["neutral"] == "test-slug-neutral.png"


def test_create_face_avatar_returns_demographics():
    advisor = {"name": "Test Advisor", "role": "Advisor", "traits": []}

    def fake_generate_image(persona_path, *, out_path, **kwargs):
        Image.new("RGB", (64, 64)).save(str(out_path))
        return out_path

    with (
        patch("pipeline.step_ef_generate_image.pick_demographics") as mock_demo,
        patch("pipeline.step_ef_generate_image.select_features") as mock_feat,
        patch(
            "pipeline.step_ef_generate_image.generate_avatar_image",
            side_effect=fake_generate_image,
        ),
    ):
        expected_demo = {
            "gender": "female",
            "age": 28,
            "name": "Test User",
            "style": "flat-vector-2D",
            "bg_color": "#4A90D9",
            "fg_color": "#FFFFFF",
            "SKIN_TONE": "#C9A96E",
            "HAIR_COLOR": "#3B2314 #261508",
            "EYE_COLOR": "#6B3A1F #0A0A0A",
            "BROWS_COLOR": "#3B2314",
        }
        mock_demo.return_value = expected_demo
        mock_feat.return_value = {}

        with tempfile.TemporaryDirectory() as tmp:
            _, demographics = create_face_avatar(
                advisor,
                ["neutral"],
                Path(tmp),
                "slug",
                gateway_url="http://test",
            )

    assert demographics == expected_demo
