# avatar_render_llm_expression_variants

**Parent**: `avatar_render_llm` | **Type**: image model call (×N) | **Testable**: integration (mock at gateway)

## Purpose
Generates N expression variant PNGs by re-rendering the same person with a different expression each time, using the neutral portrait as a visual reference to anchor identity.

## Inputs
- Expression list (non-neutral expressions only)
- Neutral portrait PNG path (reference image)
- Prompt builder (called once per expression)
- Gateway URL, width, height, optimize, seed

## Outputs
- Dict: `{expression_name: png_path | None}` — `None` for any expression that failed

## Behavior
For each non-neutral expression:
1. Build prompt via `avatar_render_llm_prompt_builder` with the target expression and `reference_image_path=neutral_path`.
2. Base64-encode the neutral portrait.
3. Call `GatewayClient.image_gen(prompt, ..., reference_images_b64=[neutral_b64])`.
4. Embed PNG metadata; save to `out_path`.
5. On failure: log warning, record `None` for this expression, continue.

## Notes
- Individual expression failures are non-fatal — the dict entry is `None` and the pipeline continues.
- Session artifacts written per expression to `session_dir/<expression_name>/`: `prompt.txt`, `reference_person.png`, `output.png`.
