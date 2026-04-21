"""Persona generator — demographics randomisation + avatar character builder."""

from __future__ import annotations

import logging
import random
import tempfile
from pathlib import Path

import yaml

from config.config import (
    _FRAME_FG_COLOR,
    SETTINGS,
    VALID_BG_PALETTE,
    _darken_hex,
)
from pipeline.persona.aggregators import pool_by_gender
from pipeline.persona.ethnicity import (
    pick_ethnicity_from_nationality,
    pick_weighted_feature,
)
from pipeline.persona.skin_tones import load_skin_tones, pick_skin_tone, tones_by_fitzpatrick

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# pool constants
# ---------------------------------------------------------------------------

_GENDERS: list[str] = SETTINGS["genders"]
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

_DEMOGRAPHICS_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent / "assets" / "persona" / "demographics.yml"
)


def _load_nationalities() -> list[str]:
    with open(_DEMOGRAPHICS_PATH) as fh:
        data = yaml.safe_load(fh)
    return [e["id"] for e in data["nationality"] if not e.get("group")]


_NATIONALITIES: list[str] = _load_nationalities()
_FITZPATRICK_TYPES: list[str] = ["I", "II", "III", "IV", "V", "VI"]


# ---------------------------------------------------------------------------
# private helpers
# ---------------------------------------------------------------------------


def _pick_name(gender: str, rng: random.Random, *, hard_type: bool = False) -> str:
    """Pick a random full name appropriate for *gender*."""
    pool = pool_by_gender(_FIRST_NAMES, gender, hard_type=hard_type)
    first = rng.choice(pool)
    return f"{first} {rng.choice(_LAST_NAMES)}"


def _pick_phenotype(ethnicity_id: str, rng: random.Random) -> dict:
    """Return skin tone and facial feature fields derived from *ethnicity_id*.

    Returns a dict with:
    - ``SKIN_TONE`` — hex colour string from skin_tones.yml
    - ``SKIN_TONE_ID`` — composite ID (``tone-name/undertone-name``)
    - ``FITZPATRICK_TYPE`` — Fitzpatrick scale type (I–VI) from skin tone entry
    - ``EYE_SHAPE``, ``NOSE_SHAPE`` — weighted from ethnicity distributions
    """
    from pipeline.persona.ethnicity import get_ethnicity

    eth = get_ethnicity(ethnicity_id)
    skin_entry = pick_skin_tone(eth["skin_tones"], rng)

    eye_shape = pick_weighted_feature(ethnicity_id, "eye_shape_weights", _EYE_SHAPES, rng)
    nose_shape = pick_weighted_feature(ethnicity_id, "nose_shape_weights", _NOSE_SHAPES, rng)

    return {
        "SKIN_TONE": skin_entry["tone"],
        "SKIN_TONE_ID": f"{skin_entry['tone-name']}/{skin_entry['undertone-name']}",
        "FITZPATRICK_TYPE": skin_entry["fitzpatrick-scale"],
        "EYE_SHAPE": eye_shape,
        "NOSE_SHAPE": nose_shape,
    }


