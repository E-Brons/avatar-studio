# avatar_render_style_resolver

**Parent**: `avatar_renderer` | **Type**: pure lookup | **Testable**: unit

## Purpose
Looks up the `style_id` from the Avatar Request in `styles.yml` and returns the full style definition, including render family (LLM or Programmatic), system prompt, and key technical traits.

## Inputs
- `style_id` (string)
- Path to `assets/styles/styles.yml`

## Outputs
- Style entry dict: `{id, name, family, system_prompt, key_technical_traits, ...}`

## Behavior
1. Load `styles.yml`.
2. Find entry where `id == style_id`.
3. Raise `UnknownStyleError` if not found.
4. Return the entry.

## Notes
- The `random` selector is resolved before this unit runs — `style_id` is always a concrete style ID by the time this unit is called.
