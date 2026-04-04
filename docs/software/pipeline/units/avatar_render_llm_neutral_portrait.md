# avatar_render_llm_neutral_portrait

**Parent**: `avatar_render_llm` | **Type**: image model call | **Testable**: integration (mock at gateway)

## Purpose
Generates the canonical neutral portrait — the identity anchor for the avatar. Called once per persona; output is the reference image for all expression variants.

## Inputs
- Full prompt (from `avatar_render_llm_prompt_builder`, neutral expression)
- Gateway URL, width, height, optimize, seed

## Outputs
- PNG file at `out_path`
- PNG has generation metadata embedded (see Appendix A.3)

## Behavior
1. Call `GatewayClient.image_gen(prompt, width, height, optimize, seed, reference_images_b64=None)`.
2. Open returned bytes as PIL Image.
3. Embed PNG metadata chunks: prompt, persona YAML, style YAML, expression YAML, copyright.
4. Save to `out_path`.
5. Write session artifacts to `session_dir/`: `prompt.txt`, `style.yml`, `expression.yml`, `output.png`.

## Notes
- `reference_images_b64` is `None` here — distinguishes Step E from Step F at the gateway level.
- If the gateway returns no image data, raise `RuntimeError`.
