# avatar_persona_aggregator_random_from_range_color

**Parent**: `avatar_persona_aggregator_random_from_range` | **Type**: pure function | **Testable**: unit

## Purpose
Samples a random hex color by uniform linear interpolation between two hex color endpoints.

## Inputs
- `min_hex`: start color (e.g. `"#FFFFFF"`)
- `max_hex`: end color (e.g. `"#000000"`)

## Outputs
- A hex color string uniformly sampled between the two endpoints

## Behavior
1. Convert both hex values to YCbCr.
2. Sample a single `t ~ Uniform(0, 1)` (shared across all channels).
3. Interpolate each channel: `result_channel = min_channel + t * (max_channel - min_channel)`.
4. Convert result back to RGB and return as `"#RRGGBB"`.

## Design notes

**Single shared `t`**: all three channels use the same scalar `t`. This samples uniformly along the *line* between the two endpoint colors in the interpolation space. Independent per-channel `t` values would instead sample from the full 3D rectangular box between the two endpoints — a much larger and less meaningful region for a "range between two colors" semantic.

**YCbCr interpolation space**: interpolating in RGB is perceptually non-uniform — the midpoint at `t=0.5` rarely falls at the perceptual midpoint between the two endpoints, and the path tends toward dark/desaturated values. YCbCr separates luminance (Y) from chrominance (Cb, Cr), so uniform `t` maps to uniform perceptual distance. This matters especially for skin tones and hair colors where the `min`/`max` define a meaningful perceptual corridor.
