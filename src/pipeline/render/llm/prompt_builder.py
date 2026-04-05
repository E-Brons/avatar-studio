"""Prompt builder — assemble the full image-generation prompt."""

from __future__ import annotations

import yaml

from pipeline.render.llm.facs_resolver import resolve_unilateral


def build_prompt(
    persona: dict,
    expr_entry: dict,
    style_directive: str,
    *,
    reference_image: bool = False,
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
    reference_image:
        When True, appends the reference image note (expression variant).
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
    if reference_image:
        user_prompt += "\nreference image: see the attached neutral expression avatar PNG file"

    return f"{style_directive}\n\n{user_prompt}".strip() if style_directive else user_prompt
