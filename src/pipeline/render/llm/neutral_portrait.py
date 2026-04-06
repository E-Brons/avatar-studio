"""Neutral portrait generator — no reference image."""

from __future__ import annotations

from pathlib import Path

from pipeline.render.llm.orchestrator import render_llm


def generate_neutral_portrait(
    persona_path: Path,
    *,
    style: dict,
    gateway_url: str = "http://127.0.0.1:4096",
    width: int = 256,
    height: int = 256,
    optimize: str = "normal",
    seed: int | None = None,
    out_path: Path,
    session_dir: Path | None = None,
) -> Path:
    """Generate the neutral portrait.

    Delegates to ``render_llm`` with ``expression="neutral"`` and no reference.
    """
    return render_llm(
        persona_path,
        style=style,
        expression_name="neutral",
        reference_image=None,
        gateway_url=gateway_url,
        width=width,
        height=height,
        optimize=optimize,
        seed=seed,
        out_path=out_path,
        session_dir=session_dir,
    )
