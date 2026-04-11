"""Tests for IPAdapter prompt_gen module and _apply_prompt_gen_patches helpers."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from pipeline.render.ipadapter.prompt_gen import (
    IPAdapterGenParams,
    build_reexpress_params,
    build_restyle_params,
)

# ---------------------------------------------------------------------------
# Shared YAML fixtures
# ---------------------------------------------------------------------------

_RESTYLE_YAML = """\
prompt_template: "{style_description}. Same person."
negative_prompt: "blurry"
width: 512
height: 512
num_inference_steps: 20
cfg_scale: 7.0
ip_adapter_scale: 0.7
lora: null
lora_weight: 1.0
"""

_RESTYLE_YAML_NO_LORA_WEIGHT = """\
prompt_template: "{style_description}. Same person."
negative_prompt: "blurry"
width: 512
height: 512
num_inference_steps: 20
cfg_scale: 7.0
ip_adapter_scale: 0.7
lora: null
"""

_RESTYLE_YAML_WITH_LORA = """\
prompt_template: "{style_description}. Same person."
negative_prompt: "blurry"
width: 512
height: 512
num_inference_steps: 20
cfg_scale: 7.0
ip_adapter_scale: 0.7
lora: "some-lora-model"
lora_weight: 0.8
"""

_REEXPRESS_YAML = """\
prompt_template: "Same person. {expression_name}, {facs_au_codes}."
negative_prompt: "blurry, distorted"
width: 512
height: 512
num_inference_steps: 25
cfg_scale: 8.0
ip_adapter_scale: 0.6
lora: null
lora_weight: 1.0
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _patch_restyle(yaml_text: str):
    """Context manager: mock _RESTYLE_CONFIG.read_text() to return yaml_text."""
    return patch(
        "pipeline.render.ipadapter.prompt_gen._RESTYLE_CONFIG",
        new_callable=lambda: _FakePathFactory(yaml_text),
    )


def _patch_reexpress(yaml_text: str):
    """Context manager: mock _REEXPRESS_CONFIG.read_text() to return yaml_text."""
    return patch(
        "pipeline.render.ipadapter.prompt_gen._REEXPRESS_CONFIG",
        new_callable=lambda: _FakePathFactory(yaml_text),
    )


class _FakePath:
    """Minimal Path-alike that returns a fixed string from read_text()."""

    def __init__(self, text: str) -> None:
        self._text = text
        # Needed so with_suffix() on the restyle script side doesn't explode in
        # the patch-helper path (not used here but keeps the API consistent).
        self.name = "fake.yml"

    def read_text(self, *args, **kwargs) -> str:
        return self._text

    def with_suffix(self, suffix: str) -> "_FakePath":
        return _FakePath(self._text)

    def write_text(self, text: str, *args, **kwargs) -> None:
        self._written = text

    def rename(self, target: "_FakePath") -> None:
        pass

    def __str__(self) -> str:
        return self.name


def _FakePathFactory(text: str):
    """Return a callable (class) whose instances behave like _FakePath(text)."""

    class _Cls(_FakePath):
        def __init__(self):
            super().__init__(text)

    return _Cls


# ---------------------------------------------------------------------------
# Tests: IPAdapterGenParams.log_lines()
# ---------------------------------------------------------------------------


