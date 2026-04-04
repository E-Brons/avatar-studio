# avatar_render_llm

**Parent**: `avatar_renderer` | **Type**: orchestrator | **Testable**: integration

## Purpose
Orchestrates the LLM render path: generates the neutral portrait once, then generates expression variants using the neutral portrait as a reference image.

## Inputs
- Avatar Persona
- Style entry (from `avatar_render_style_resolver`)
- Expression list (from `avatar_render_expression_resolver`)
- Gateway URL, image size, optimize flag

## Outputs
- Dict mapping expression name → output PNG path (or `None` on failure)

## Coordinates
1. Build prompt via `avatar_render_llm_prompt_builder` for the neutral expression.
2. Call `avatar_render_llm_neutral_portrait` — one image model call.
3. For each non-neutral expression: call `avatar_render_llm_expression_variants` with the neutral PNG as reference.
4. Collect results; individual expression failures recorded as `None` (non-fatal).

## Children
- [`avatar_render_llm_prompt_builder`](avatar_render_llm_prompt_builder.md)
- [`avatar_render_llm_neutral_portrait`](avatar_render_llm_neutral_portrait.md)
- [`avatar_render_llm_expression_variants`](avatar_render_llm_expression_variants.md)
