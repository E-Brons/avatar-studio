"""Tests for pipeline/render/llm/orchestrator.py render_llm."""

from __future__ import annotations

from unittest.mock import patch


class TestRenderLlm:
    def test_delegates_to_generate_avatar_image(self, tmp_path):
        persona = tmp_path / "persona.yml"
        persona.write_text("personal:\n  gender: female\n")
        out = tmp_path / "neutral.png"

        with patch(
            "pipeline.render.llm.orchestrator.generate_avatar_image",
            return_value=out,
        ) as mock_gen:
            from pipeline.render.llm.orchestrator import render_llm

            result = render_llm(
                persona,
                style={"name": "photorealistic"},
                expression_name="neutral",
                out_path=out,
            )
            assert mock_gen.call_count == 1
            assert result == out

    def test_style_name_passed_through(self, tmp_path):
        persona = tmp_path / "persona.yml"
        persona.write_text("personal:\n  gender: male\n")
        out = tmp_path / "out.png"

        with patch(
            "pipeline.render.llm.orchestrator.generate_avatar_image",
            return_value=out,
        ) as mock_gen:
            from pipeline.render.llm.orchestrator import render_llm

            render_llm(
                persona,
                style={"name": "clay"},
                expression_name="happiness",
                out_path=out,
            )
            call_kwargs = mock_gen.call_args.kwargs
            assert call_kwargs["style"]["name"] == "clay"
            assert call_kwargs["expression"]["name"] == "happiness"

    def test_custom_styles_yml_used(self, tmp_path):
        """Covers the styles_yml fallback line (line 36)."""
        persona = tmp_path / "persona.yml"
        persona.write_text("personal:\n  gender: female\n")
        out = tmp_path / "out.png"
        custom_yml = tmp_path / "custom_styles.yml"
        custom_yml.write_text("styles: []\n")

        with patch(
            "pipeline.render.llm.orchestrator.generate_avatar_image",
            return_value=out,
        ) as mock_gen:
            from pipeline.render.llm.orchestrator import render_llm

            render_llm(
                persona,
                style={"name": "random", "styles_yml": custom_yml},
                expression_name="neutral",
                out_path=out,
            )
            call_kwargs = mock_gen.call_args.kwargs
            assert call_kwargs["style"]["styles_yml"] == custom_yml

    def test_reference_image_forwarded(self, tmp_path):
        persona = tmp_path / "persona.yml"
        persona.write_text("personal:\n  gender: female\n")
        ref = tmp_path / "ref.png"
        ref.touch()
        out = tmp_path / "out.png"

        with patch(
            "pipeline.render.llm.orchestrator.generate_avatar_image",
            return_value=out,
        ) as mock_gen:
            from pipeline.render.llm.orchestrator import render_llm

            render_llm(
                persona,
                style={"name": "photorealistic"},
                expression_name="happiness",
                reference_image=ref,
                out_path=out,
            )
            call_kwargs = mock_gen.call_args.kwargs
            assert call_kwargs["reference_image"] == ref
