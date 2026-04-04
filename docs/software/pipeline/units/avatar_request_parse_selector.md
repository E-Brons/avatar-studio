# avatar_request_parse_selector

**Parent**: `avatar_request_serve` | **Type**: dispatcher | **Testable**: unit (dispatch logic) + unit (each child)

## Purpose
Dispatches each selector-type attribute to the appropriate aggregator based on selector type, respecting the resolution order: random selectors first, then LLM, then inherit.

## Inputs
- Avatar Request dict (selector attributes only — explicits already removed)
- Current aggregate (grows as attributes resolve)

## Outputs
- Fully populated aggregate (all selector attributes resolved)

## Behavior
1. Resolve all **random** selectors (list, range, probability) — order within group is arbitrary.
2. Resolve all **LLM** selectors — receive current aggregate as context.
3. Resolve all **inherit** selectors — read from the now-complete aggregate.

## Notes
- Inherit attributes must not depend on other inherit attributes.

## Children
- [`avatar_persona_aggregator_random_from_list`](avatar_persona_aggregator_random_from_list.md)
- [`avatar_persona_aggregator_random_from_range`](avatar_persona_aggregator_random_from_range.md)
- [`avatar_persona_aggregator_random_from_probability`](avatar_persona_aggregator_random_from_probability.md)
- [`avatar_persona_aggregator_from_llm`](avatar_persona_aggregator_from_llm.md)
- [`avatar_persona_aggregator_from_inherited`](avatar_persona_aggregator_from_inherited.md)