class TestIPAdapterGenParamsLogLines:
    _PARAMS = IPAdapterGenParams(
        prompt="a portrait",
        negative_prompt="blurry",
        width=512,
        height=512,
        num_inference_steps=20,
        cfg_scale=7.0,
        ip_adapter_scale=0.7,
        lora=None,
        lora_weight=1.0,
    )

    def test_log_lines_non_empty(self):
        lines = self._PARAMS.log_lines()
        assert len(lines) > 0

    def test_log_lines_contains_prompt(self):
        lines = self._PARAMS.log_lines()
        joined = "\n".join(lines)
        assert "a portrait" in joined

    def test_log_lines_contains_negative_prompt(self):
        lines = self._PARAMS.log_lines()
        joined = "\n".join(lines)
        assert "blurry" in joined

    def test_log_lines_contains_size(self):
        lines = self._PARAMS.log_lines()
        joined = "\n".join(lines)
        assert "512" in joined

    def test_log_lines_contains_num_inference_steps(self):
        lines = self._PARAMS.log_lines()
        joined = "\n".join(lines)
        assert "20" in joined

    def test_log_lines_contains_cfg_scale(self):
        lines = self._PARAMS.log_lines()
        joined = "\n".join(lines)
        assert "7.0" in joined

    def test_log_lines_contains_ip_adapter_scale(self):
        lines = self._PARAMS.log_lines()
        joined = "\n".join(lines)
        assert "0.7" in joined

    def test_log_lines_lora_null_shown_as_null(self):
        lines = self._PARAMS.log_lines()
        joined = "\n".join(lines)
        assert "null" in joined

    def test_log_lines_lora_name_shown(self):
        params = IPAdapterGenParams(
            prompt="p",
            negative_prompt="n",
            width=256,
            height=256,
            num_inference_steps=10,
            cfg_scale=5.0,
            ip_adapter_scale=0.5,
            lora="my-lora",
            lora_weight=0.9,
        )
        joined = "\n".join(params.log_lines())
        assert "my-lora" in joined

    def test_log_lines_returns_list_of_strings(self):
        lines = self._PARAMS.log_lines()
        assert isinstance(lines, list)
        assert all(isinstance(line, str) for line in lines)


# ---------------------------------------------------------------------------
# Tests: build_restyle_params
# ---------------------------------------------------------------------------


class TestBuildRestyleParams:
    def _call(self, style_entry: dict, yaml_text: str = _RESTYLE_YAML) -> IPAdapterGenParams:
        fake = _FakePath(yaml_text)
        with patch("pipeline.render.ipadapter.prompt_gen._RESTYLE_CONFIG", fake):
            return build_restyle_params(style_entry)

    def test_returns_ipadapter_gen_params(self):
        result = self._call({"description": "photorealistic portrait"})
        assert isinstance(result, IPAdapterGenParams)

    def test_style_description_inserted_in_prompt(self):
        result = self._call({"description": "photorealistic"})
        assert "photorealistic" in result.prompt

    def test_prompt_is_string(self):
        result = self._call({"description": "studio 3d"})
        assert isinstance(result.prompt, str)

    def test_negative_prompt_from_yaml(self):
        result = self._call({"description": "any"})
        assert result.negative_prompt == "blurry"

    def test_width_is_int(self):
        result = self._call({"description": "any"})
        assert isinstance(result.width, int)
        assert result.width == 512

    def test_height_is_int(self):
        result = self._call({"description": "any"})
        assert isinstance(result.height, int)
        assert result.height == 512

    def test_num_inference_steps_is_int(self):
        result = self._call({"description": "any"})
        assert isinstance(result.num_inference_steps, int)
        assert result.num_inference_steps == 20

    def test_cfg_scale_is_float(self):
        result = self._call({"description": "any"})
        assert isinstance(result.cfg_scale, float)
        assert result.cfg_scale == 7.0

    def test_ip_adapter_scale_is_float(self):
        result = self._call({"description": "any"})
        assert isinstance(result.ip_adapter_scale, float)
        assert result.ip_adapter_scale == 0.7

    def test_lora_null_yaml_gives_none(self):
        result = self._call({"description": "any"})
        assert result.lora is None

    def test_lora_weight_is_float(self):
        result = self._call({"description": "any"})
        assert isinstance(result.lora_weight, float)
        assert result.lora_weight == 1.0

    def test_lora_string_value_preserved(self):
        result = self._call({"description": "any"}, yaml_text=_RESTYLE_YAML_WITH_LORA)
        assert result.lora == "some-lora-model"

    def test_lora_weight_from_yaml_with_lora(self):
        result = self._call({"description": "any"}, yaml_text=_RESTYLE_YAML_WITH_LORA)
        assert result.lora_weight == 0.8

    def test_missing_lora_weight_defaults_to_1_0(self):
        result = self._call({"description": "any"}, yaml_text=_RESTYLE_YAML_NO_LORA_WEIGHT)
        assert result.lora_weight == 1.0

    def test_description_trailing_dot_stripped(self):
        result = self._call({"description": "korean style."})
        assert "korean style" in result.prompt
        # The description passed to format_map must not end with "." per source logic
        # (rstripped before insertion)
        assert "korean style.." not in result.prompt

    def test_missing_description_falls_back_to_portrait(self):
        result = self._call({})
        assert "portrait" in result.prompt

    def test_log_lines_non_empty(self):
        result = self._call({"description": "any"})
        assert len(result.log_lines()) > 0


