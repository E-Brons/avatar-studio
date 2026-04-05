# avatar_persona_marshal

**Parent**: `avatar_request_serve` | **Type**: pure function | **Testable**: unit

## Purpose
Converts the flat aggregate dict of resolved attribute values into the structured Avatar Persona format and serializes it to the output format (YAML or JSON).

## Inputs
- Aggregate dict: `{attribute_name: resolved_value, ...}`

## Outputs
- Serialized Avatar Persona (see Appendix A.2)

## Behavior
1. Map flat attribute keys into the Avatar Persona structure: `personal`, `appearance`, `post-process` sections.
2. Expand multi-value color fields into named sub-dicts (e.g. `HAIR_COLOR "#BASE #SHADOW"` → `{hex_base, hex_shadow}`).
3. Serialize to output format (YAML by default).

## Notes
- The `post-process` block (`pp_style_name`, `bg_color`, `fg_color`) is written to the persona but **not** passed to the image model — it is consumed only by `avatar_postprocessor`.
- `eye_shape` is present in the persona but stripped by `avatar_render_llm_persona_sanitizer` before prompt construction.
