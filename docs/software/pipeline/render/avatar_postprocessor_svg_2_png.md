# avatar_postprocessor_svg_2_png

**Parent**: `avatar_postprocessor` | **Type**: pure function | **Testable**: unit

## Purpose
Rasterizes an SVG file to PNG at the target canvas size.

## Inputs
- SVG file path (or bytes)
- `size`: target canvas size in pixels (width = height)

## Outputs
- PNG bytes at the target size

## Notes
- Applied to Programmatic render outputs only — LLM outputs are already PNG.
- Renderer library: e.g. `cairosvg` or equivalent. Preserves RGBA transparency.
