# avatar_request_identify_missing

**Parent**: `avatar_request_serve` | **Type**: pure function | **Testable**: unit

## Purpose
Identifies attributes defined in the schema that are absent from the Avatar Request, then injects the schema default selector for each so they can proceed through normal resolution.

## Inputs
- Avatar Request dict (post-validation)
- Schema (full attribute list + default selectors)

## Outputs
- Augmented Avatar Request dict with default selectors injected for missing attributes

## Behavior
1. Compute the set of schema attributes not present in the request.
2. For each missing attribute: call `avatar_persona_default_fallback` to retrieve the default selector.
3. Inject the returned selector into the request dict under the missing attribute's key.

## Child
- [`avatar_persona_default_fallback`](avatar_persona_default_fallback.md)
