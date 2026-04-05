# avatar_persona_aggregator_from_inherited

**Parent**: `avatar_request_parse_selector` | **Type**: pure lookup | **Testable**: unit

## Purpose
Resolves an inherit selector by reading the parent attribute's current value from the aggregate and mapping it to the derived value via the selector's lookup table.

## Inputs
- Attribute name
- Selector spec: `{parent_attribute: <name>, mapping: {parent_value: derived_value, ...}}`
- Current aggregate (parent attribute must already be resolved)

## Outputs
- `aggregate[attribute_name] = derived_value for aggregate[parent_attribute]`

## Behavior
1. Read `parent_value = aggregate[parent_attribute]`.
2. Look up `derived_value = mapping[parent_value]`.
3. Write `aggregate[attribute_name] = derived_value`.

## Notes
- Constraint: the parent attribute must have been resolved before this unit runs (no circular inherit chains).
- Example: `FIRST_NAME` inherits from `GENDER` — male/female/non-binary → gender-appropriate name pool.
