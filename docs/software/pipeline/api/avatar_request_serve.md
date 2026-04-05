# avatar_request_serve

**Parent**: `avatar_persona_generator` | **Type**: orchestrator | **Testable**: integration (via children)

## Purpose
Processes an Avatar Request end-to-end: validates input, resolves all attributes in dependency order, and marshals the result into the Avatar Persona.

## Inputs
- Avatar Request dict
- Loaded schema (from `avatar_persona_schema`)

## Outputs
- Avatar Persona (serialized)

## Coordinates
1. `avatar_request_api` — normalize and accept the incoming request.
2. `avatar_request_validate_input` — reject unknown attributes or illegal selector types.
3. `avatar_request_identify_missing` — inject schema defaults for absent attributes.
4. `avatar_request_identify_explicits` — pass single-value attributes straight through.
5. `avatar_request_parse_selector` — resolve all remaining selector attributes (random, LLM, inherit).
6. `avatar_persona_marshal` — structure and serialize the aggregate to Avatar Persona.

## Notes
- Resolution order follows §3.1.2: explicits → random → missing → LLM → inherit.
- Inherit attributes must not depend on other inherit attributes (evaluation order undefined).

## Children
- [`avatar_request_api`](avatar_request_api.md)
- [`avatar_request_validate_input`](avatar_request_validate_input.md)
- [`avatar_request_identify_missing`](avatar_request_identify_missing.md)
- [`avatar_request_identify_explicits`](avatar_request_identify_explicits.md)
- [`avatar_request_parse_selector`](avatar_request_parse_selector.md)
- [`avatar_persona_marshal`](avatar_persona_marshal.md)