def _pick_colors(
    rng: random.Random | None = None,
    *,
    ethnicity_id: str | None = None,
) -> dict:
    """Return randomly selected color and phenotype features.

    If *ethnicity_id* is provided, skin tone + eye/nose shapes are drawn from
    the ethnicity's weighted distributions.  Otherwise a random skin tone is
    picked uniformly across all 120 tones.
    """
    if rng is None:
        rng = random.Random()

    hair_color = rng.choice(_HAIR_COLORS)
    eye_color = rng.choice(_EYE_COLORS)
    hair_base_hex = hair_color.split()[0]
    brows_color = _darken_hex(hair_base_hex, factor=0.7)

    if ethnicity_id is not None:
        pheno = _pick_phenotype(ethnicity_id, rng)
    else:
        all_tones = load_skin_tones()
        tone_entry = rng.choice(list(all_tones.values()))
        pheno = {
            "SKIN_TONE": tone_entry["tone"],
            "SKIN_TONE_ID": f"{tone_entry['tone-name']}/{tone_entry['undertone-name']}",
            "FITZPATRICK_TYPE": tone_entry["fitzpatrick-scale"],
            "EYE_SHAPE": rng.choice(_EYE_SHAPES),
            "NOSE_SHAPE": rng.choice(_NOSE_SHAPES),
        }

    return {
        "SKIN_TONE": pheno["SKIN_TONE"],
        "SKIN_TONE_ID": pheno["SKIN_TONE_ID"],
        "FITZPATRICK_TYPE": pheno["FITZPATRICK_TYPE"],
        "HAIR_COLOR": hair_color,
        "EYE_COLOR": eye_color,
        "BROWS_COLOR": brows_color,
        "EYE_SHAPE": pheno["EYE_SHAPE"],
        "NOSE_SHAPE": pheno["NOSE_SHAPE"],
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

    Returns DEMO fields (gender, age, name, nationality, ethnicity),
    STYLE fields (style, bg_color, fg_color), and PHENO color fields
    (SKIN_TONE, SKIN_TONE_ID, FITZPATRICK_TYPE, HAIR_COLOR, EYE_COLOR,
    BROWS_COLOR, EYE_SHAPE, NOSE_SHAPE) — generated from random selection,
    no LLM needed for visual identity basics.
    """
    rng = random.Random(seed) if seed is not None else random.Random()
    logger.info("START — randomise_person (seed=%s)", seed)
    # Weight non-binary at 10 % — male/female each get 45 %.
    gender = rng.choices(_GENDERS, weights=[45, 45, 10], k=1)[0]

    nationality = rng.choice(_NATIONALITIES)
    ethnicity_id = pick_ethnicity_from_nationality(nationality, rng)

    demo = {
        "gender": gender,
        "age": rng.randint(25, 70),
        "name": _pick_name(gender, rng, hard_type=hard_type_gender),
        "nationality": nationality,
        "ethnicity": ethnicity_id,
        "style": style,
        "bg_color": rng.choice(VALID_BG_PALETTE),
        "fg_color": _FRAME_FG_COLOR,
    }
    demo.update(_pick_colors(rng, ethnicity_id=ethnicity_id))
    demo.update(
        {
            "BROWS_STYLE": rng.choice(
                pool_by_gender(_BROWS_STYLES, gender, hard_type=hard_type_gender)
            ),
            "CHIN_SHAPE": rng.choice(
                pool_by_gender(_CHIN_SHAPES, gender, hard_type=hard_type_gender)
            ),
            "CHEEKS_SHAPE": rng.choice(
                pool_by_gender(_CHEEKS_SHAPES, gender, hard_type=hard_type_gender)
            ),
        }
    )
    logger.info(
        "DONE  — gender=%s, age=%s, nationality=%s, ethnicity=%s, fitzpatrick=%s",
        demo.get("gender"),
        demo.get("age"),
        demo.get("nationality"),
        demo.get("ethnicity"),
        demo.get("FITZPATRICK_TYPE"),
    )
    return demo


def _pick_diverse_demographics(count: int = 4) -> list[dict]:
    """Pick *count* demographics dicts with embedded diversity guarantees.

    Constraints (for count=4):
    - At least one of each gender (male, female, non-binary); 4th is random.
    - At least 3 different age groups from (25-35, 36-45, 46-55, 56+).
    - Skin tones span distinct Fitzpatrick types (sampled without replacement
      from the 6 types, then one skin tone is picked per type).
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

    # Guarantee diverse Fitzpatrick types — shuffle the 6 types, pick one per persona
    fitz_types = list(_FITZPATRICK_TYPES)
    rng.shuffle(fitz_types)
    fitz_types = (fitz_types * ((count // 6) + 1))[:count]

    results = []
    for i in range(count):
        fitz = fitz_types[i]
        tones_for_fitz = tones_by_fitzpatrick(fitz)
        tone_entry = rng.choice(list(tones_for_fitz.values()))
        hair_color = rng.choice(_HAIR_COLORS)
        hair_base_hex = hair_color.split()[0]

        nationality = rng.choice(_NATIONALITIES)
        ethnicity_id = pick_ethnicity_from_nationality(nationality, rng)

        demo = {
            "gender": genders[i],
            "age": ages[i],
            "name": _pick_name(genders[i], rng),
            "nationality": nationality,
            "ethnicity": ethnicity_id,
            "style": _DEFAULT_STYLE,
            "bg_color": rng.choice(VALID_BG_PALETTE),
            "fg_color": _FRAME_FG_COLOR,
            "SKIN_TONE": tone_entry["tone"],
            "SKIN_TONE_ID": f"{tone_entry['tone-name']}/{tone_entry['undertone-name']}",
            "FITZPATRICK_TYPE": tone_entry["fitzpatrick-scale"],
            "HAIR_COLOR": hair_color,
            "EYE_COLOR": rng.choice(_EYE_COLORS),
            "BROWS_COLOR": _darken_hex(hair_base_hex, factor=0.7),
            "EYE_SHAPE": pick_weighted_feature(ethnicity_id, "eye_shape_weights", _EYE_SHAPES, rng),
            "NOSE_SHAPE": pick_weighted_feature(
                ethnicity_id, "nose_shape_weights", _NOSE_SHAPES, rng
            ),
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
        "nationality",
        "ethnicity",
        "style",
        "bg_color",
        "fg_color",
        "SKIN_TONE",
        "SKIN_TONE_ID",
        "FITZPATRICK_TYPE",
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
