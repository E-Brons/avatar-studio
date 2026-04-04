"""PNG metadata writer — embed pipeline inputs into PNG tEXt chunks."""

from __future__ import annotations

import io

import yaml
from PIL import Image, PngImagePlugin


def write_metadata(
    image_bytes: bytes,
    *,
    gateway_url: str = "",
    style_directive: str = "",
    user_prompt: str = "",
    full_prompt: str = "",
    persona_yaml: str = "",
    style_entry: dict | None = None,
    expr_yaml: str = "",
) -> bytes:
    """Embed pipeline metadata into *image_bytes* PNG tEXt chunks."""
    img = Image.open(io.BytesIO(image_bytes))
    meta = PngImagePlugin.PngInfo()
    meta.add_text("Copyright", "\u00a9 2026 MyBoard & Elkana Bronstein")
    if gateway_url:
        meta.add_text("GatewayUrl", gateway_url)
    if style_directive:
        meta.add_text("StyleDirective", style_directive)
    if user_prompt:
        meta.add_text("UserPrompt", user_prompt)
    if full_prompt:
        meta.add_text("Prompt", full_prompt)
    if persona_yaml:
        meta.add_text("PersonaYaml", persona_yaml)
    if style_entry:
        meta.add_text(
            "StyleYaml",
            yaml.dump(style_entry, default_flow_style=False, sort_keys=False, allow_unicode=True),
        )
    if expr_yaml:
        meta.add_text("ExpressionYaml", expr_yaml)

    out = io.BytesIO()
    img.save(out, format="PNG", pnginfo=meta)
    return out.getvalue()
