"""Post-processor orchestrator — SVG→PNG, bg removal, compositor, metadata."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def postprocess_portrait(
    image_bytes: bytes,
    *,
    bg_color: str = "#FFFFFF",
    size: int = 256,
    mode: str = "round_fill",
    remove_bg: bool = True,
    metadata: dict | None = None,
) -> bytes:
    """Apply bg removal + compositing + metadata to *image_bytes*.

    Returns processed PNG bytes.
    """
    from pipeline.render.postprocess.background_remover import remove_background
    from pipeline.render.postprocess.compositor import composite
    from pipeline.render.postprocess.metadata import write_metadata

    processed = image_bytes
    if remove_bg:
        try:
            processed = remove_background(processed)
        except Exception as exc:
            logger.warning("[postprocess] background removal failed: %s", exc)

    try:
        processed = composite(processed, size, bg_color=bg_color, mode=mode)
    except Exception as exc:
        logger.warning("[postprocess] compositor failed: %s", exc)

    if metadata:
        try:
            processed = write_metadata(processed, **metadata)
        except Exception as exc:
            logger.warning("[postprocess] metadata write failed: %s", exc)

    return processed
