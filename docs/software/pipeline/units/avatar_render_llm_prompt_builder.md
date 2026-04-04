# avatar_render_llm_prompt_builder

**Parent**: `avatar_render_llm` | **Type**: pure function | **Testable**: unit

## Purpose
Assembles the full text prompt for one image model call, combining the style directive, the sanitized persona YAML, and the expression YAML.

## Inputs
- Avatar Persona
- Style entry
- Expression entry (from `expressions.yml`)
- `reference_image_path` (optional — present for expression variants, absent for neutral)

## Outputs
- `full_prompt: str` — the complete prompt to send to the image model

## Behavior
1. `avatar_render_llm_persona_sanitizer` → strip non-visual fields from persona.
2. `avatar_render_llm_style_directive` → build style prefix string.
3. `avatar_render_llm_facs_resolver` → resolve unilateral FACS AU placeholders in expression.
4. Build `user_prompt = f"persona profile:\n{persona_yaml}\nexpression:\n{expr_yaml}"`.
5. If `reference_image_path` set: append `"\nreference image: see the attached neutral expression avatar PNG file"`.
6. Return `f"{style_directive}\n\n{user_prompt}".strip()`.

## Notes
- Image models have no system/user turn structure — the style directive is prepended inline.

## Children
- [`avatar_render_llm_persona_sanitizer`](avatar_render_llm_persona_sanitizer.md)
- [`avatar_render_llm_style_directive`](avatar_render_llm_style_directive.md)
- [`avatar_render_llm_facs_resolver`](avatar_render_llm_facs_resolver.md)