# ---------------------------------------------------------------------------
# Tests: build_reexpress_params
# ---------------------------------------------------------------------------


class TestBuildReexpressParams:
    _EXPR_ENTRY_SIMPLE = {
        "expression": "Happiness",
        "facs_action_units": "AU6+AU12",
        "description": "A warm genuine smile",
    }

    _EXPR_ENTRY_WITH_INTENSITY = {
        "expression": "Anger",
        "facs_action_units": "AU4 (moderate)+AU7 (slight)+AU23 (strong)",
        "description": "Anger face",
    }

    _EXPR_ENTRY_UNILATERAL = {
        "expression": "Contempt",
        "facs_action_units": "AU12x+AU14x",
        "description": "One-sided smirk",
    }

    def _call(self, expr_entry: dict, yaml_text: str = _REEXPRESS_YAML) -> IPAdapterGenParams:
        fake = _FakePath(yaml_text)
        with patch("pipeline.render.ipadapter.prompt_gen._REEXPRESS_CONFIG", fake):
            return build_reexpress_params(expr_entry)

    def test_returns_ipadapter_gen_params(self):
        result = self._call(self._EXPR_ENTRY_SIMPLE)
        assert isinstance(result, IPAdapterGenParams)

    def test_expression_name_in_prompt(self):
        result = self._call(self._EXPR_ENTRY_SIMPLE)
        assert "Happiness" in result.prompt

    def test_facs_codes_in_prompt(self):
        result = self._call(self._EXPR_ENTRY_SIMPLE)
        assert "AU6" in result.prompt
        assert "AU12" in result.prompt

    def test_intensity_labels_stripped_from_facs(self):
        result = self._call(self._EXPR_ENTRY_WITH_INTENSITY)
        assert "(moderate)" not in result.prompt
        assert "(slight)" not in result.prompt
        assert "(strong)" not in result.prompt

    def test_facs_codes_retained_after_intensity_strip(self):
        result = self._call(self._EXPR_ENTRY_WITH_INTENSITY)
        assert "AU4" in result.prompt
        assert "AU7" in result.prompt
        assert "AU23" in result.prompt

    def test_unilateral_placeholder_resolved(self):
        result = self._call(self._EXPR_ENTRY_UNILATERAL)
        # AUNNx should be replaced with AUNNR or AUNNL
        assert "AU12x" not in result.prompt
        assert "AU14x" not in result.prompt
        assert "AU12R" in result.prompt or "AU12L" in result.prompt
        assert "AU14R" in result.prompt or "AU14L" in result.prompt

    def test_negative_prompt_from_yaml(self):
        result = self._call(self._EXPR_ENTRY_SIMPLE)
        assert result.negative_prompt == "blurry, distorted"

    def test_width_is_int(self):
        result = self._call(self._EXPR_ENTRY_SIMPLE)
        assert isinstance(result.width, int)
        assert result.width == 512

    def test_height_is_int(self):
        result = self._call(self._EXPR_ENTRY_SIMPLE)
        assert isinstance(result.height, int)
        assert result.height == 512

    def test_num_inference_steps_is_int(self):
        result = self._call(self._EXPR_ENTRY_SIMPLE)
        assert isinstance(result.num_inference_steps, int)
        assert result.num_inference_steps == 25

    def test_cfg_scale_is_float(self):
        result = self._call(self._EXPR_ENTRY_SIMPLE)
        assert isinstance(result.cfg_scale, float)
        assert result.cfg_scale == 8.0

    def test_ip_adapter_scale_is_float(self):
        result = self._call(self._EXPR_ENTRY_SIMPLE)
        assert isinstance(result.ip_adapter_scale, float)
        assert result.ip_adapter_scale == 0.6

    def test_lora_null_yaml_gives_none(self):
        result = self._call(self._EXPR_ENTRY_SIMPLE)
        assert result.lora is None

    def test_lora_weight_default(self):
        result = self._call(self._EXPR_ENTRY_SIMPLE)
        assert result.lora_weight == 1.0

    def test_expression_from_id_key_fallback(self):
        """Falls back to 'id' key when 'expression' key is absent."""
        expr_entry = {"id": "surprise", "facs_action_units": "AU1+AU2", "description": "wide eyes"}
        result = self._call(expr_entry)
        assert "surprise" in result.prompt

    def test_expression_defaults_to_neutral_when_missing(self):
        result = self._call({"facs_action_units": "AU6", "description": "nothing"})
        assert "neutral" in result.prompt

    def test_empty_facs_action_units(self):
        expr_entry = {"expression": "Neutral", "facs_action_units": "", "description": "resting"}
        result = self._call(expr_entry)
        assert isinstance(result.prompt, str)

    def test_log_lines_non_empty(self):
        result = self._call(self._EXPR_ENTRY_SIMPLE)
        assert len(result.log_lines()) > 0


