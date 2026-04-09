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


def _make_transparent_png(transparent_fraction: float = 0.5) -> bytes:
    """Make a 32×32 RGBA PNG with a given fraction of fully-transparent pixels."""
    import numpy as np

    arr = np.zeros((32, 32, 4), dtype=np.uint8)
    arr[:, :, :3] = [100, 150, 200]
    arr[:, :, 3] = 255  # fully opaque
    cutoff = int(32 * transparent_fraction)
    arr[:cutoff, :, 3] = 0  # top rows fully transparent
    img = Image.fromarray(arr, mode="RGBA")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestRemoveBackground:
    def test_calls_rembg_remove_with_alpha_matting(self):
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

            remove_background(png)
            mock_remove.assert_called_once_with(
                png,
                session=mock_session,
                alpha_matting=True,
                alpha_matting_foreground_threshold=240,
                alpha_matting_background_threshold=10,
                alpha_matting_erode_size=10,
            )

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

    def test_skips_rembg_when_already_transparent(self):
        """Images with >5% transparent pixels are passed through without rembg."""
        transparent_png = _make_transparent_png(transparent_fraction=0.5)
        mock_session = MagicMock()

        with (
            patch("rembg.remove") as mock_remove,
            patch(
                "pipeline.render.postprocess.background_remover._get_rembg_session",
                return_value=mock_session,
            ),
        ):
            from pipeline.render.postprocess.background_remover import remove_background

            result = remove_background(transparent_png)
            mock_remove.assert_not_called()
            assert isinstance(result, bytes)

    def test_does_not_skip_rembg_for_opaque_image(self):
        """Fully opaque images (no existing transparency) still go through rembg."""
        opaque_png = _make_png()  # all pixels alpha=255
        mock_session = MagicMock()

        with (
            patch("rembg.remove", return_value=opaque_png) as mock_remove,
            patch(
                "pipeline.render.postprocess.background_remover._get_rembg_session",
                return_value=mock_session,
            ),
        ):
            from pipeline.render.postprocess.background_remover import remove_background

            remove_background(opaque_png)
            mock_remove.assert_called_once()


class TestRemoveBackgroundForStyle:
    def test_illustration_styles_use_flood_fill(self):
        """korean/lineart/clay route to remove_background_illustration."""
        png = _make_png()

        with patch(
            "pipeline.render.postprocess.background_remover.remove_background_illustration",
            return_value=png,
        ) as mock_ff:
            from pipeline.render.postprocess.background_remover import (
                remove_background_for_style,
            )

            for style in ("korean", "lineart", "clay", "Korean", "LINEART"):
                mock_ff.reset_mock()
                remove_background_for_style(png, style)
                mock_ff.assert_called_once()

    def test_ml_styles_use_remove_background(self):
        """studio_3d/photorealistic route to remove_background (u2net)."""
        png = _make_png()

        with patch(
            "pipeline.render.postprocess.background_remover.remove_background",
            return_value=png,
        ) as mock_ml:
            from pipeline.render.postprocess.background_remover import (
                remove_background_for_style,
            )

            for style in ("studio_3d", "photorealistic", "Studio_3D"):
                mock_ml.reset_mock()
                remove_background_for_style(png, style)
                mock_ml.assert_called_once()

    def test_unknown_style_raises(self):
        import pytest

        from pipeline.render.postprocess.background_remover import (
            remove_background_for_style,
        )

        with pytest.raises(ValueError, match="watercolor"):
            remove_background_for_style(b"", "watercolor")
