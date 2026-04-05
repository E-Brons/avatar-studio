"""Persona request pipeline — validate → inject defaults → resolve selectors."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from pipeline.persona.schema import PersonaSchema, get_schema

logger = logging.getLogger(__name__)


def normalize_input(source: dict | Path | str) -> dict:
    """Normalize file path / YAML string / dict → canonical dict."""
    if isinstance(source, dict):
        return source
    path = Path(source)
    with open(path) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"normalize_input: expected dict, got {type(data).__name__}")
    return data


def validate_input(request: dict, schema: PersonaSchema | None = None) -> list[str]:
    """Return a list of validation errors (empty = valid).

    Checks that any explicitly provided selector types are valid for their
    attribute, and that all keys present in the request are recognised.
    """
    if schema is None:
        schema = get_schema()
    errors: list[str] = []
    for key, value in request.items():
        if key not in schema:
            errors.append(f"Unknown attribute: {key!r}")
            continue
        if isinstance(value, dict) and "selector" in value:
            selector = value["selector"]
            valid = schema.valid_selector_types(key)
            if selector not in valid:
                errors.append(
                    f"Attribute {key!r}: selector {selector!r} not in {valid}"
                )
    return errors


def identify_missing(request: dict, schema: PersonaSchema | None = None) -> dict:
    """Return a copy of *request* with schema defaults injected for absent attrs.

    Only attributes present in the schema are injected.  Existing keys are
    left untouched.
    """
    if schema is None:
        schema = get_schema()
    result = dict(request)
    for key in schema.keys():
        if key not in result:
            result[key] = {
                "selector": schema.default_selector(key),
                "value": schema.default_value(key),
            }
    return result


def identify_explicits(request: dict, schema: PersonaSchema | None = None) -> tuple[dict, dict]:
    """Split *request* into (explicits, selectors).

    *explicits* — attributes whose value is a plain (non-selector) value.
    *selectors* — attributes that still need to be resolved via a selector.
    """
    if schema is None:
        schema = get_schema()
    explicits: dict = {}
    selectors: dict = {}
    for key, value in request.items():
        if isinstance(value, dict) and "selector" in value:
            selectors[key] = value
        else:
            explicits[key] = value
    return explicits, selectors


def parse_selectors(
    selectors: dict,
    resolved: dict,
    *,
    schema: PersonaSchema | None = None,
    rng=None,
    gateway_url: str = "http://127.0.0.1:4096",
) -> dict:
    """Resolve all selector entries in *selectors*, returning a flat dict.

    Dispatches each selector to the appropriate aggregator:
      random_from_list / random_from_range / random_from_range_color / random_from_probability
        → pure aggregators (no LLM/IO)
      from_inherited
        → aggregator_inherited.from_inherited
      from_llm
        → aggregator_llm.from_llm
      fallthrough
        → direct passthrough of value
    """
    import random as _random

    from config.config import SETTINGS
    from pipeline.persona.aggregators import (
        fallthrough,
        pool_by_gender,
        random_from_list,
        random_from_probability,
        random_from_range,
        random_from_range_color,
    )

    if schema is None:
        schema = get_schema()
    if rng is None:
        rng = _random.Random()

    result: dict = {}
    gender = resolved.get("gender", "")

    for key, spec in selectors.items():
        selector = spec.get("selector")
        value = spec.get("value")

        try:
            if selector == "fallthrough":
                result[key] = fallthrough(value)

            elif selector == "random_from_list":
                pool = _resolve_pool(value, SETTINGS)
                result[key] = random_from_list(pool, rng)

            elif selector == "random_from_range":
                lo, hi = (value[0], value[1]) if isinstance(value, (list, tuple)) else (25, 70)
                result[key] = random_from_range(lo, hi, rng)

            elif selector == "random_from_range_color":
                source_key = value.get("source") if isinstance(value, dict) else None
                source_value = resolved.get(source_key) or result.get(source_key, "")
                if source_value:
                    parts = source_value.split()
                    min_hex = parts[0]
                    max_hex = parts[1] if len(parts) > 1 else parts[0]
                    result[key] = random_from_range_color(min_hex, max_hex, rng)
                else:
                    logger.warning("parse_selectors: source %r not resolved for %r", source_key, key)

            elif selector == "random_from_probability":
                opts = value.get("options", []) if isinstance(value, dict) else []
                weights = value.get("weights", []) if isinstance(value, dict) else []
                result[key] = random_from_probability(opts, weights, rng)

            elif selector == "from_inherited":
                pool_src = _resolve_pool(value, SETTINGS)
                pool = pool_by_gender(pool_src, gender)
                result[key] = random_from_list(pool, rng)

            elif selector == "from_llm":
                # Deferred — caller should handle via aggregator_llm
                result[key] = None

            else:
                logger.warning("parse_selectors: unknown selector %r for %r", selector, key)
                result[key] = None

        except Exception as exc:
            logger.error("parse_selectors: error resolving %r: %s", key, exc)
            result[key] = None

    return result


def _resolve_pool(value: Any, settings: dict) -> list:
    """Resolve a pool reference — either an inline list or a settings key name."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return settings.get(value, [])
    return []
