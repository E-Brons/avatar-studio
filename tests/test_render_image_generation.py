"""Tests for the image generation pipeline — mocked GatewayClient."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from PIL import Image

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_png(w: int = 64, h: int = 64) -> bytes:
    img = Image.new("RGBA", (w, h), (120, 150, 200, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _write_styles_yml(path: Path, style_id: str = "photorealistic") -> None:
    data = {
        "styles": [
            {
                "id": style_id,
                "name": "Photorealistic",
                "create": {
                    "llm_params": {"system_prompt_template": "photorealistic portrait [BG_COLOR]"}
                },
            }
        ]
    }

    path.write_text(yaml.dump(data))


def _write_expressions_yml(path: Path, expr_id: str = "neutral") -> None:
    data = {
        "expressions": [
            {
                "id": expr_id,
                "expression": expr_id.capitalize(),
                "facs_action_units": "AU1 AU2x",
                "description": f"A {expr_id} face.",
            }
        ]
    }
    path.write_text(yaml.dump(data))


def _write_persona_yml(path: Path) -> None:
    persona = {
        "personal": {"name": "Alice", "gender": "female", "age": 30},
        "advisor": {"role": "Advisor"},
        "appearance": {"hair_style": "bob"},
    }
    path.write_text(yaml.dump(persona))


# ---------------------------------------------------------------------------
# _resolve_unilateral
# ---------------------------------------------------------------------------


class TestResolveUnilateral:
    def test_no_placeholder(self):
        from pipeline.render.llm.facs_resolver import resolve_unilateral

        result = resolve_unilateral("AU1 AU2 AU4")
        assert result == "AU1 AU2 AU4"

    def test_placeholder_replaced(self):
        from pipeline.render.llm.facs_resolver import resolve_unilateral

        result = resolve_unilateral("AU1x AU2x")
        # Each AUNNx replaced with AUNNR or AUNNL
        assert "AU1x" not in result
        assert "AU2x" not in result
        assert "AU1R" in result or "AU1L" in result

    def test_empty_string(self):
        from pipeline.render.llm.facs_resolver import resolve_unilateral

        assert resolve_unilateral("") == ""


# ---------------------------------------------------------------------------
# generate_avatar_image — neutral portrait
# ---------------------------------------------------------------------------


class TestGenerateAvatarImage:
    def _setup(self, tmp_path: Path):
        styles_yml = tmp_path / "styles.yml"
        expr_yml = tmp_path / "expressions.yml"
        persona_yml = tmp_path / "persona.yml"
        _write_styles_yml(styles_yml)
        _write_expressions_yml(expr_yml)
        _write_persona_yml(persona_yml)
        out = tmp_path / "out.png"
        return styles_yml, expr_yml, persona_yml, out

    def test_returns_out_path(self, tmp_path):
        styles_yml, expr_yml, persona_yml, out = self._setup(tmp_path)

        with patch("pipeline.render.llm.orchestrator.GatewayClient") as MockClient:
            MockClient.return_value.image_gen.return_value = _make_png()
            from pipeline.render.llm.orchestrator import generate_avatar_image

            result = generate_avatar_image(
                persona_yml,
                style={"name": "photorealistic", "styles_yml": str(styles_yml), "bg_color": "#FFF"},
                expression={"name": "neutral", "expressions_yml": str(expr_yml)},
                gateway_url="http://127.0.0.1:4096",
                out_path=out,
            )
            assert result == out
            assert out.exists()

    def test_calls_image_gen(self, tmp_path):
        styles_yml, expr_yml, persona_yml, out = self._setup(tmp_path)

        with patch("pipeline.render.llm.orchestrator.GatewayClient") as MockClient:
            MockClient.return_value.image_gen.return_value = _make_png()
            from pipeline.render.llm.orchestrator import generate_avatar_image

            generate_avatar_image(
                persona_yml,
                style={"name": "photorealistic", "styles_yml": str(styles_yml)},
                expression={"name": "neutral", "expressions_yml": str(expr_yml)},
                gateway_url="http://gw",
                out_path=out,
            )
            MockClient.assert_called_once_with("http://gw")
            MockClient.return_value.image_gen.assert_called_once()

    def test_with_reference_image(self, tmp_path):
        styles_yml, expr_yml, persona_yml, out = self._setup(tmp_path)
        ref = tmp_path / "neutral.png"
        ref.write_bytes(_make_png())

        with patch("pipeline.render.llm.orchestrator.GatewayClient") as MockClient:
            MockClient.return_value.image_gen.return_value = _make_png()
            from pipeline.render.llm.orchestrator import generate_avatar_image

            result = generate_avatar_image(
                persona_yml,
                style={"name": "photorealistic", "styles_yml": str(styles_yml)},
                expression={"name": "happiness", "expressions_yml": str(expr_yml)},
                gateway_url="http://gw",
                out_path=out,
                reference_image=ref,
            )
            assert result == out
            call_kwargs = MockClient.return_value.image_gen.call_args.kwargs
            assert call_kwargs["reference_images_b64"] is not None

    def test_seed_passed_to_image_gen(self, tmp_path):
        styles_yml, expr_yml, persona_yml, out = self._setup(tmp_path)

        with patch("pipeline.render.llm.orchestrator.GatewayClient") as MockClient:
            MockClient.return_value.image_gen.return_value = _make_png()
            from pipeline.render.llm.orchestrator import generate_avatar_image

            generate_avatar_image(
                persona_yml,
                style={"name": "photorealistic", "styles_yml": str(styles_yml)},
                expression={"name": "neutral", "expressions_yml": str(expr_yml)},
                gateway_url="http://gw",
                out_path=out,
                seed=42,
            )
            call_kwargs = MockClient.return_value.image_gen.call_args.kwargs
            assert call_kwargs.get("seed") == 42

    def test_session_dir_artifacts_written(self, tmp_path):
        styles_yml, expr_yml, persona_yml, out = self._setup(tmp_path)
        session_dir = tmp_path / "session"

        with patch("pipeline.render.llm.orchestrator.GatewayClient") as MockClient:
            MockClient.return_value.image_gen.return_value = _make_png()
            from pipeline.render.llm.orchestrator import generate_avatar_image

            generate_avatar_image(
                persona_yml,
                style={"name": "photorealistic", "styles_yml": str(styles_yml)},
                expression={"name": "neutral", "expressions_yml": str(expr_yml)},
                gateway_url="http://gw",
                out_path=out,
                session_dir=session_dir,
            )
            assert (session_dir / "prompt.txt").exists()
            assert (session_dir / "style.yml").exists()
            assert (session_dir / "expression.yml").exists()

    def test_bg_color_substituted_in_style_directive(self, tmp_path):
        styles_yml, expr_yml, persona_yml, out = self._setup(tmp_path)

        captured_prompt = {}

        with patch("pipeline.render.llm.orchestrator.GatewayClient") as MockClient:

            def _capture(prompt="", **kwargs):
                captured_prompt["full"] = prompt
                return _make_png()

            MockClient.return_value.image_gen.side_effect = _capture
            from pipeline.render.llm.orchestrator import generate_avatar_image

            generate_avatar_image(
                persona_yml,
                style={
                    "name": "photorealistic",
                    "styles_yml": str(styles_yml),
                    "bg_color": "#AABBCC",
                },
                expression={"name": "neutral", "expressions_yml": str(expr_yml)},
                gateway_url="http://gw",
                out_path=out,
            )
            assert "#AABBCC" in captured_prompt["full"]

    def test_unknown_style_still_works(self, tmp_path):
        """When style not in styles.yml, style_directive is empty."""
        styles_yml, expr_yml, persona_yml, out = self._setup(tmp_path)

        with patch("pipeline.render.llm.orchestrator.GatewayClient") as MockClient:
            MockClient.return_value.image_gen.return_value = _make_png()
            from pipeline.render.llm.orchestrator import generate_avatar_image

            result = generate_avatar_image(
                persona_yml,
                style={"name": "unknown_style", "styles_yml": str(styles_yml)},
                expression={"name": "neutral", "expressions_yml": str(expr_yml)},
                gateway_url="http://gw",
                out_path=out,
            )
            assert result == out

    def test_session_dir_artifact_failure_continues(self, tmp_path):
        """Covers the except block around session artifact writes."""
        styles_yml, expr_yml, persona_yml, out = self._setup(tmp_path)
        session_dir = tmp_path / "session"

        # Make only session_dir.mkdir raise; out_path.parent already exists (tmp_path)
        _real_mkdir = Path.mkdir

        def _selective_mkdir(self_path, **kwargs):
            if self_path == session_dir:
                raise OSError("disk full")
            return _real_mkdir(self_path, **kwargs)

        with (
            patch("pipeline.render.llm.orchestrator.GatewayClient") as MockClient,
            patch.object(Path, "mkdir", _selective_mkdir),
        ):
            MockClient.return_value.image_gen.return_value = _make_png()
            from pipeline.render.llm.orchestrator import generate_avatar_image

            result = generate_avatar_image(
                persona_yml,
                style={"name": "photorealistic", "styles_yml": str(styles_yml)},
                expression={"name": "neutral", "expressions_yml": str(expr_yml)},
                gateway_url="http://gw",
                out_path=out,
                session_dir=session_dir,
            )
            # Even if session dir writing fails, result returned
            assert result == out

    def test_reference_image_copied_to_session_dir(self, tmp_path):
        """Covers line 212: shutil.copy2 when reference_image exists + session_dir set."""
        styles_yml, expr_yml, persona_yml, out = self._setup(tmp_path)
        ref = tmp_path / "neutral.png"
        ref.write_bytes(_make_png())
        session_dir = tmp_path / "session"

        with patch("pipeline.render.llm.orchestrator.GatewayClient") as MockClient:
            MockClient.return_value.image_gen.return_value = _make_png()
            from pipeline.render.llm.orchestrator import generate_avatar_image

            generate_avatar_image(
                persona_yml,
                style={"name": "photorealistic", "styles_yml": str(styles_yml)},
                expression={"name": "happiness", "expressions_yml": str(expr_yml)},
                gateway_url="http://gw",
                out_path=out,
                reference_image=ref,
                session_dir=session_dir,
            )
            assert (session_dir / "reference_person.png").exists()


# ---------------------------------------------------------------------------
# pick_diverse_demographics — while-loop fill branches (lines 198, 205)
# ---------------------------------------------------------------------------


class TestPickDiverseDemographicsWhileLoops:
    def test_age_fill_loop_fires(self, monkeypatch):
        """Force age while loop by making _AGE_GROUPS tiny."""
        import pipeline.persona.generator as mod

        real_groups = mod._AGE_GROUPS
        monkeypatch.setattr(mod, "_AGE_GROUPS", [(20, 30)])  # only 1 group
        try:
            result = mod._pick_diverse_demographics(count=3)
            assert len(result) == 3
        finally:
            monkeypatch.setattr(mod, "_AGE_GROUPS", real_groups)

    def test_skin_tone_fill_loop_fires(self, monkeypatch):
        """Force skin_tone while loop by making _SKIN_TONES tiny."""
        import pipeline.persona.generator as mod

        real_tones = mod._SKIN_TONES
        monkeypatch.setattr(mod, "_SKIN_TONES", ["#FFFFFF"])  # only 1 tone
        try:
            result = mod._pick_diverse_demographics(count=3)
            assert len(result) == 3
        finally:
            monkeypatch.setattr(mod, "_SKIN_TONES", real_tones)


# ---------------------------------------------------------------------------
# svg_generator — _vendor_dir raises FileNotFoundError (line 87)
# ---------------------------------------------------------------------------


class TestVendorDirMissing:
    def test_vendor_dir_raises_when_generate_js_absent(self, monkeypatch):
        """Covers line 87: raise FileNotFoundError in _vendor_dir."""
        from pathlib import Path
        from unittest.mock import patch

        with patch.object(Path, "exists", return_value=False):
            import importlib

            import pipeline.render.programmatic.svg_generator as mod

            importlib.reload(mod)
            with pytest.raises(FileNotFoundError, match="generate.js not found"):
                mod._vendor_dir()
