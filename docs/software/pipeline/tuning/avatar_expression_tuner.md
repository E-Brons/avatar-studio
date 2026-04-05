# avatar_expression_tuner

**Type**: CLI agent | **Testable**: unit (helpers) + integration (generate→classify loop)

## Purpose
Iterative expression tuning loop: generate avatar portraits for a given expression × style × gender
combination, classify the output, and report pass/fail statistics.  Edit `expressions.yml`
FACS/description between runs to improve recognition.

## Inputs
- `--expression` — one or more expression IDs (or `all`)
- `--style` — style ID(s) (or `all`)
- `--gender` — gender(s) (or `all` / `random`)
- `--runs` — number of generation passes per combination
- `--seed` — optional fixed seed for reproducibility
- `--watch` — re-run automatically when `expressions.yml` changes

## Outputs
- Generated PNG images in `tmp/expression_tuning/<session>/`
- Per-run classification result (PASS / SEMANTIC / FAIL) printed to stdout
- Aggregated pass-rate table per style at end of run

## Coordinates
1. Load `expressions.yml` (fresh, bypasses module cache so `--watch` picks up edits).
2. For each (expression × style × gender) tuple, call `generate_avatar_image` via `GatewayClient`.
3. Classify the generated image using `classify_image_expression` (litellm VLM call).
4. Score result: VISIBLE if top label matches + score ≥ threshold; SEMANTIC if synonym
   sum ≥ threshold; FAIL otherwise.
5. Aggregate and print pass-rate summary.

## Children
- [`pipeline.render.llm.orchestrator.generate_avatar_image`](../render/avatar_render_llm.md)
- `tuning.classify_expression.classify_image_expression`
- `pipeline.persona.generator.pick_demographics`
- `pipeline.persona.aggregator_llm.generate_advisor_profile`
- `pipeline.persona.generator.build_avatar_charachter`
