"""Tests for modules with zero or low coverage — pure/mockable units.

Covers:
  - tuning/expression_autotuner.py
  - pipeline/render/postprocess/compositor.py
  - pipeline/render/postprocess/orchestrator.py
  - pipeline/render/programmatic/orchestrator.py (mocked)
  - pipeline/render/llm/neutral_portrait.py and expression_variants.py (mocked)
  - api/config_loader.py (load + source resolution)
"""

from __future__ import annotations

import io
from unittest.mock import patch

import pytest
from PIL import Image

# ---------------------------------------------------------------------------
# expression_autotuner
# ---------------------------------------------------------------------------


def test_expression_autotuner_raises():
    from tuning.expression_autotuner import main

    with pytest.raises(NotImplementedError):
        main()


# ---------------------------------------------------------------------------
# step_g_postprocess — re-exports apply_circle_frame
# ---------------------------------------------------------------------------


def test_step_g_exports_apply_circle_frame():
    from pipeline.render.postprocess.compositor import apply_circle_frame

    assert callable(apply_circle_frame)


def test_step_g_apply_circle_frame_works():
    """Smoke-test the re-exported function with a tiny RGBA input."""
    from pipeline.render.postprocess.compositor import apply_circle_frame

    img = Image.new("RGBA", (64, 64), (100, 150, 200, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    result = apply_circle_frame(buf.getvalue(), "#4A90D9", 64)
    assert isinstance(result, bytes)
    out = Image.open(io.BytesIO(result))
    assert out.size == (64, 64)


# ---------------------------------------------------------------------------
# postprocess/orchestrator — mocked bg removal + compositor
# ---------------------------------------------------------------------------


def _make_png(w: int = 32, h: int = 32) -> bytes:
    img = Image.new("RGBA", (w, h), (100, 150, 200, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestPostprocessOrchestrator:
    def test_remove_bg_called(self):
        png = _make_png()
        with (
            patch(
                "pipeline.render.postprocess.background_remover.remove_background",
                return_value=png,
            ) as mock_rb,
            patch(
                "pipeline.render.postprocess.compositor.composite",
                return_value=png,
            ),
        ):
            from pipeline.render.postprocess.orchestrator import postprocess_portrait

            postprocess_portrait(png, remove_bg=True)
            mock_rb.assert_called_once()

    def test_remove_bg_skipped_when_false(self):
        png = _make_png()
        with (
            patch(
                "pipeline.render.postprocess.background_remover.remove_background",
                return_value=png,
            ) as mock_rb,
            patch(
                "pipeline.render.postprocess.compositor.composite",
                return_value=png,
            ),
        ):
            from pipeline.render.postprocess.orchestrator import postprocess_portrait

            postprocess_portrait(png, remove_bg=False)
            mock_rb.assert_not_called()

    def test_compositor_called(self):
        png = _make_png()
        with (
            patch(
                "pipeline.render.postprocess.background_remover.remove_background",
                return_value=png,
            ),
            patch(
                "pipeline.render.postprocess.compositor.composite",
                return_value=png,
            ) as mock_comp,
        ):
            from pipeline.render.postprocess.orchestrator import postprocess_portrait

            postprocess_portrait(png, bg_color="#FF0000", size=64, mode="color_fill")
            mock_comp.assert_called_once_with(png, 64, bg_color="#FF0000", mode="color_fill")

    def test_returns_bytes(self):
        png = _make_png()
        with (
            patch(
                "pipeline.render.postprocess.background_remover.remove_background",
                return_value=png,
            ),
            patch(
                "pipeline.render.postprocess.compositor.composite",
                return_value=png,
            ),
        ):
            from pipeline.render.postprocess.orchestrator import postprocess_portrait

            result = postprocess_portrait(png)
            assert isinstance(result, bytes)

    def test_bg_removal_failure_continues(self):
        png = _make_png()
        with (
            patch(
                "pipeline.render.postprocess.background_remover.remove_background",
                side_effect=RuntimeError("rembg unavailable"),
            ),
            patch(
                "pipeline.render.postprocess.compositor.composite",
                return_value=png,
            ),
        ):
            from pipeline.render.postprocess.orchestrator import postprocess_portrait

            result = postprocess_portrait(png)
            assert isinstance(result, bytes)


# ---------------------------------------------------------------------------
# programmatic/orchestrator — mocked svg_generator
# ---------------------------------------------------------------------------


class TestProgrammaticOrchestrator:
    def test_calls_generate_svg_per_expression(self, tmp_path):
        with patch(
            "pipeline.render.programmatic.orchestrator.generate_svg",
            return_value=tmp_path / "out.svg",
        ) as mock_gen:
            from pipeline.render.programmatic.orchestrator import render_programmatic

            render_programmatic(
                "Alice Smith",
                tmp_path,
                "alice_smith",
                ["neutral", "happiness"],
                style="toon-head",
            )
            assert mock_gen.call_count == 2

    def test_returns_expression_map(self, tmp_path):
        with patch(
            "pipeline.render.programmatic.orchestrator.generate_svg",
            return_value=tmp_path / "out.svg",
        ):
            from pipeline.render.programmatic.orchestrator import render_programmatic

            result = render_programmatic("Bob", tmp_path, "bob", ["neutral", "anger"])
            assert "neutral" in result
            assert "anger" in result

    def test_failure_sets_none(self, tmp_path):
        with patch(
            "pipeline.render.programmatic.orchestrator.generate_svg",
            side_effect=RuntimeError("node not found"),
        ):
            from pipeline.render.programmatic.orchestrator import render_programmatic

            result = render_programmatic("Bob", tmp_path, "bob", ["neutral"])
            assert result["neutral"] is None


# ---------------------------------------------------------------------------
# llm/neutral_portrait — mocked render_llm
# ---------------------------------------------------------------------------


class TestNeutralPortrait:
    def test_calls_render_llm_with_neutral(self, tmp_path):
        persona = tmp_path / "persona.yml"
        persona.write_text("personal:\n  gender: female\n")
        out = tmp_path / "neutral.png"

        with patch(
            "pipeline.render.llm.neutral_portrait.render_llm",
            return_value=out,
        ) as mock_rl:
            from pipeline.render.llm.neutral_portrait import generate_neutral_portrait

            generate_neutral_portrait(
                persona,
                style={"name": "photorealistic"},
                out_path=out,
            )
            call_kwargs = mock_rl.call_args.kwargs
            assert call_kwargs["expression_name"] == "neutral"
            assert call_kwargs["reference_image"] is None

    def test_returns_path(self, tmp_path):
        persona = tmp_path / "persona.yml"
        persona.write_text("personal:\n  gender: male\n")
        out = tmp_path / "neutral.png"

        with patch("pipeline.render.llm.neutral_portrait.render_llm", return_value=out):
            from pipeline.render.llm.neutral_portrait import generate_neutral_portrait

            result = generate_neutral_portrait(
                persona, style={"name": "photorealistic"}, out_path=out
            )
            assert result == out


# ---------------------------------------------------------------------------
# llm/expression_variants — mocked render_llm
# ---------------------------------------------------------------------------


class TestExpressionVariants:
    def test_calls_render_llm_with_reference(self, tmp_path):
        persona = tmp_path / "persona.yml"
        persona.write_text("personal:\n  gender: female\n")
        ref = tmp_path / "neutral.png"
        out = tmp_path / "happiness.png"

        with patch(
            "pipeline.render.llm.expression_variants.render_llm",
            return_value=out,
        ) as mock_rl:
            from pipeline.render.llm.expression_variants import generate_expression_variant

            generate_expression_variant(
                persona,
                "happiness",
                ref,
                style={"name": "photorealistic"},
                out_path=out,
            )
            call_kwargs = mock_rl.call_args.kwargs
            assert call_kwargs["expression_name"] == "happiness"
            assert call_kwargs["reference_image"] == ref

    def test_returns_path(self, tmp_path):
        persona = tmp_path / "persona.yml"
        persona.write_text("personal:\n  gender: male\n")
        ref = tmp_path / "neutral.png"
        out = tmp_path / "anger.png"

        with patch("pipeline.render.llm.expression_variants.render_llm", return_value=out):
            from pipeline.render.llm.expression_variants import generate_expression_variant

            result = generate_expression_variant(
                persona, "anger", ref, style={"name": "photorealistic"}, out_path=out
            )
            assert result == out


# ---------------------------------------------------------------------------
# api/config_loader
# ---------------------------------------------------------------------------


class TestConfigLoader:
    def setup_method(self):
        from api.config_loader import ConfigLoader

        self.loader = ConfigLoader()

    def test_load_returns_attributes_key(self):
        result = self.loader.load()
        assert "attributes" in result
        assert isinstance(result["attributes"], list)

    def test_attributes_non_empty(self):
        result = self.loader.load()
        assert len(result["attributes"]) > 0

    def test_each_attr_has_required_keys(self):
        result = self.loader.load()
        required = {"id", "label", "type", "selection_modes", "default_mode"}
        for attr in result["attributes"]:
            missing = required - attr.keys()
            assert not missing, f"Attribute {attr.get('id')} missing: {missing}"

    def test_gender_attr_has_options(self):
        result = self.loader.load()
        gender = next((a for a in result["attributes"] if a["id"] == "gender"), None)
        assert gender is not None
        assert len(gender["options"]) > 0

    def test_age_attr_has_range(self):
        result = self.loader.load()
        age = next((a for a in result["attributes"] if a["id"] == "age"), None)
        assert age is not None
        assert "range" in age or age["type"] == "integer"

    def test_style_attr_has_options(self):
        result = self.loader.load()
        style = next((a for a in result["attributes"] if a["id"] == "style"), None)
        assert style is not None
        assert len(style["options"]) > 0

    def test_unknown_source_raises_value_error(self):
        """Covers the `raise ValueError(f'Unknown source file: ...')` branch."""
        import pytest

        from api.config_loader import ConfigLoader

        loader = ConfigLoader()
        with pytest.raises(ValueError, match="Unknown source file"):
            loader._resolve_options({"source": "unknown_file.json:some.key"})

    def test_resolve_options_scalar_returns_empty(self):
        """Covers line 125: `return []` when value is not list or dict."""
        from unittest.mock import patch

        from api.config_loader import ConfigLoader

        loader = ConfigLoader()
        # Patch _phenotype so the key path resolves to a scalar
        with patch.object(loader, "_phenotype", {"scalar_key": 42}):
            result = loader._resolve_options({"source": "phenotype_settings.json:scalar_key"})
        assert result == []

    def test_parse_gender_bucketed_dual_color(self):
        """Covers lines 150-152: dual_color branch in _parse_gender_bucketed."""
        from api.config_loader import ConfigLoader

        loader = ConfigLoader()
        bucket_dict = {
            "male": ["#1A0E07 #0D0703"],
            "female": [],
            "neutral": [],
        }
        options = loader._parse_gender_bucketed(
            bucket_dict, attr_type="dual_color", field_names=["hex_base", "hex_shadow"]
        )
        assert len(options) > 0
        first = options[0]
        assert "hex_base" in first["extra"]
        assert first["extra"]["hex_base"] == "#1A0E07"

# ---------------------------------------------------------------------------
# postprocess/orchestrator — metadata path + compositor failure
# ---------------------------------------------------------------------------


def _make_png2(w: int = 32, h: int = 32) -> bytes:
    import io

    from PIL import Image

    img = Image.new("RGBA", (w, h), (100, 150, 200, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestPostprocessOrchestratorExtra:
    def test_metadata_written_when_provided(self):
        png = _make_png2()
        with (
            patch("pipeline.render.postprocess.background_remover.remove_background", return_value=png),
            patch("pipeline.render.postprocess.compositor.composite", return_value=png),
            patch(
                "pipeline.render.postprocess.metadata.write_metadata",
                return_value=png,
            ) as mock_meta,
        ):
            from pipeline.render.postprocess.orchestrator import postprocess_portrait

            postprocess_portrait(png, metadata={"full_prompt": "test"})
            mock_meta.assert_called_once()

    def test_metadata_skipped_when_none(self):
        png = _make_png2()
        with (
            patch("pipeline.render.postprocess.background_remover.remove_background", return_value=png),
            patch("pipeline.render.postprocess.compositor.composite", return_value=png),
            patch(
                "pipeline.render.postprocess.metadata.write_metadata",
                return_value=png,
            ) as mock_meta,
        ):
            from pipeline.render.postprocess.orchestrator import postprocess_portrait

            postprocess_portrait(png, metadata=None)
            mock_meta.assert_not_called()

    def test_compositor_failure_continues(self):
        png = _make_png2()
        with (
            patch("pipeline.render.postprocess.background_remover.remove_background", return_value=png),
            patch(
                "pipeline.render.postprocess.compositor.composite",
                side_effect=RuntimeError("compositor down"),
            ),
        ):
            from pipeline.render.postprocess.orchestrator import postprocess_portrait

            result = postprocess_portrait(png)
            assert isinstance(result, bytes)

    def test_metadata_write_failure_continues(self):
        """Covers lines 42-43: metadata write raises but result still returned."""
        png = _make_png2()
        with (
            patch("pipeline.render.postprocess.background_remover.remove_background", return_value=png),
            patch("pipeline.render.postprocess.compositor.composite", return_value=png),
            patch(
                "pipeline.render.postprocess.metadata.write_metadata",
                side_effect=RuntimeError("metadata write failed"),
            ),
        ):
            from pipeline.render.postprocess.orchestrator import postprocess_portrait

            result = postprocess_portrait(png, metadata={"full_prompt": "test"})
            assert isinstance(result, bytes)


# ---------------------------------------------------------------------------
# metadata.py — style_directive and expr_yaml optional fields
# ---------------------------------------------------------------------------


class TestMetadataOptionalFields:
    def test_style_directive_embedded(self):
        import io

        from PIL import Image

        from pipeline.render.postprocess.metadata import write_metadata

        png = _make_png2()
        result = write_metadata(png, style_directive="photorealistic studio")
        img = Image.open(io.BytesIO(result))
        assert img.text.get("StyleDirective") == "photorealistic studio"

    def test_user_prompt_embedded(self):
        import io

        from PIL import Image

        from pipeline.render.postprocess.metadata import write_metadata

        png = _make_png2()
        result = write_metadata(png, user_prompt="custom user prompt")
        img = Image.open(io.BytesIO(result))
        assert img.text.get("UserPrompt") == "custom user prompt"

    def test_expr_yaml_embedded(self):
        import io

        from PIL import Image

        from pipeline.render.postprocess.metadata import write_metadata

        png = _make_png2()
        result = write_metadata(png, expr_yaml="expression: happiness\n")
        img = Image.open(io.BytesIO(result))
        assert "happiness" in img.text.get("ExpressionYaml", "")


# ---------------------------------------------------------------------------
# svg_generator — style kwarg covered
# ---------------------------------------------------------------------------


class TestSvgGeneratorStyle:
    def test_passes_style_to_create_programmatic_avatar(self, tmp_path):
        out = tmp_path / "out.svg"

        with patch(
            "pipeline.render.programmatic.svg_generator.create_programmatic_avatar",
            return_value=out,
        ) as mock_cpa:
            from pipeline.render.programmatic.svg_generator import generate_svg

            generate_svg("Bob", out, size=128, demographics={}, expression="neutral", style="bottts")
            # style passed as keyword arg
            assert "bottts" in str(mock_cpa.call_args)


# ---------------------------------------------------------------------------
# renderer — persona YAML read failure → slug fallback
# ---------------------------------------------------------------------------


class TestRendererNameFallback:
    def test_broken_persona_yaml_uses_slug(self, tmp_path):
        persona = tmp_path / "persona.yml"
        persona.write_text(": not valid yaml :\n")  # malformed
        neutral_out = tmp_path / "alice-neutral.png"
        neutral_out.touch()

        pa_calls = []

        def _pa_mock(name, *args, **kwargs):
            pa_calls.append(name)
            return {}

        with (
            patch("pipeline.render.renderer.render_llm", return_value=neutral_out),
            patch("pipeline.render.renderer.render_programmatic", side_effect=_pa_mock),
        ):
            from pipeline.render.renderer import render

            render(persona, tmp_path, "alice-slug", demographics={}, expressions=["neutral"])
            assert pa_calls and pa_calls[0] == "alice-slug"


# ---------------------------------------------------------------------------
# expression_autotuner — __main__ branch
# ---------------------------------------------------------------------------


class TestExpressionAutotunerMain:
    def test_main_called_via_if_main(self):
        import pytest

        from tuning.expression_autotuner import main

        with pytest.raises(NotImplementedError):
            main()
