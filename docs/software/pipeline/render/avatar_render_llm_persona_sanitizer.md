# avatar_render_llm_persona_sanitizer

**Parent**: `avatar_render_llm_prompt_builder` | **Type**: pure function | **Testable**: unit

## Purpose
Strips non-visual and potentially problematic fields from the Avatar Persona before it is serialized into the image model prompt.

## Inputs
- Full Avatar Persona dict

## Outputs
- Sanitized persona dict (subset of input)

## Fields removed
| Field | Reason |
|---|---|
| `personal.name` | Model may render name as literal text |
| `advisor.education`, `advisor.experience`, `advisor.traits` | Text-heavy; model renders as text, not visuals |
| `post-process` block | Compositing metadata — not visual identity |
| `appearance.eye_shape` | Rendering owned by style system prompt; persona eye shape would conflict |

## Notes
- All other `appearance` fields are kept — they describe the person's visual identity.
- String values are also sanitized to strip any system-prompt injection markers.
