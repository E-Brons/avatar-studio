# avatar_render_programmatic_expression_mapper

**Parent**: `avatar_render_programmatic` | **Type**: pure lookup | **Testable**: unit

## Purpose
Maps a canonical expression name to the DiceBear (or Opeeps) component override options for a given style.

## Inputs
- `style_id`: e.g. `"toon-head"`, `"avataaars"`, `"micah"`, `"bottts"`, `"opeeps"`
- `expression_name`: canonical expression name (e.g. `"happiness"`, `"anger"`)

## Outputs
- Options dict: e.g. `{"eyes": ["happy"], "mouth": ["laugh"], "eyebrows": ["happy"]}`
- Empty dict if no mapping exists for the style/expression combination

## Source
Mapping table defined in `src/pipeline/step_d_make_programmatic_avatar.py → EXPRESSION_OPTIONS`. See also [step_d2.md](../step_d2.md) for the full 5×6 table.

## Notes
- `bottts` style has no `eyebrows` key — only `eyes` and `mouth`.
- `opeeps` uses singular keys (`eye`, `mouth`, `eyebrow`) vs. DiceBear's plural keys.
