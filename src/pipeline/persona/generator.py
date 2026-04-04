"""Persona generator — top-level orchestrator for the persona pipeline.

Replaces the pick_demographics → generate_advisor_profile → select_features
→ build_avatar_charachter chain with a single function.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def generate_persona(
    request: dict | Path | None = None,
    *,
    gateway_url: str = "http://127.0.0.1:4096",
    seed: int | None = None,
    hard_type_gender: bool = False,
    session_dir: Path | None = None,
) -> dict:
    """Generate a complete avatar persona from an optional request dict.

    Steps performed internally:
      A — pick demographics (gender, age, colors, phenotype)
      B — generate advisor profile (LLM) if not provided in request
      C — select presentation features (LLM) per field

    Returns the ``avatar_persona`` dict (same structure as ``_marshal_avatar_persona``).
    """
    from config.config import SETTINGS
    from pipeline.step_a_randomise_person import pick_demographics
    from pipeline.step_b_generate_cv import generate_advisor_profile
    from pipeline.step_c_select_features import build_avatar_charachter, select_features

    # Normalize request
    req: dict = {}
    if request is not None:
        from pipeline.persona.request import normalize_input
        req = normalize_input(request)

    # Step A — demographics
    style = req.get("style", SETTINGS.get("default_style", "random"))
    demographics = pick_demographics(seed, style, hard_type_gender=hard_type_gender)

    # Override any explicitly provided demographics fields
    for key in ("gender", "age", "style", "bg_color", "fg_color",
                "SKIN_TONE", "HAIR_COLOR", "EYE_COLOR", "BROWS_COLOR",
                "EYE_SHAPE", "BROWS_STYLE", "NOSE_SHAPE", "CHIN_SHAPE", "CHEEKS_SHAPE"):
        if key in req:
            demographics[key] = req[key]

    # Build advisor dict from request or defaults
    advisor: dict = {
        "role": req.get("role", "Professional Advisor"),
        "traits": req.get("traits", []),
        "education": req.get("education", []),
        "experience": req.get("experience", []),
    }

    # Step B — advisor profile (skip if all fields already provided)
    if not all(advisor.get(k) for k in ("traits", "education", "experience")):
        try:
            profile = generate_advisor_profile(
                advisor["role"],
                {"gender": demographics["gender"], "age": demographics["age"]},
                gateway_url=gateway_url,
            )
            advisor.update(profile)
        except Exception as exc:
            logger.warning("[generate_persona] Step B failed: %s", exc)
            advisor.setdefault("traits", [])
            advisor.setdefault("education", [])
            advisor.setdefault("experience", [])

    # Step C — feature selection
    features = None
    _tmp_ctx = None
    if session_dir is None:
        _tmp_ctx = tempfile.TemporaryDirectory(prefix="avatar_persona_")
        _session = Path(_tmp_ctx.__enter__())
    else:
        _session = session_dir

    try:
        features = select_features(
            demographics,
            advisor,
            gateway_url=gateway_url,
            session_dir=_session,
            hard_type_gender=hard_type_gender,
        )
    except Exception as exc:
        logger.warning("[generate_persona] Step C failed: %s", exc)
    finally:
        if _tmp_ctx is not None:
            _tmp_ctx.__exit__(None, None, None)

    avatar = build_avatar_charachter(advisor, demographics, features)
    return avatar
