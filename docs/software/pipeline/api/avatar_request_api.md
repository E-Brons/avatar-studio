# avatar_request_api

**Parent**: `avatar_request_serve` | **Type**: interface | **Testable**: integration

## Purpose
Entry point for the Avatar Request. Accepts the request from callers (API payload, file path, or in-process dict), normalizes it to a canonical internal dict, and passes it to the validation and processing pipeline.

## Inputs
- One of: JSON/YAML file path, HTTP request body, in-process Python dict

## Outputs
- Normalized Avatar Request dict

## Behavior
1. Accept input in any supported form.
2. Deserialize if needed (file → dict, JSON string → dict).
3. Return normalized dict to `avatar_request_serve`.

## Notes
- Does not validate content — that is `avatar_request_validate_input`'s responsibility.
- Callers: HTTP server (`/api/avatar/generate`), CLI, test harness.