# ---------------------------------------------------------------------------
# Tests: _apply_prompt_gen_patches (restyle version) — real temp files
# ---------------------------------------------------------------------------


def _ensure_script_paths_on_sys_path() -> None:
    """Ensure src/, scripts/learn/, and scripts/examples/ are on sys.path."""
    root = Path(__file__).resolve().parents[1]
    for p in (
        root / "src",
        root / "scripts" / "learn",
        root / "scripts" / "examples",
    ):
        s = str(p)
        if s not in sys.path:
            sys.path.insert(0, s)


def _load_restyle_apply_patches():
    """Import _apply_prompt_gen_patches from learn_restyle.py.

    Caches the module in sys.modules under '_learn_restyle_mod' so repeated
    calls within a session do not re-execute the whole script.
    """
    mod_name = "_learn_restyle_mod"
    if mod_name in sys.modules:
        mod = sys.modules[mod_name]
        return mod._apply_prompt_gen_patches, mod._RESTYLE_CONFIG  # type: ignore[attr-defined]

    _ensure_script_paths_on_sys_path()
    scripts_learn = Path(__file__).resolve().parents[1] / "scripts" / "learn"
    spec = importlib.util.spec_from_file_location(mod_name, scripts_learn / "learn_restyle.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod._apply_prompt_gen_patches, mod._RESTYLE_CONFIG  # type: ignore[attr-defined]


def _load_reexpress_apply_patches():
    """Import _apply_prompt_gen_patches from learn_reexpress.py.

    Caches the module in sys.modules under '_learn_reexpress_mod'.
    """
    mod_name = "_learn_reexpress_mod"
    if mod_name in sys.modules:
        mod = sys.modules[mod_name]
        return mod._apply_prompt_gen_patches, mod._REEXPRESS_CONFIG  # type: ignore[attr-defined]

    _ensure_script_paths_on_sys_path()
    scripts_learn = Path(__file__).resolve().parents[1] / "scripts" / "learn"
    spec = importlib.util.spec_from_file_location(mod_name, scripts_learn / "learn_reexpress.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod._apply_prompt_gen_patches, mod._REEXPRESS_CONFIG  # type: ignore[attr-defined]


_INITIAL_RESTYLE_YAML = """\
prompt_template: "Old template. {style_description}."
negative_prompt: "blurry"
width: 512
height: 512
num_inference_steps: 20
cfg_scale: 7.0
ip_adapter_scale: 0.7
lora: null
lora_weight: 1.0
"""

_INITIAL_REEXPRESS_YAML = """\
prompt_template: "Old reexpress. {expression_name}, {facs_au_codes}."
negative_prompt: "blurry, distorted"
width: 512
height: 512
num_inference_steps: 25
cfg_scale: 8.0
ip_adapter_scale: 0.6
lora: null
lora_weight: 1.0
"""


class TestApplyPromptGenPatchesRestyle:
    """Test _apply_prompt_gen_patches from learn_restyle.py using real tmp files."""

    @pytest.fixture()
    def restyle_config_file(self, tmp_path: Path):
        """Create a real temp restyle.yml and monkey-patch the module's _RESTYLE_CONFIG."""
        cfg_file = tmp_path / "restyle.yml"
        cfg_file.write_text(_INITIAL_RESTYLE_YAML)
        return cfg_file

    def _apply(self, restyle_config_file: Path, patches: dict) -> list[str]:
        apply_fn, _ = _load_restyle_apply_patches()
        # Monkey-patch the module-level _RESTYLE_CONFIG to use our temp file
        mod_name = "_learn_restyle_mod"
        mod = sys.modules.get(mod_name)
        assert mod is not None
        orig = mod._RESTYLE_CONFIG  # type: ignore[attr-defined]
        mod._RESTYLE_CONFIG = restyle_config_file  # type: ignore[attr-defined]
        try:
            return apply_fn(patches)
        finally:
            mod._RESTYLE_CONFIG = orig  # type: ignore[attr-defined]

    def test_empty_patches_returns_empty_list(self, restyle_config_file: Path):
        result = self._apply(restyle_config_file, {})
        assert result == []

    def test_apply_single_key_returns_change_description(self, restyle_config_file: Path):
        result = self._apply(restyle_config_file, {"cfg_scale": 9.0})
        assert len(result) == 1
        assert "cfg_scale" in result[0]
        assert "restyle.yml" in result[0]

    def test_change_description_includes_old_and_new(self, restyle_config_file: Path):
        result = self._apply(restyle_config_file, {"cfg_scale": 9.0})
        assert "7.0" in result[0]
        assert "9.0" in result[0]

    def test_change_description_arrow_format(self, restyle_config_file: Path):
        result = self._apply(restyle_config_file, {"cfg_scale": 9.0})
        assert "→" in result[0]

    def test_null_value_is_skipped(self, restyle_config_file: Path):
        result = self._apply(restyle_config_file, {"cfg_scale": None})
        assert result == []

    def test_file_updated_after_apply(self, restyle_config_file: Path):
        self._apply(restyle_config_file, {"cfg_scale": 10.0})
        updated = yaml.safe_load(restyle_config_file.read_text())
        assert updated["cfg_scale"] == 10.0

    def test_apply_multiple_keys(self, restyle_config_file: Path):
        result = self._apply(
            restyle_config_file,
            {"cfg_scale": 9.0, "ip_adapter_scale": 0.9},
        )
        assert len(result) == 2

    def test_mix_of_null_and_real_values(self, restyle_config_file: Path):
        result = self._apply(
            restyle_config_file,
            {"cfg_scale": 9.0, "ip_adapter_scale": None},
        )
        assert len(result) == 1
        assert "cfg_scale" in result[0]

    def test_negative_prompt_updated(self, restyle_config_file: Path):
        result = self._apply(restyle_config_file, {"negative_prompt": "new bad stuff"})
        assert len(result) == 1
        updated = yaml.safe_load(restyle_config_file.read_text())
        assert updated["negative_prompt"] == "new bad stuff"

    def test_prompt_template_updated(self, restyle_config_file: Path):
        new_tmpl = "New template. {style_description}. Portrait."
        result = self._apply(restyle_config_file, {"prompt_template": new_tmpl})
        assert len(result) == 1
        updated = yaml.safe_load(restyle_config_file.read_text())
        assert updated["prompt_template"] == new_tmpl

    def test_all_null_patches_does_not_write_file(self, restyle_config_file: Path):
        mtime_before = restyle_config_file.stat().st_mtime
        self._apply(restyle_config_file, {"cfg_scale": None, "ip_adapter_scale": None})
        mtime_after = restyle_config_file.stat().st_mtime
        assert mtime_before == mtime_after


class TestApplyPromptGenPatchesReexpress:
    """Test _apply_prompt_gen_patches from learn_reexpress.py using real tmp files."""

    @pytest.fixture()
    def reexpress_config_file(self, tmp_path: Path):
        cfg_file = tmp_path / "reexpress.yml"
        cfg_file.write_text(_INITIAL_REEXPRESS_YAML)
        return cfg_file

    def _apply(self, reexpress_config_file: Path, patches: dict) -> list[str]:
        apply_fn, _ = _load_reexpress_apply_patches()
        mod_name = "_learn_reexpress_mod"
        mod = sys.modules.get(mod_name)
        assert mod is not None
        orig = mod._REEXPRESS_CONFIG  # type: ignore[attr-defined]
        mod._REEXPRESS_CONFIG = reexpress_config_file  # type: ignore[attr-defined]
        try:
            return apply_fn(patches)
        finally:
            mod._REEXPRESS_CONFIG = orig  # type: ignore[attr-defined]

    def test_empty_patches_returns_empty_list(self, reexpress_config_file: Path):
        result = self._apply(reexpress_config_file, {})
        assert result == []

    def test_apply_single_key_returns_change_description(self, reexpress_config_file: Path):
        result = self._apply(reexpress_config_file, {"cfg_scale": 9.0})
        assert len(result) == 1
        assert "cfg_scale" in result[0]
        assert "reexpress.yml" in result[0]

    def test_change_description_includes_old_and_new(self, reexpress_config_file: Path):
        result = self._apply(reexpress_config_file, {"cfg_scale": 9.0})
        assert "8.0" in result[0]
        assert "9.0" in result[0]

    def test_change_description_arrow_format(self, reexpress_config_file: Path):
        result = self._apply(reexpress_config_file, {"cfg_scale": 9.0})
        assert "→" in result[0]

    def test_null_value_is_skipped(self, reexpress_config_file: Path):
        result = self._apply(reexpress_config_file, {"cfg_scale": None})
        assert result == []

    def test_file_updated_after_apply(self, reexpress_config_file: Path):
        self._apply(reexpress_config_file, {"ip_adapter_scale": 0.8})
        updated = yaml.safe_load(reexpress_config_file.read_text())
        assert updated["ip_adapter_scale"] == 0.8

    def test_apply_multiple_keys(self, reexpress_config_file: Path):
        result = self._apply(
            reexpress_config_file,
            {"cfg_scale": 9.0, "ip_adapter_scale": 0.8},
        )
        assert len(result) == 2

    def test_mix_of_null_and_real_values(self, reexpress_config_file: Path):
        result = self._apply(
            reexpress_config_file,
            {"cfg_scale": 9.0, "ip_adapter_scale": None},
        )
        assert len(result) == 1
        assert "cfg_scale" in result[0]

    def test_num_inference_steps_updated(self, reexpress_config_file: Path):
        result = self._apply(reexpress_config_file, {"num_inference_steps": 40})
        assert len(result) == 1
        updated = yaml.safe_load(reexpress_config_file.read_text())
        assert updated["num_inference_steps"] == 40

    def test_all_null_patches_does_not_write_file(self, reexpress_config_file: Path):
        mtime_before = reexpress_config_file.stat().st_mtime
        self._apply(reexpress_config_file, {"cfg_scale": None, "ip_adapter_scale": None})
        mtime_after = reexpress_config_file.stat().st_mtime
        assert mtime_before == mtime_after
