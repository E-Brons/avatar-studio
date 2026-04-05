# avatar_persona_default_fallback

**Parent**: `avatar_request_identify_missing` | **Type**: pure lookup | **Testable**: unit

## Purpose
Returns the schema-defined default selector (or default value) for a given attribute that was absent from the Avatar Request.

## Inputs
- Attribute name
- Schema

## Outputs
- Default selector spec for the attribute (may be a single value, list selector, range spec, etc.)

## Behavior
1. Look up `schema[attribute].default_selector` and `schema[attribute].default_value`.
2. Return the default selector spec to `avatar_request_identify_missing` for injection.

## Notes
- Purely a schema lookup — no side effects.
