# avatar_request_identify_explicits

**Parent**: `avatar_request_serve` | **Type**: pure function | **Testable**: unit

## Purpose
Scans the Avatar Request for attributes carrying a single concrete value (no selector), and routes each directly to `avatar_persona_aggregator_fallthrough` to be written into the aggregate unchanged.

## Inputs
- Avatar Request dict

## Outputs
- Set of (attribute_name, value) pairs written to the aggregate
- Remaining request dict with explicit attributes removed (passed to `avatar_request_parse_selector`)

## Child
- [`avatar_persona_aggregator_fallthrough`](avatar_persona_aggregator_fallthrough.md)
