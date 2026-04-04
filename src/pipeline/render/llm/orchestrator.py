"""LLM render orchestrator — single entry point for both Step E and Step F.

This is a thin wrapper around ``generate_avatar_image`` from
``step_ef_generate_image`` that uses the decomposed render units internally.
The old step_ef function is kept as the canonical implementation to avoid
duplication; this module re-exports it with a cleaner name.
"""

from __future__ import annotations

from pathlib import Path

from pipeline.render.expression_resolver import _EXPRESSIONS_YML
from pipeline.render.style_resolver import _STYLES_YML
from pipeline.step_ef_generate_image import generate_avatar_image


def render_llm(
    persona_path: Path,
    *,
    style: dict,
    expression_name: str,
    reference_image: Path | None = None,
    gateway_url: str = "http://127.0.0.1:4096",
    width: int = 256,
    height: int = 256,
    optimize: str = "normal",
    seed: int | None = None,
    out_path: Path,
    session_dir: Path | None = None,
) -> Path:
    """Generate an avatar image via the LLM Gateway (Step E or F).

    Thin delegation to ``generate_avatar_image`` with a normalized interface.
    """
    styles_yml = style.get("styles_yml", _STYLES_YML)
    expressions_yml = _EXPRESSIONS_YML

    return generate_avatar_image(
        persona_path,
        style={
            "name": style.get("name", "random"),
            "bg_color": style.get("bg_color", "#F5F0E8"),
            "styles_yml": styles_yml,
        },
        expression={"name": expression_name, "expressions_yml": expressions_yml},
        reference_image=reference_image,
        gateway_url=gateway_url,
        width=width,
        height=height,
        optimize=optimize,
        seed=seed,
        out_path=out_path,
        session_dir=session_dir,
    )
