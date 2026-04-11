"""Restyle pipeline — re-render an existing avatar in a new style.

Identity is anchored via IP-Adapter FaceID; the text prompt is built from
the target style + expression only (no persona text — identity comes from
the reference images).
"""

from __future__ import annotations

import base64
import logging

from config.gateway import GatewayClient
from pipeline.render.expression_resolver import resolve_expression
from pipeline.render.llm.prompt_builder import build_clip_prompt_restyle
from pipeline.render.style_resolver import resolve_style
from tuning.compare_side_by_side import compare_side_by_side

logger = logging.getLogger(__name__)


def _vary_seed(base: int | None, i: int) -> int:
    return (base if base is not None else 42) + i * 1000


def restyle_avatar(
    images_b64: list[str],
    style_id: str,
    expression_id: str,
    *,
    candidates: int = 4,
    width: int = 512,
    height: int = 512,
    gateway_url: str = "http://127.0.0.1:4096",
    optimize: str = "normal",
    seed: int | None = None,
) -> bytes:
    """Re-render *images_b64* in *style_id* with *expression_id*.

    Parameters
    ----------
    images_b64:
        One or more base64-encoded PNG images of the source avatar.
    style_id:
        Target style identifier (e.g. ``"studio_3d"``).
    expression_id:
        Target expression identifier (e.g. ``"happiness"``).
    candidates:
        Number of candidate images to generate; the best is returned.
    width, height:
        Output image dimensions in pixels.
    gateway_url:
        Base URL of the LLM Gateway server.
    optimize:
        Generation quality mode: ``"quality"``, ``"normal"``, or ``"fast"``.
    seed:
        Base RNG seed; each candidate uses ``seed + i * 1000``.

    Returns
    -------
    bytes
        Raw PNG bytes of the best candidate (highest identity score).
    """
    style_entry, _ = resolve_style(style_id)
    expr_entry = resolve_expression(expression_id)
    clip_prompt = build_clip_prompt_restyle(style_entry, expr_entry)

    client = GatewayClient(gateway_url)
    source_bytes = base64.b64decode(images_b64[0])

    best_bytes: bytes | None = None
    best_score: float = -1.0

    for i in range(candidates):
        candidate_bytes = client.ipadapter_faceid(
            clip_prompt,
            images_b64,
            seed=_vary_seed(seed, i),
            width=width,
            height=height,
            optimize=optimize,
        )
        try:
            result = compare_side_by_side(
                source_bytes,
                candidate_bytes,
                goal="re-render in a new style",
                reference_label="source",
                generated_label="restyled",
                gateway_url=gateway_url,
            )
            score = result.identity_score
        except Exception as exc:
            logger.warning("restyle_avatar: scoring failed for candidate %d: %s", i, exc)
            score = 0.0

        if score > best_score:
            best_score = score
            best_bytes = candidate_bytes

    assert best_bytes is not None
    return best_bytes
