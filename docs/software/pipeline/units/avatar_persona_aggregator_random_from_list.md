# avatar_persona_aggregator_random_from_list

**Parent**: `avatar_request_parse_selector` | **Type**: pure function | **Testable**: unit

## Purpose
Resolves a list selector by drawing one value uniformly at random from the provided list.

## Inputs
- Attribute name
- Selector spec: `{values: [v1, v2, ...]}`

## Outputs
- `aggregate[attribute_name] = one uniformly picked value`

## Notes
- All values in the list are equally weighted. For weighted selection use `avatar_persona_aggregator_random_from_probability`.
