# avatar_render_expression_resolver

**Parent**: `avatar_renderer` | **Type**: pure function | **Testable**: unit

## Purpose
Resolves the `expression_id` value from the Avatar Request to a concrete ordered list of expression names.

## Inputs
- `expression_id`: one of — single name `"happiness"`, list `["happiness", "anger"]`, `"all"`, `"random"`
- Path to `assets/expressions/expressions.yml`

## Outputs
- `list[str]` — concrete expression names, always including `"neutral"` first

## Behavior
1. Load `expressions.yml` to get the full defined expression set.
2. Resolve:
   - Single name → `["neutral", name]`
   - List → `["neutral", *list]` (deduplicated)
   - `"all"` → `["neutral", *all_defined_expressions]`
   - `"random"` → `["neutral", one_uniform_pick]`
3. Return the list.

## Notes
- `"neutral"` is always prepended — it is required as the identity anchor for LLM expression variants and must always be generated.
