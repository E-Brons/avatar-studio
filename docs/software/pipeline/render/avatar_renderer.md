# avatar_renderer

**Type**: orchestrator | **Testable**: integration (via children)

## Purpose
Top-level unit for §3.2. Accepts an Avatar Persona and Avatar Request render parameters; produces the final set of expression PNGs.

## Inputs
- Avatar Persona (from §3.1)
- `style_id` from Avatar Request
- `expression_id` from Avatar Request

## Outputs
- Set of final PNG files, one per expression

## Coordinates
1. `avatar_render_style_resolver` — resolve style definition.
2. `avatar_render_expression_resolver` — resolve expression set.
3. Branch on style family:
   - LLM → `avatar_render_llm`
   - Programmatic → `avatar_render_programmatic`
4. `avatar_postprocessor` — post-process all outputs.

## Children
- [`avatar_render_style_resolver`](avatar_render_style_resolver.md)
- [`avatar_render_expression_resolver`](avatar_render_expression_resolver.md)
- [`avatar_render_llm`](avatar_render_llm.md)
- [`avatar_render_programmatic`](avatar_render_programmatic.md)
- [`avatar_postprocessor`](avatar_postprocessor.md)
