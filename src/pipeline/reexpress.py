"""Reexpress pipeline — apply a new expression to an existing avatar.

Identity is anchored via IP-Adapter FaceID; the CLIP prompt is built from the
target expression and its FACS action units only (style identity comes from the
reference image). Candidates are ranked by side-by-side compound score with
expression classification as a tiebreaker.
"""

from __future__ import annotations

import base64
import logging

from config.gateway import GatewayClient
from pipeline.render.expression_resolver import resolve_expression
from pipeline.render.llm.prompt_builder import build_clip_prompt_reexpress
from tuning.classify_expression import classify_image_expression
from tuning.compare_side_by_side import compare_side_by_side

logger = logging.getLogger(__name__)


def _vary_seed(base: int | None, i: int) -> int:
    return (base if base is not None else 42) + i * 1000


def reexpress_avatar(
    images_b64: list[str],
    expression_id: str,
    *,
    candidates: int = 4,
    width: int = 512,
    height: int = 512,
    gateway_url: str = "http://127.0.0.1:4096",
    optimize: str = "normal",
    seed: int | None = None,
) -> bytes:
    """Apply *expression_id* to the avatar in *images_b64*.

    Parameters
    ----------
    images_b64:
        One or more base64-encoded PNG images of the source avatar.
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
        Raw PNG bytes of the best candidate.
    """
    source_bytes = base64.b64decode(images_b64[0])

    expr_entry = resolve_expression(expression_id)
    clip_prompt = build_clip_prompt_reexpress(expr_entry)

    client = GatewayClient(gateway_url)

    scored: list[tuple[float, float, bytes]] = []  # (compound_score, expr_top_score, bytes)

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
            sbs = compare_side_by_side(
                source_bytes,
                candidate_bytes,
                goal=f"change expression to {expression_id}",
                reference_label="source",
                generated_label="reexpressed",
                gateway_url=gateway_url,
            )
            compound = sbs.compound_score
        except Exception as exc:
            logger.warning("reexpress_avatar: SBS scoring failed for candidate %d: %s", i, exc)
            compound = 0.0

        try:
            expr_result = classify_image_expression(
                candidate_bytes,
                [expression_id],
                gateway_url=gateway_url,
            )
            expr_top = expr_result.top_score()
        except Exception as exc:
            logger.warning(
                "reexpress_avatar: expression classification failed for candidate %d: %s", i, exc
            )
            expr_top = 0.0

        scored.append((compound, expr_top, candidate_bytes))

    # Sort by compound_score descending; use expr_top_score as tiebreaker
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return scored[0][2]
