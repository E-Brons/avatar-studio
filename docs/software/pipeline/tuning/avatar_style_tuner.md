# avatar_style_tuner

**Type**: CLI agent | **Testable**: unit (helpers) + integration (generate→classify loop)

## Purpose
Iterative style tuning loop: generate avatar portraits for a given style × gender × expression
combination, classify the output by style, and report pass/fail statistics.  Edit `styles.yml`
`system_prompt` between runs to improve style distinctiveness.

## Inputs
- `--style` — style ID(s) (or `all`)
- `--gender` — gender(s) (or `all` / `random`)
- `--expression` — expression ID(s) (default: `neutral`)
- `--runs` — number of generation passes per combination
- `--seed` — optional fixed seed for reproducibility
- `--watch` — re-run automatically when `styles.yml` changes

## Outputs
- Generated PNG images in `tmp/style_tuning/<session>/`
- Per-run classification result (PASS / FAIL) printed to stdout
- Aggregated pass-rate table per style at end of run

## Coordinates
1. Load `styles.yml` and `expressions.yml` (fresh, bypasses module cache).
2. For each (style × gender × expression) tuple, call `generate_avatar_image` via `GatewayClient`.
3. Classify the generated image using `classify_image_style` (litellm VLM call).
4. Score result: PASS if top style label matches; FAIL otherwise.
5. Aggregate and print pass-rate summary.

## Children
- [`pipeline.render.llm.orchestrator.generate_avatar_image`](../render/avatar_render_llm.md)
- `tuning.classify_style.classify_image_style`
- `pipeline.persona.generator.pick_demographics`
- `pipeline.persona.aggregator_llm.generate_advisor_profile`
- `pipeline.persona.generator.build_avatar_charachter`
