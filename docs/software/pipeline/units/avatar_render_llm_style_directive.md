# avatar_render_llm_style_directive

**Parent**: `avatar_render_llm_prompt_builder` | **Type**: pure function | **Testable**: unit

## Purpose
Extracts the style system prompt from the style entry and substitutes the `[BG_COLOR]` placeholder with the persona's actual background color.

## Inputs
- Style entry dict (contains `system_prompt`)
- `bg_color` from Avatar Persona `post-process` block

## Outputs
- Style directive string (ready to prepend to the full prompt)

## Behavior
1. Read `system_prompt` from style entry. Return empty string if absent (e.g. `random` style resolved at runtime).
2. Replace `[BG_COLOR]` with `bg_color`.
3. Return the substituted string.
