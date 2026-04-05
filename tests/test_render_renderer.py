"""Tests for render/renderer.py top-level orchestrator — mocked."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch


def _write_persona(path: Path, name: str = "Alice") -> Path:
    path.write_text(f"personal:\n  name: {name}\n")
    return path


class TestRenderer:
    def test_returns_expressions_and_programmatic_keys(self, tmp_path):
        persona = _write_persona(tmp_path / "persona.yml")
        neutral_out = tmp_path / "alice-neutral.png"
        neutral_out.touch()

        with (
            patch(
                "pipeline.render.renderer.render_llm",
                return_value=neutral_out,
            ),
            patch(
                "pipeline.render.renderer.render_programmatic",
                return_value={"neutral": tmp_path / "pa.svg"},
            ),
        ):
            from pipeline.render.renderer import render

            result = render(
                persona,
                tmp_path,
                "alice",
                demographics={"style": "photorealistic"},
                expressions=["neutral", "happiness"],
            )
            assert "expressions" in result
            assert "programmatic" in result

    def test_neutral_portrait_in_expressions(self, tmp_path):
        persona = _write_persona(tmp_path / "persona.yml")
        neutral_out = tmp_path / "alice-neutral.png"
        neutral_out.touch()

        with (
            patch("pipeline.render.renderer.render_llm", return_value=neutral_out),
            patch(
                "pipeline.render.renderer.render_programmatic",
                return_value={},
            ),
        ):
            from pipeline.render.renderer import render

            result = render(
                persona,
                tmp_path,
                "alice",
                demographics={},
                expressions=["neutral"],
            )
            assert result["expressions"].get("neutral") is not None

    def test_expression_variant_failure_sets_none(self, tmp_path):
        persona = _write_persona(tmp_path / "persona.yml")
        neutral_out = tmp_path / "alice-neutral.png"
        neutral_out.touch()

        call_count = 0

        def _llm_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return neutral_out
            raise RuntimeError("gateway down")

        with (
            patch("pipeline.render.renderer.render_llm", side_effect=_llm_side_effect),
            patch("pipeline.render.renderer.render_programmatic", return_value={}),
        ):
            from pipeline.render.renderer import render

            result = render(
                persona,
                tmp_path,
                "alice",
                demographics={},
                expressions=["neutral", "happiness"],
            )
            assert result["expressions"]["neutral"] is not None
            assert result["expressions"]["happiness"] is None

    def test_neutral_failure_returns_all_none(self, tmp_path):
        persona = _write_persona(tmp_path / "persona.yml")

        with (
            patch("pipeline.render.renderer.render_llm", side_effect=RuntimeError("fail")),
            patch("pipeline.render.renderer.render_programmatic", return_value={}),
        ):
            from pipeline.render.renderer import render

            result = render(
                persona,
                tmp_path,
                "alice",
                demographics={},
                expressions=["neutral", "happiness"],
            )
            assert all(v is None for v in result["expressions"].values())

    def test_persona_name_read_from_yaml(self, tmp_path):
        persona = _write_persona(tmp_path / "persona.yml", name="Bob Jones")
        neutral_out = tmp_path / "bob-neutral.png"
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

            render(persona, tmp_path, "bob", demographics={}, expressions=["neutral"])
            assert pa_calls and pa_calls[0] == "Bob Jones"
