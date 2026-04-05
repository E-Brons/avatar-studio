# avatar_persona_generator

**Type**: orchestrator | **Testable**: integration (via children)

## Purpose
Top-level unit for §3.1. Coordinates loading the persona schema, processing the Avatar Request, and producing a fully resolved Avatar Persona.

## Inputs
- Avatar Request (file path, API payload, or dict)

## Outputs
- Avatar Persona (serialized — see Appendix A.2)

## Coordinates
1. Load `avatar_persona_schema` — establishes the set of valid attributes, selector types, and defaults.
2. Invoke `avatar_request_serve` — processes the request end-to-end and returns the resolved persona.

## Children
- [`avatar_persona_schema`](avatar_persona_schema.md)
- [`avatar_request_serve`](avatar_request_serve.md)
