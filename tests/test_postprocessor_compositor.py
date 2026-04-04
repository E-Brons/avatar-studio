"""Tests for postprocessor compositor."""

import io

import pytest
from PIL import Image

from pipeline.render.postprocess.compositor import composite


def _make_rgba_bytes(w: int = 64, h: int = 64, color=(128, 200, 50, 255)) -> bytes:
    img = Image.new("RGBA", (w, h), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestComposite:
    def test_output_is_png(self):
        data = _make_rgba_bytes()
        result = composite(data, 64)
        img = Image.open(io.BytesIO(result))
        assert img.format == "PNG"

    def test_output_size_matches(self):
        data = _make_rgba_bytes()
        result = composite(data, 128)
        img = Image.open(io.BytesIO(result))
        assert img.size == (128, 128)

    def test_round_fill_mode(self):
        data = _make_rgba_bytes()
        result = composite(data, 64, bg_color="#FF0000", mode="round_fill")
        assert len(result) > 0

    def test_color_fill_mode(self):
        data = _make_rgba_bytes()
        result = composite(data, 64, bg_color="#0000FF", mode="color_fill")
        assert len(result) > 0

    def test_transparent_mode(self):
        data = _make_rgba_bytes()
        result = composite(data, 64, mode="transparent")
        img = Image.open(io.BytesIO(result))
        assert img.mode == "RGBA"

    def test_output_rgba_mode(self):
        data = _make_rgba_bytes()
        result = composite(data, 64)
        img = Image.open(io.BytesIO(result))
        assert img.mode == "RGBA"
