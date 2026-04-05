"""Tests for postprocess/background_remover — mocked rembg."""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

from PIL import Image


def _make_png() -> bytes:
    img = Image.new("RGBA", (32, 32), (100, 150, 200, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestRemoveBackground:
    def test_calls_rembg_remove(self):
        png = _make_png()
        mock_session = MagicMock()

        with (
            patch("rembg.remove", return_value=png) as mock_remove,
            patch(
                "pipeline.render.postprocess.background_remover._get_rembg_session",
                return_value=mock_session,
            ),
        ):
            from pipeline.render.postprocess.background_remover import remove_background

            result = remove_background(png)
            mock_remove.assert_called_once_with(png, session=mock_session)
            assert result == png

    def test_returns_bytes(self):
        png = _make_png()
        mock_session = MagicMock()

        with (
            patch("rembg.remove", return_value=png),
            patch(
                "pipeline.render.postprocess.background_remover._get_rembg_session",
                return_value=mock_session,
            ),
        ):
            from pipeline.render.postprocess.background_remover import remove_background

            result = remove_background(png)
            assert isinstance(result, bytes)
