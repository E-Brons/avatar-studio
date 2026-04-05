# avatar_request_validate_input

**Parent**: `avatar_request_serve` | **Type**: pure function | **Testable**: unit

## Purpose
Validates the Avatar Request against the persona schema. Rejects unknown attribute names and illegal selector types before any resolution begins.

## Inputs
- Avatar Request dict
- Schema (attribute names + allowed selector types)

## Outputs
- Validated request dict (unchanged if valid)
- `ValidationError` on failure

## Behavior
1. For each key in the request: verify it exists in the schema.
2. For each selector value: verify its type is among the schema's `selector_types` for that attribute.
3. For mandatory rendering params (Artistic Style, Expression IDs, Image Size, Background Style, Background Color): verify all are present.
4. Raise `ValidationError` with the list of violations if any check fails.

## Notes
- Mandatory rendering params are checked for presence but not resolved here — resolution happens in subsequent units.
