"""Tests for postprocess/svg_to_png — mocked cairosvg."""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock


def _with_fake_cairosvg():
    """Context manager that installs a fake cairosvg in sys.modules."""
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        fake = ModuleType("cairosvg")
        fake.svg2png = MagicMock()  # type: ignore[attr-defined]
        sys.modules["cairosvg"] = fake
        sys.modules.pop("pipeline.render.postprocess.svg_to_png", None)
        try:
            yield fake
        finally:
            sys.modules.pop("cairosvg", None)
            sys.modules.pop("pipeline.render.postprocess.svg_to_png", None)

    return _ctx()


class TestSvgToPng:
    def test_calls_cairosvg(self, tmp_path):
        svg = tmp_path / "test.svg"
        svg.write_text("<svg/>")
        out = tmp_path / "out.png"

        with _with_fake_cairosvg() as fake:
            from pipeline.render.postprocess.svg_to_png import svg_to_png

            svg_to_png(svg, out, size=128)
            fake.svg2png.assert_called_once_with(
                url=str(svg),
                write_to=str(out),
                output_width=128,
                output_height=128,
            )

    def test_returns_out_path(self, tmp_path):
        svg = tmp_path / "test.svg"
        svg.write_text("<svg/>")
        out = tmp_path / "sub" / "out.png"

        with _with_fake_cairosvg():
            from pipeline.render.postprocess.svg_to_png import svg_to_png

            result = svg_to_png(svg, out)
            assert result == out

    def test_creates_parent_dirs(self, tmp_path):
        svg = tmp_path / "test.svg"
        svg.write_text("<svg/>")
        out = tmp_path / "deep" / "nested" / "out.png"

        with _with_fake_cairosvg():
            from pipeline.render.postprocess.svg_to_png import svg_to_png

            svg_to_png(svg, out)
            assert out.parent.exists()

    def test_import_error_reraised(self, tmp_path):
        import pytest

        svg = tmp_path / "test.svg"
        svg.write_text("<svg/>")
        out = tmp_path / "out.png"

        # Ensure cairosvg is absent
        sys.modules.pop("cairosvg", None)
        sys.modules.pop("pipeline.render.postprocess.svg_to_png", None)
        # Use None sentinel to trigger ImportError on `import cairosvg`
        sys.modules["cairosvg"] = None  # type: ignore[assignment]
        try:
            with pytest.raises((ImportError, TypeError)):
                from pipeline.render.postprocess.svg_to_png import svg_to_png

                svg_to_png(svg, out)
        finally:
            sys.modules.pop("cairosvg", None)
            sys.modules.pop("pipeline.render.postprocess.svg_to_png", None)
