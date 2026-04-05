# avatar_persona_aggregator_random_from_range_color

**Parent**: `avatar_persona_aggregator_random_from_range` | **Type**: pure function | **Testable**: unit

## Purpose
Samples a random hex color by uniform linear interpolation between two hex color endpoints.

## Inputs
- `min_hex`: start color (e.g. `"#FFFFFF"`)
- `max_hex`: end color (e.g. `"#000000"`)

## Outputs
- A hex color string uniformly sampled between the two endpoints in RGB space

## Behavior
1. Parse both hex values to (R, G, B).
2. Sample `t ~ Uniform(0, 1)`.
3. Interpolate: `result_channel = int(min_channel + t * (max_channel - min_channel))`.
4. Return as `"#RRGGBB"`.
