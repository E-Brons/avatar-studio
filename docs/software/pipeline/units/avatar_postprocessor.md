# avatar_postprocessor

**Parent**: `avatar_renderer` | **Type**: orchestrator | **Testable**: integration

## Purpose
Applies post-processing to all rendered outputs — both LLM and Programmatic paths. Converts SVGs to PNGs, removes backgrounds (LLM path), composites the sticker layout, and embeds output metadata.

## Inputs
- Dict of `{expression_name: raw_file_path}` from both render paths
- `pp_style_name` from Avatar Persona `post-process` block (`transparent`, `color-fill`, `round-fill`)
- `bg_color`, `fg_color` from Avatar Persona `post-process` block
- Target canvas size

## Outputs
- Dict of `{expression_name: final_png_path}`

## Coordinates
For each expression output:
1. If SVG: `avatar_postprocessor_svg_2_png` → rasterize to PNG.
2. If LLM PNG: `avatar_postprocessor_background_remover` → remove generated background.
3. `avatar_postprocessor_compositor` → apply sticker layout per `pp_style_name`.
4. `avatar_postprocessor_metadata` → embed acceptance scores and output metadata.

## Children
- [`avatar_postprocessor_svg_2_png`](avatar_postprocessor_svg_2_png.md)
- [`avatar_postprocessor_background_remover`](avatar_postprocessor_background_remover.md)
- [`avatar_postprocessor_compositor`](avatar_postprocessor_compositor.md)
- [`avatar_postprocessor_metadata`](avatar_postprocessor_metadata.md)
