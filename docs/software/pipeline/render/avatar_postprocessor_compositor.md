# avatar_postprocessor_compositor

**Parent**: `avatar_postprocessor` | **Type**: pure function | **Testable**: unit

## Purpose
Composites a background-removed portrait onto the appropriate background layout, as determined by `pp_style_name`.

## Inputs
- Portrait PNG bytes (RGBA, background transparent)
- `pp_style_name`: `"transparent"` | `"color-fill"` | `"round-fill"`
- `bg_color`: hex background color
- `fg_color`: hex foreground/text color
- `size`: output canvas size in pixels

## Outputs
- Composite PNG bytes

## Behavior per style

| `pp_style_name` | Output |
|---|---|
| `transparent` | Portrait only on transparent canvas — no background added |
| `color-fill` | Portrait composited over a solid color full-bleed square |
| `round-fill` | Portrait composited over a colored circle (33% radius) with 6px white sticker border; portrait at 80% canvas height, extending above/below the circle |

## Child
- [`avatar_postprocessor_metadata`](avatar_postprocessor_metadata.md)

## Notes
- The `round-fill` layout constants: circle radius = `size × 0.33`, border = 6 px, portrait height = `size × 0.80`.
- LANCZOS resampling used for portrait scaling.
