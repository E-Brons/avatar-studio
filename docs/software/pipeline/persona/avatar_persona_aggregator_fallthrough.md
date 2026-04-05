# avatar_persona_aggregator_fallthrough

**Parent**: `avatar_request_identify_explicits` | **Type**: pure function | **Testable**: unit

## Purpose
Identity function: writes a single concrete attribute value directly into the aggregate without transformation.

## Inputs
- Attribute name
- Concrete value

## Outputs
- Aggregate updated: `aggregate[attribute_name] = value`

## Notes
- No logic — this is a named pass-through to make the data flow explicit in the unit tree.
