# avatar_persona_aggregator_random_from_range

**Parent**: `avatar_request_parse_selector` | **Type**: pure function | **Testable**: unit

## Purpose
Resolves a range selector by sampling uniformly from `[min, max]`. Handles integer ranges directly; delegates color ranges to `avatar_persona_aggregator_random_from_range_color`.

## Inputs
- Attribute name
- Selector spec: `{min: <value>, max: <value>}`

## Outputs
- `aggregate[attribute_name] = sampled value`

## Behavior
1. Detect value type: if `min`/`max` are hex color strings → delegate to `avatar_persona_aggregator_random_from_range_color`.
2. Otherwise: `randint(min, max)` for integers.

## Child
- [`avatar_persona_aggregator_random_from_range_color`](avatar_persona_aggregator_random_from_range_color.md)
