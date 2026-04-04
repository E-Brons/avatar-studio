"""Expression variant generator — Step F (with reference image)."""

from __future__ import annotations

from pathlib import Path

from pipeline.render.llm.orchestrator import render_llm


def generate_expression_variant(
    persona_path: Path,
    expression_name: str,
    reference_image: Path,
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
    """Generate one expression variant (Step F).

    Delegates to ``render_llm`` with a reference image.
    """
    return render_llm(
        persona_path,
        style=style,
        expression_name=expression_name,
        reference_image=reference_image,
        gateway_url=gateway_url,
        width=width,
        height=height,
        optimize=optimize,
        seed=seed,
        out_path=out_path,
        session_dir=session_dir,
    )
