# avatar_persona_schema

**Type**: data asset | **Testable**: schema validation test

## Purpose
Defines the canonical set of avatar persona attributes: for each attribute, the allowed selector types, the default selector, and the default value used when the attribute is absent from the Avatar Request.

## Location
`assets/persona/persona_schema.yml` (or equivalent settings file)

## Structure per attribute
```yaml
<attribute_name>:
  selector_types: [single, list, range, probability, inherit, llm]
  default_selector: <selector_type>
  default_value: <value_or_selector_spec>
```

## Notes
- Read once at startup by `avatar_persona_generator`.
- Determines which attributes `avatar_request_validate_input` accepts.
- Determines which attributes `avatar_request_identify_missing` considers required.
