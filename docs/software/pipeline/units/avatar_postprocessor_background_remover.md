# avatar_postprocessor_background_remover

**Parent**: `avatar_postprocessor` | **Type**: ML inference | **Testable**: integration (mock with fixture)

## Purpose
Removes the background from a raw portrait PNG, producing an RGBA image with transparent background, ready for compositing.

## Inputs
- PNG bytes (raw portrait, with background)

## Outputs
- RGBA PNG bytes (background made transparent)

## Behavior
1. Call `rembg.remove(image_bytes, session=_rembg_session)`.
2. Return RGBA PNG bytes.

## Notes
- Applied to LLM render outputs only — Programmatic outputs (SVG → PNG via `avatar_postprocessor_svg_2_png`) already have transparent backgrounds.
- The `u2net` ONNX model session is a process-level singleton (`_rembg_session`) — loaded once on first call.
- Mocking strategy: supply a fixture image with background already removed.
