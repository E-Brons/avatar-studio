# avatar_render_programmatic

**Parent**: `avatar_renderer` | **Type**: orchestrator | **Testable**: integration

## Purpose
Orchestrates the Programmatic render path: maps each expression to DiceBear component options and generates one SVG per expression.

## Inputs
- Avatar Persona (only `bg_color` is consumed)
- Style entry (DiceBear style ID)
- Expression list
- Output directory

## Outputs
- Dict: `{expression_name: svg_path}` for all expressions

## Coordinates
1. For each expression: call `avatar_render_programmatic_expression_mapper` to get component options.
2. Call `avatar_render_programmatic_svg_generator` with name seed, style, size, options.
3. Collect SVG paths.

## Notes
- Failure of the whole path (Node.js unavailable) is non-fatal at the `avatar_renderer` level.

## Children
- [`avatar_render_programmatic_expression_mapper`](avatar_render_programmatic_expression_mapper.md)
- [`avatar_render_programmatic_svg_generator`](avatar_render_programmatic_svg_generator.md)
