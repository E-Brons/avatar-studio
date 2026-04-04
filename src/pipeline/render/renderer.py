"""Top-level renderer — orchestrates the full avatar render pipeline.

Replaces the ``process_advisor`` logic from ``server.py`` with a clean
interface that accepts a demographics dict and produces all avatar outputs.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pipeline.render.expression_resolver import resolve_expression_list
from pipeline.render.llm.orchestrator import render_llm
from pipeline.render.programmatic.orchestrator import render_programmatic

logger = logging.getLogger(__name__)


def render(
    persona_path: Path,
    out_dir: Path,
    slug: str,
    *,
    demographics: dict,
    expressions: list[str],
    gateway_url: str = "http://127.0.0.1:4096",
    width: int = 256,
    height: int = 256,
    optimize: str = "normal",
    seed: int | None = None,
    pa_style: str = "toon-head",
    pa_size: int = 256,
) -> dict:
    """Render all avatar outputs for one persona.

    Returns a results dict with:
      ``expressions``       — {expr_id: filename | None}
      ``programmatic``      — {expr_id: filename | None}
    """
    from pipeline.render.style_resolver import _STYLES_YML

    expressions = resolve_expression_list(expressions)
    style_arg = {
        "name": demographics.get("style", "random"),
        "bg_color": demographics.get("bg_color", "#F5F0E8"),
        "styles_yml": _STYLES_YML,
    }

    expr_map: dict[str, str | None] = {}

    # Step E — neutral portrait
    neutral_filename = f"{slug}-neutral.png"
    neutral_path = out_dir / neutral_filename
    try:
        render_llm(
            persona_path,
            style=style_arg,
            expression_name="neutral",
            reference_image=None,
            gateway_url=gateway_url,
            width=width,
            height=height,
            optimize=optimize,
            seed=seed,
            out_path=neutral_path,
            session_dir=None,
        )
        expr_map["neutral"] = neutral_filename
    except Exception as exc:
        logger.error("[render] neutral portrait failed: %s", exc)
        return {"expressions": {e: None for e in expressions}, "programmatic": {}}

    # Step F — expression variants
    for expr_id in [e for e in expressions if e != "neutral"]:
        expr_filename = f"{slug}-{expr_id}.png"
        expr_path = out_dir / expr_filename
        try:
            render_llm(
                persona_path,
                style=style_arg,
                expression_name=expr_id,
                reference_image=neutral_path,
                gateway_url=gateway_url,
                width=width,
                height=height,
                optimize=optimize,
                seed=seed,
                out_path=expr_path,
                session_dir=None,
            )
            expr_map[expr_id] = expr_filename
        except Exception as exc:
            logger.warning("[render] expression %s failed: %s", expr_id, exc)
            expr_map[expr_id] = None

    # Step D — programmatic avatar
    name = ""
    try:
        import yaml
        with open(persona_path) as f:
            persona = yaml.safe_load(f)
        name = persona.get("personal", {}).get("name", slug)
    except Exception:
        name = slug

    pa_map = render_programmatic(
        name,
        out_dir,
        slug,
        expressions,
        style=pa_style,
        size=pa_size,
        demographics=demographics,
    )

    return {"expressions": expr_map, "programmatic": pa_map}
