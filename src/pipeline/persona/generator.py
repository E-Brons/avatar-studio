"""Persona generator — demographics randomisation + avatar character builder."""

from __future__ import annotations

import logging
import random
import tempfile
from pathlib import Path

from config.config import (
    _FRAME_FG_COLOR,
    SETTINGS,
    VALID_BG_PALETTE,
    _darken_hex,
)
from pipeline.persona.aggregators import pool_by_gender

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# pool constants
# ---------------------------------------------------------------------------

_GENDERS: list[str] = SETTINGS["genders"]
_SKIN_TONES: list[str] = SETTINGS["skin_tones"]
_HAIR_COLORS: list[str] = SETTINGS["hair_colors"]
_EYE_COLORS: list[str] = SETTINGS["eye_colors"]
_EYE_SHAPES: list[str] = SETTINGS["eye_shapes"]
_BROWS_STYLES: dict = SETTINGS["brows_styles"]
_NOSE_SHAPES: list[str] = SETTINGS["nose_shapes"]
_CHIN_SHAPES: dict = SETTINGS["chin_shapes"]
_CHEEKS_SHAPES: dict = SETTINGS["cheeks_shapes"]
_FIRST_NAMES: dict = SETTINGS["first_names"]
_LAST_NAMES: list[str] = SETTINGS["last_names"]
_AGE_GROUPS: list[tuple[int, int]] = [tuple(pair) for pair in SETTINGS["age_groups"].values()]
_DEFAULT_STYLE: str = SETTINGS["default_style"]


# ---------------------------------------------------------------------------
# private helpers
# ---------------------------------------------------------------------------


def _pick_name(gender: str, rng: random.Random, *, hard_type: bool = False) -> str:
    """Pick a random full name appropriate for *gender*."""
    pool = pool_by_gender(_FIRST_NAMES, gender, hard_type=hard_type)
    first = rng.choice(pool)
    return f"{first} {rng.choice(_LAST_NAMES)}"


def _pick_colors(rng: random.Random | None = None) -> dict:
    """Return randomly selected color features from appearance-neutral flat lists."""
    if rng is None:
        rng = random.Random()

    skin_tone = rng.choice(_SKIN_TONES)
    hair_color = rng.choice(_HAIR_COLORS)
    eye_color = rng.choice(_EYE_COLORS)

    hair_base_hex = hair_color.split()[0]
    brows_color = _darken_hex(hair_base_hex, factor=0.7)

    return {
        "SKIN_TONE": skin_tone,
        "HAIR_COLOR": hair_color,
        "EYE_COLOR": eye_color,
        "BROWS_COLOR": brows_color,
    }


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


def pick_demographics(
    seed: int | None = None, style: str = _DEFAULT_STYLE, *, hard_type_gender: bool = False
) -> dict:
    """Random demographics, optionally seeded for reproducibility.

    All categories use uniform random selection — no group is weighted above
    another.  If *seed* is provided the result is deterministic; if ``None``,
    fresh random values are used (the "re-generate advisor" flow).

    *hard_type_gender* — when True, gender-bucketed pools are filtered to the
    strict gender bucket only (no neutral crossover).  Default is False.
    See pool_by_gender for full semantics.

    Returns DEMO fields (gender, age, name), STYLE fields (style, bg_color,
    fg_color), and PHENO color fields (SKIN_TONE, HAIR_COLOR, EYE_COLOR,
    BROWS_COLOR) — all generated from random selection, no LLM needed for visual
    identity basics.
    """
    rng = random.Random(seed) if seed is not None else random.Random()
    logger.info("START — randomise_person (seed=%s)", seed)
    # Weight non-binary at 10 % — male/female each get 45 %.
    gender = rng.choices(_GENDERS, weights=[45, 45, 10], k=1)[0]

    demo = {
        "gender": gender,
        "age": rng.randint(25, 70),
        "name": _pick_name(gender, rng, hard_type=hard_type_gender),
        "style": style,
        "bg_color": rng.choice(VALID_BG_PALETTE),
        "fg_color": _FRAME_FG_COLOR,
    }
    demo.update(_pick_colors(rng))
    demo.update(
        {
            "EYE_SHAPE": rng.choice(_EYE_SHAPES),
            "BROWS_STYLE": rng.choice(
                pool_by_gender(_BROWS_STYLES, gender, hard_type=hard_type_gender)
            ),
            "NOSE_SHAPE": rng.choice(_NOSE_SHAPES),
            "CHIN_SHAPE": rng.choice(
                pool_by_gender(_CHIN_SHAPES, gender, hard_type=hard_type_gender)
            ),
            "CHEEKS_SHAPE": rng.choice(
                pool_by_gender(_CHEEKS_SHAPES, gender, hard_type=hard_type_gender)
            ),
        }
    )
    logger.info("DONE  — gender=%s, age=%s", demo.get("gender"), demo.get("age"))
    return demo


