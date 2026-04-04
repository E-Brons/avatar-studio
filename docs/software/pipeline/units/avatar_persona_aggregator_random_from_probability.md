# avatar_persona_aggregator_random_from_probability

**Parent**: `avatar_request_parse_selector` | **Type**: pure function | **Testable**: unit

## Purpose
Resolves a probability selector by weighted random pick from a `{value: probability}` dict.

## Inputs
- Attribute name
- Selector spec: `{value1: p1, value2: p2, ...}` (probabilities must sum to 1.0)

## Outputs
- `aggregate[attribute_name] = one value sampled according to the given probabilities`

## Notes
- Validate that probabilities sum to ~1.0 (within floating-point tolerance) — raise if not.
