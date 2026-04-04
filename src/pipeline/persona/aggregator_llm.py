"""LLM-based aggregator — wraps _select_feature_field from step_c."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def from_llm(
    attr: str,
    options: list | None,
    resolved: dict,
    *,
    gateway_url: str = "http://127.0.0.1:4096",
) -> str | dict | None:
    """Select a single feature attribute via LLM.

    Delegates to ``step_c_select_features._select_feature_field``.
    Returns None on failure (caller should fall back or skip).
    """
    from pipeline.step_c_select_features import (
        _STEP_C_SYSTEM_PROMPT,
        _format_profile,
        _select_feature_field,
    )

    demographics = {k: resolved[k] for k in ("gender", "age") if k in resolved}
    advisor = {
        "role": resolved.get("role", "Professional Advisor"),
        "traits": resolved.get("traits", []),
    }
    profile = _format_profile(demographics, advisor)

    try:
        return _select_feature_field(
            attr,
            profile,
            _STEP_C_SYSTEM_PROMPT,
            options,
            resolved,
            demographics,
            advisor,
            gateway_url=gateway_url,
        )
    except Exception as exc:
        logger.warning("aggregator_llm.from_llm: %r failed: %s", attr, exc)
        return None