def _pick_diverse_demographics(count: int = 4) -> list[dict]:
    """Pick *count* demographics dicts with embedded diversity guarantees.

    Constraints (for count=4):
    - At least one of each gender (male, female, non-binary); 4th is random.
    - At least 3 different age groups from (25-35, 36-45, 46-55, 56+).
    - All skin tones are distinct (sampled without replacement from _SKIN_TONES).
    """
    rng = random.Random()

    logger.info("START — randomise_person diverse (count=%d)", count)
    genders = list(_GENDERS)
    rng.shuffle(genders)
    genders.append(rng.choice(_GENDERS))

    age_groups = list(_AGE_GROUPS)
    rng.shuffle(age_groups)
    chosen_groups = age_groups[:count]
    while len(chosen_groups) < count:
        chosen_groups.append(rng.choice(_AGE_GROUPS))
    rng.shuffle(chosen_groups)
    ages = [rng.randint(lo, hi) for lo, hi in chosen_groups]

    skin_tones = rng.sample(_SKIN_TONES, min(count, len(_SKIN_TONES)))
    while len(skin_tones) < count:
        skin_tones.append(rng.choice(_SKIN_TONES))
    rng.shuffle(skin_tones)

    results = []
    for i in range(count):
        hair_color = rng.choice(_HAIR_COLORS)
        hair_base_hex = hair_color.split()[0]
        demo = {
            "gender": genders[i],
            "age": ages[i],
            "name": _pick_name(genders[i], rng),
            "style": _DEFAULT_STYLE,
            "bg_color": rng.choice(VALID_BG_PALETTE),
            "fg_color": _FRAME_FG_COLOR,
            "SKIN_TONE": skin_tones[i],
            "HAIR_COLOR": hair_color,
            "EYE_COLOR": rng.choice(_EYE_COLORS),
            "BROWS_COLOR": _darken_hex(hair_base_hex, factor=0.7),
        }
        results.append(demo)

    logger.info("DONE  — diverse demographics count=%d", len(results))
    return results


# ---------------------------------------------------------------------------
# avatar character builder
# ---------------------------------------------------------------------------


def build_avatar_charachter(
    advisor: dict,
    demographics: dict,
    features: dict | None = None,
) -> dict:
    """Build a complete avatar character definition."""
    from pipeline.persona.marshal import marshal_avatar_persona

    traits = advisor.get("traits", [])
    traits_str = ", ".join(traits) if traits else "professional"

    avatar_persona = marshal_avatar_persona(demographics, advisor, features)

    return dict(
        gender=demographics["gender"],
        age=demographics["age"],
        traits_str=traits_str,
        avatar_persona=avatar_persona,
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


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

    Returns the ``avatar_persona`` dict (same structure as ``marshal_avatar_persona``).
    """
    from config.config import SETTINGS
    from pipeline.persona.aggregator_llm import select_features

    # Normalize request
    req: dict = {}
    if request is not None:
        from pipeline.persona.request import normalize_input

        req = normalize_input(request)

    # demographics
    style = req.get("style", SETTINGS.get("default_style", "random"))
    demographics = pick_demographics(seed, style, hard_type_gender=hard_type_gender)

    # Override any explicitly provided demographics fields
    for key in (
        "gender",
        "age",
        "style",
        "bg_color",
        "fg_color",
        "SKIN_TONE",
        "HAIR_COLOR",
        "EYE_COLOR",
        "BROWS_COLOR",
        "EYE_SHAPE",
        "BROWS_STYLE",
        "NOSE_SHAPE",
        "CHIN_SHAPE",
        "CHEEKS_SHAPE",
    ):
        if key in req:
            demographics[key] = req[key]

    # Build personality dict from request or defaults
    advisor: dict = {
        "traits": req.get("traits", []),
    }

    # feature selection
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
        logger.warning("[generate_persona] feature selection failed: %s", exc)
    finally:
        if _tmp_ctx is not None:
            _tmp_ctx.__exit__(None, None, None)

    avatar = build_avatar_charachter(advisor, demographics, features)
    return avatar
