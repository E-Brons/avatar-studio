"""Unit tests for the HTTP API layer — config_loader and http_server helpers.

No running services required. FastAPI / uvicorn must be installed
(``scripts/install.sh``) but no server is started.

Covers:
  - api.config_loader.ConfigLoader  — attribute loading, option resolution
  - api.http_server._resolve_demographics — constraint merging, brows re-derive
  - api.http_server._demo_to_response    — key mapping
  - api.http_server._demo_key            — attribute-id → pipeline-key lookup
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from api.config_loader import ConfigLoader

# http_server requires FastAPI. Guard the import so ConfigLoader tests always
# run, while the http_server tests are skipped if the package is not installed
# (i.e. before ``scripts/install.sh`` has been run).
try:
    from api.http_server import (
        _ATTR_TO_DEMO_KEY,
        AttributeSelection,
        _demo_key,
        _demo_to_response,
        _resolve_demographics,
    )

    _HTTP_SERVER_AVAILABLE = True
except ImportError:
    _HTTP_SERVER_AVAILABLE = False

_requires_http_server = pytest.mark.skipif(
    not _HTTP_SERVER_AVAILABLE,
    reason="fastapi not installed — run scripts/install.sh first",
)

pytestmark = pytest.mark.avatar

# ─── Helpers ─────────────────────────────────────────────────────────────────

# Minimal demographics dict returned by pick_demographics()
_DEMO_BASE: dict = {
    "gender": "male",
    "age": 35,
    "name": "Test User",
    "style": "random",
    "bg_color": "#4A90D9",
    "fg_color": "#FFFFFF",
    "SKIN_TONE": "#F5E0C9",
    "HAIR_COLOR": "#3B2314 #261508",
    "EYE_COLOR": "#3D1C02 #1A0800",
    "BROWS_COLOR": "#2A1A0C",
    "EYE_SHAPE": "almond",
    "BROWS_STYLE": "straight thick",
    "NOSE_SHAPE": "small rounded shadow",
    "CHIN_SHAPE": "squared-off",
    "CHEEKS_SHAPE": "hollow and sculpted",
}


# ─── ConfigLoader ─────────────────────────────────────────────────────────────


class TestConfigLoaderLoad:
    """ConfigLoader.load() returns the full attribute catalogue."""

    def setup_method(self):
        self.loader = ConfigLoader()
        self.config = self.loader.load()
        self.attrs = {a["id"]: a for a in self.config["attributes"]}

    def test_returns_20_attributes(self):
        assert len(self.config["attributes"]) == 20

    def test_all_attrs_have_required_keys(self):
        required = {"id", "label", "category", "type", "selection_modes", "default_mode", "options"}
        for attr in self.config["attributes"]:
            missing = required - attr.keys()
            assert not missing, f"Attribute '{attr['id']}' missing keys: {missing}"

    def test_categories_cover_all_groups(self):
        cats = {a["category"] for a in self.config["attributes"]}
        assert cats == {
            "style",
            "demographics",
            "personal",
            "phenotype",
            "appearance",
            "personality",
        }

    # ── gender ───────────────────────────────────────────────────────────────

    def test_gender_has_three_options(self):
        assert len(self.attrs["gender"]["options"]) == 3

    def test_gender_option_ids(self):
        ids = {o["id"] for o in self.attrs["gender"]["options"]}
        assert ids == {"male", "female", "non-binary"}

    def test_gender_default_mode_is_random(self):
        assert self.attrs["gender"]["default_mode"] == "random"

    # ── age ──────────────────────────────────────────────────────────────────

    def test_age_has_twelve_groups(self):
        assert len(self.attrs["age"]["options"]) == 12

    def test_age_options_have_min_max_extra(self):
        for opt in self.attrs["age"]["options"]:
            assert "min" in opt["extra"] and "max" in opt["extra"]

    def test_age_range_field_present(self):
        assert self.attrs["age"]["range"] == [0, 110]

    # ── skin_tone ────────────────────────────────────────────────────────────

    def test_skin_tone_type_is_color(self):
        assert self.attrs["skin_tone"]["type"] == "color"

    def test_skin_tone_has_28_options(self):
        assert len(self.attrs["skin_tone"]["options"]) == 28

    def test_skin_tone_option_ids_are_hex(self):
        for opt in self.attrs["skin_tone"]["options"]:
            assert opt["id"].startswith("#"), f"Not a hex: {opt['id']}"

    # ── hair_color ───────────────────────────────────────────────────────────

    def test_hair_color_type_is_dual_color(self):
        assert self.attrs["hair_color"]["type"] == "dual_color"

    def test_hair_color_has_20_options(self):
        assert len(self.attrs["hair_color"]["options"]) == 20

    def test_hair_color_options_have_hex_base_and_shadow(self):
        for opt in self.attrs["hair_color"]["options"]:
            extra = opt.get("extra", {})
            assert "hex_base" in extra, f"Missing hex_base on {opt['id']}"
            assert "hex_shadow" in extra, f"Missing hex_shadow on {opt['id']}"

    def test_hair_color_field_names(self):
        assert self.attrs["hair_color"]["field_names"] == ["hex_base", "hex_shadow"]

    # ── eye_color ────────────────────────────────────────────────────────────

    def test_eye_color_options_have_hex_iris_and_pupil(self):
        for opt in self.attrs["eye_color"]["options"]:
            extra = opt.get("extra", {})
            assert "hex_iris" in extra
            assert "hex_pupil" in extra

    # ── brows_color ──────────────────────────────────────────────────────────

    def test_brows_color_has_inherited_mode(self):
        modes = {m["id"] for m in self.attrs["brows_color"]["selection_modes"]}
        assert "inherited" in modes

    def test_brows_color_default_is_inherited(self):
        assert self.attrs["brows_color"]["default_mode"] == "inherited"

    def test_brows_color_formula_present(self):
        assert "formula" in self.attrs["brows_color"]

    # ── gender-bucketed phenotype shapes ─────────────────────────────────────

    def test_brows_style_depends_on_gender(self):
        assert self.attrs["brows_style"]["depends_on"] == "gender"

    def test_brows_style_options_have_gender_bucket(self):
        for opt in self.attrs["brows_style"]["options"]:
            assert "gender_bucket" in opt.get("extra", {}), (
                f"brows_style option '{opt['id']}' missing gender_bucket"
            )

    def test_chin_shape_depends_on_gender(self):
        assert self.attrs["chin_shape"]["depends_on"] == "gender"

    def test_cheeks_shape_depends_on_gender(self):
        assert self.attrs["cheeks_shape"]["depends_on"] == "gender"

    # ── style ─────────────────────────────────────────────────────────────────

    def test_style_has_ten_options(self):
        assert len(self.attrs["style"]["options"]) == 10

    def test_style_option_ids(self):
        ids = {o["id"] for o in self.attrs["style"]["options"]}
        assert ids == {
            "studio_3d",
            "korean",
            "photorealistic",
            "lineart",
            "clay",
            "toon-head",
            "avataaars",
            "bottts",
            "micah",
            "opeeps",
        }

    def test_style_options_have_description_extra(self):
        for opt in self.attrs["style"]["options"]:
            assert "description" in opt.get("extra", {}), (
                f"style option '{opt['id']}' missing description"
            )

    # ── hair_style is depends_on gender + llm_generated ──────────────────────

    def test_hair_style_depends_on_gender(self):
        assert self.attrs["hair_style"]["depends_on"] == "gender"

    def test_hair_style_is_llm_generated(self):
        assert self.attrs["hair_style"]["llm_generated"] is True

    def test_hair_style_options_have_gender_bucket(self):
        for opt in self.attrs["hair_style"]["options"]:
            assert "gender_bucket" in opt.get("extra", {}), (
                f"hair_style option '{opt['id']}' missing gender_bucket"
            )


# ─── _demo_key ────────────────────────────────────────────────────────────────


@_requires_http_server
class TestDemoKey:
    """_demo_key maps UI attribute IDs to pipeline dict keys."""

    def test_gender_maps_to_gender(self):
        assert _demo_key("gender") == "gender"

    def test_skin_tone_maps_to_upper(self):
        assert _demo_key("skin_tone") == "SKIN_TONE"

    def test_hair_color_maps_to_upper(self):
        assert _demo_key("hair_color") == "HAIR_COLOR"

    def test_brows_color_maps_to_upper(self):
        assert _demo_key("brows_color") == "BROWS_COLOR"

    def test_style_maps_to_style(self):
        assert _demo_key("style") == "style"

    def test_unknown_id_returns_none(self):
        assert _demo_key("nonexistent_attribute") is None

    def test_all_mapped_ids_covered(self):
        # Every key in the explicit mapping dict resolves to a non-None value.
        for attr_id in _ATTR_TO_DEMO_KEY:
            assert _demo_key(attr_id) is not None


# ─── _demo_to_response ────────────────────────────────────────────────────────


@_requires_http_server
class TestDemoToResponse:
    """_demo_to_response converts the pipeline demo dict to JSON-safe attr map."""

    def setup_method(self):
        self.resp = _demo_to_response(_DEMO_BASE.copy())

    def test_gender_present(self):
        assert self.resp["gender"] == "male"

    def test_age_present(self):
        assert self.resp["age"] == 35

    def test_style_present(self):
        assert self.resp["style"] == "random"

    def test_skin_tone_key_is_snake_case(self):
        assert "skin_tone" in self.resp

    def test_hair_color_key_is_snake_case(self):
        assert "hair_color" in self.resp

    def test_eye_shape_key_is_snake_case(self):
        assert "eye_shape" in self.resp

    def test_values_preserved(self):
        assert self.resp["skin_tone"] == "#F5E0C9"
        assert self.resp["hair_color"] == "#3B2314 #261508"


# ─── _resolve_demographics ────────────────────────────────────────────────────


@_requires_http_server
class TestResolveDemographics:
    """_resolve_demographics merges pick_demographics() output with constraints."""

    def _patched(self, constraints=None, seed=None):
        with patch("api.http_server.pick_demographics", return_value=_DEMO_BASE.copy()):
            return _resolve_demographics(constraints or [], seed)

    def test_no_constraints_returns_base_keys(self):
        demo = self._patched()
        for key in ("gender", "age", "SKIN_TONE", "HAIR_COLOR", "EYE_COLOR", "BROWS_COLOR"):
            assert key in demo, f"Missing key: {key}"

    def test_gender_select_override(self):
        demo = self._patched([AttributeSelection(id="gender", mode="select", value="female")])
        assert demo["gender"] == "female"

    def test_age_select_override(self):
        demo = self._patched([AttributeSelection(id="age", mode="select", value=42)])
        assert demo["age"] == 42

    def test_skin_tone_select_override(self):
        demo = self._patched([AttributeSelection(id="skin_tone", mode="select", value="#AABBCC")])
        assert demo["SKIN_TONE"] == "#AABBCC"

    def test_random_mode_constraint_ignored(self):
        # mode=random does not apply the value
        demo = self._patched([AttributeSelection(id="gender", mode="random", value="female")])
        assert demo["gender"] == "male"  # base value unchanged

    def test_llm_mode_constraint_ignored(self):
        # mode=llm does not apply the value — LLM decides at pipeline time
        demo = self._patched([AttributeSelection(id="gender", mode="llm", value="female")])
        assert demo["gender"] == "male"  # base value unchanged

    def test_hair_color_override_re_derives_brows_color(self):
        """Overriding hair_color must re-compute BROWS_COLOR from the new base hex."""
        new_hair = "#8B5E3C #5C3D1E"  # base hex = #8B5E3C
        demo = self._patched([AttributeSelection(id="hair_color", mode="select", value=new_hair)])
        assert demo["HAIR_COLOR"] == new_hair
        # BROWS_COLOR should be darkened version of #8B5E3C (factor 0.7)
        # _darken_hex uses int() (truncation): int(0x8B*0.7)=int(97.3)=97=0x61,
        # int(0x5E*0.7)=int(65.8)=65=0x41, int(0x3C*0.7)=int(42.0)=42=0x2A → #61412A
        assert demo["BROWS_COLOR"] == "#61412A"

    def test_hair_color_no_override_keeps_original_brows_color(self):
        """If hair_color is NOT overridden, BROWS_COLOR is not touched."""
        original_brows = _DEMO_BASE["BROWS_COLOR"]
        demo = self._patched([AttributeSelection(id="gender", mode="select", value="female")])
        assert demo["BROWS_COLOR"] == original_brows

    def test_multiple_constraints_all_applied(self):
        demo = self._patched(
            [
                AttributeSelection(id="gender", mode="select", value="female"),
                AttributeSelection(id="age", mode="select", value=28),
                AttributeSelection(id="style", mode="select", value="clay"),
            ]
        )
        assert demo["gender"] == "female"
        assert demo["age"] == 28
        assert demo["style"] == "clay"

    def test_none_value_select_constraint_skipped(self):
        """A select constraint with value=None must not overwrite the base key."""
        demo = self._patched([AttributeSelection(id="gender", mode="select", value=None)])
        assert demo["gender"] == "male"  # base unchanged
