"""Prompt builder — assemble the full image-generation prompt."""

from __future__ import annotations

from typing import Literal

import yaml

from pipeline.render.llm.facs_resolver import resolve_unilateral

ReferenceMode = Literal["none", "person_photo", "avatar_portrait", "style_transfer"]

# Per-mode reference instructions.  {source_style} is substituted for style_transfer.
_REFERENCE_INSTRUCTIONS: dict[str, str] = {
    "person_photo": (
        "Reference photograph: A real photo of the person described above.\n"
        "Your task: Generate this specific individual's portrait in the style specified.\n"
        "Identity — preserve faithfully: face shape and proportions, skin tone, hair color and "
        "form, eye shape, distinctive facial features and markings.\n"
        "Framing — head-and-shoulders portrait, clean uncluttered background as defined by the "
        "style. No additional background elements, props, or environmental context.\n"
        "Style — apply fully as directed. Do not copy photographic artifacts into illustrative "
        "styles (e.g. no bokeh, no pores, no depth-of-field in cartoon/clay/lineart)."
    ),
    "avatar_portrait": (
        "Reference portrait: The existing avatar of this person in the target style.\n"
        "Your task: Re-render this exact avatar with the new expression specified above.\n"
        "Preserve exactly: every visual detail — face shape, hair, skin tone, eye shape, "
        "clothing, accessories, background, and all style rendering details.\n"
        "Change only: the facial expression as described in the expression section above. "
        "No other changes whatsoever."
    ),
    "style_transfer": (
        "Reference avatar: The existing avatar of this person rendered in {source_style} style.\n"
        "Your task: Re-render this person in the new style specified in the style directive.\n"
        "Preserve: face shape and proportions, skin tone family, hair color and form, "
        "clothing colors and items, accessories, and overall identity.\n"
        "Transform: apply the new style's rendering fully — reinterpret texture, shading, "
        "line weight, color depth, and lighting model per the style directive.\n"
        "Do not carry over: rendering artifacts specific to {source_style} "
        "(e.g. if source is photorealistic: discard skin pores, bokeh, photographic grain; "
        "if source is illustrative: do not carry over simplified flat fills into a realistic render)."
    ),
}


def build_prompt(
    persona: dict,
    expr_entry: dict,
    style_directive: str,
    *,
    reference_mode: ReferenceMode = "none",
    source_style_name: str | None = None,
) -> str:
    """Return the full prompt string for the image model.

    Parameters
    ----------
    persona:
        Visual-only persona dict (already sanitized).
    expr_entry:
        Expression entry dict with ``expression``, ``facs_action_units``,
        ``description`` fields.
    style_directive:
        Prepended verbatim before the user content.
    reference_mode:
        How the attached reference image should be interpreted:
        - ``"none"``: no reference image attached.
        - ``"person_photo"``: reference is a real photograph of the person;
          preserve identity while applying target style.
        - ``"avatar_portrait"``: reference is an existing avatar in the target
          style; preserve all appearance, change expression only.
        - ``"style_transfer"``: reference is an existing avatar in a different
          source style; preserve identity while transforming the rendering.
    source_style_name:
        Human-readable name of the source style (e.g. ``"photorealistic"``).
        Required when ``reference_mode="style_transfer"``; ignored otherwise.
    """
    persona_for_prompt = {k: v for k, v in persona.items() if k != "style"}
    persona_yaml = yaml.dump(
        persona_for_prompt, default_flow_style=False, sort_keys=False, allow_unicode=True
    )

    expr_name = expr_entry.get("expression", expr_entry.get("id", "neutral"))
    facs = resolve_unilateral(expr_entry.get("facs_action_units", ""))
    expr_for_prompt = {
        "Expression": expr_name,
        "FACS": facs,
        "Description": expr_entry.get("description", ""),
    }
    expr_yaml = yaml.dump(
        expr_for_prompt, default_flow_style=False, sort_keys=False, allow_unicode=True
    )

    user_prompt = f"persona profile:\n{persona_yaml}\nexpression:\n{expr_yaml}"

    if reference_mode != "none":
        tmpl = _REFERENCE_INSTRUCTIONS[reference_mode]
        ref_instruction = tmpl.format(source_style=source_style_name or "previous style")
        user_prompt += f"\n\n{ref_instruction}"

    return f"{style_directive}\n\n{user_prompt}".strip() if style_directive else user_prompt
