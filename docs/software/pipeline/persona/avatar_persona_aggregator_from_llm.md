# avatar_persona_aggregator_from_llm

**Parent**: `avatar_request_parse_selector` | **Type**: LLM call | **Testable**: unittest intentionally skipped (low ROI)

## Purpose
Calls a text LLM to select a value for an attribute, given the partially-resolved persona as context and the schema's allowed values as a constraint.

## Inputs
- Attribute name
- Selector spec: `{options: [...], schema: {...}}`
- Current aggregate (attributes resolved so far — steps 1–3 of resolution order)
- Gateway URL

## Outputs
- `aggregate[attribute_name] = LLM-selected value`

## Behavior
1. Build prompt: include attribute name, allowed options, and a YAML dump of the current aggregate.
2. Call `GatewayClient.text_gen()`.
3. Parse response: extract a single value matching one of the allowed options.
4. Retry up to `max_retries` on empty response or out-of-options value.
5. Write to aggregate.

## Notes
- LLM sees all previously resolved attributes — this is the "implicit dependency" described in §3.1.2 step 4.
- Not unit-testable in the traditional sense: LLM output is non-deterministic and mocking it provides no value.
