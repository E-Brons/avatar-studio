"""Stage A — randomize person: demographics, name, colors."""

import logging
import random

from avatar_studio.config.config import (
    _FRAME_FG_COLOR,
    SETTINGS,
    VALID_BG_PALETTE,
    _darken_hex,
)

_GENDERS: list[str] = SETTINGS["genders"]

# Flat skin-tone palette — all values available uniformly regardless of other traits.
_SKIN_TONES: list[str] = SETTINGS["skin_tones"]

# Hair colors — "#BASE #SHADOW" pairs; all available uniformly.
_HAIR_COLORS: list[str] = SETTINGS["hair_colors"]

# Eye colors — "#IRIS #PUPIL" pairs; all available uniformly.
_EYE_COLORS: list[str] = SETTINGS["eye_colors"]

# Phenotype shape fields — all picked uniformly at random in Step A (no LLM).
_EYE_SHAPES: list[str] = SETTINGS["eye_shapes"]
_BROWS_STYLES: dict = SETTINGS["brows_styles"]
_NOSE_SHAPES: list[str] = SETTINGS["nose_shapes"]
_CHIN_SHAPES: dict = SETTINGS["chin_shapes"]
_CHEEKS_SHAPES: dict = SETTINGS["cheeks_shapes"]

# Name pools — nested by gender bucket.
_FIRST_NAMES: dict = SETTINGS["first_names"]
_LAST_NAMES: list[str] = SETTINGS["last_names"]


def _pool_by_gender(option_dict: dict | list, gender: str, *, hard_type: bool = False) -> list:
    """Return a flattened option list appropriate for *gender*.

    Default (hard_type=False):
      male       → male + neutral
      female     → female + neutral
      non-binary → male + female + neutral

    Hard-typed (hard_type=True) — strict single-bucket selection:
      male       → male only
      female     → female only
      non-binary → neutral only
    """
    if isinstance(option_dict, list):
        return option_dict
    if hard_type:
        if gender == "male":
            buckets = ["male"]
        elif gender == "female":
            buckets = ["female"]
        else:
            buckets = ["neutral"]
    else:
        if gender == "male":
            buckets = ["male", "neutral"]
        elif gender == "female":
            buckets = ["female", "neutral"]
        else:
            buckets = ["male", "female", "neutral"]
    result: list = []
    for b in buckets:
        result.extend(option_dict.get(b, []))
    return result


_AGE_GROUPS: list[tuple[int, int]] = [tuple(pair) for pair in SETTINGS["age_groups"].values()]

_DEFAULT_STYLE: str = SETTINGS["default_style"]

logger = logging.getLogger(__name__)


def _pick_name(gender: str, rng: random.Random, *, hard_type: bool = False) -> str:
    """Pick a random full name appropriate for *gender*.

    See _pool_by_gender for pool selection rules (respects *hard_type*).
    """
    pool = _pool_by_gender(_FIRST_NAMES, gender, hard_type=hard_type)
    first = rng.choice(pool)
    return f"{first} {rng.choice(_LAST_NAMES)}"


def _pick_colors(rng: random.Random | None = None) -> dict:
    """Return randomly selected color features from appearance-neutral flat lists.

    Returns SKIN_TONE, HAIR_COLOR, EYE_COLOR, BROWS_COLOR — all picked
    uniformly from the full palette with no correlation to any other trait.
    BROWS_COLOR is derived by darkening the HAIR_COLOR base hex.
    """
    if rng is None:
        rng = random.Random()

    skin_tone = rng.choice(_SKIN_TONES)
    hair_color = rng.choice(_HAIR_COLORS)  # "#BASE #SHADOW"
    eye_color = rng.choice(_EYE_COLORS)  # "#IRIS #PUPIL"

    hair_base_hex = hair_color.split()[0]
    brows_color = _darken_hex(hair_base_hex, factor=0.7)

    return {
        "SKIN_TONE": skin_tone,
        "HAIR_COLOR": hair_color,
        "EYE_COLOR": eye_color,
        "BROWS_COLOR": brows_color,
    }

    return {
        "SKIN_TONE": skin_tone,
        "HAIR_COLOR": hair_color,
        "EYE_COLOR": eye_color,
        "BROWS_COLOR": brows_color,
    }


def pick_demographics(
    seed: int | None = None, style: str = _DEFAULT_STYLE, *, hard_type_gender: bool = False
) -> dict:
    """Random demographics, optionally seeded for reproducibility.

    All categories use uniform random selection — no group is weighted above
    another.  If *seed* is provided the result is deterministic; if ``None``,
    fresh random values are used (the "re-generate advisor" flow).

    *hard_type_gender* — when True, gender-bucketed pools are filtered to the
    strict gender bucket only (no neutral crossover).  Default is False.
    See _pool_by_gender for full semantics.

    Returns DEMO fields (gender, age, name), STYLE fields (style, bg_color,
    fg_color), and PHENO color fields (SKIN_TONE, HAIR_COLOR, EYE_COLOR,
    BROWS_COLOR) — all generated in Step A so no LLM is needed for visual
    identity basics.
    """
    rng = random.Random(seed) if seed is not None else random.Random()
    logger.info("[Step A] START — randomise_person (seed=%s)", seed)
    gender = rng.choice(_GENDERS)

    demo = {
        "gender": gender,
        "age": rng.randint(25, 70),
        "name": _pick_name(gender, rng, hard_type=hard_type_gender),
        "style": style,
        "bg_color": rng.choice(VALID_BG_PALETTE),
        "fg_color": _FRAME_FG_COLOR,
    }
    demo.update(_pick_colors(rng))  # adds SKIN_TONE, HAIR_COLOR, EYE_COLOR, BROWS_COLOR
    demo.update(
        {
            "EYE_SHAPE": rng.choice(_EYE_SHAPES),
            "BROWS_STYLE": rng.choice(
                _pool_by_gender(_BROWS_STYLES, gender, hard_type=hard_type_gender)
            ),
            "NOSE_SHAPE": rng.choice(_NOSE_SHAPES),
            "CHIN_SHAPE": rng.choice(
                _pool_by_gender(_CHIN_SHAPES, gender, hard_type=hard_type_gender)
            ),
            "CHEEKS_SHAPE": rng.choice(
                _pool_by_gender(_CHEEKS_SHAPES, gender, hard_type=hard_type_gender)
            ),
        }
    )
    logger.info("[Step A] DONE  — gender=%s, age=%s", demo.get("gender"), demo.get("age"))
    return demo


# Backward-compat alias
_pick_demographics = pick_demographics


def _pick_diverse_demographics(count: int = 4) -> list[dict]:
    """Pick *count* demographics dicts with embedded diversity guarantees.

    Constraints (for count=4):
    - At least one of each gender (male, female, non-binary); 4th is random.
    - At least 3 different age groups from (25-35, 36-45, 46-55, 56+).
    - All skin tones are distinct (sampled without replacement from _SKIN_TONES).

    Each candidate gets a random name (gender-matched), PHENO colors, and
    a random frame color.
    """
    rng = random.Random()

    logger.info("[Step A] START — randomise_person diverse (count=%d)", count)
    # --- Gender: guarantee one of each, 4th is random ---
    genders = list(_GENDERS)  # male, female, non-binary
    rng.shuffle(genders)
    genders.append(rng.choice(_GENDERS))  # 4th random

    # --- Age: pick from at least 3 distinct age groups ---
    age_groups = list(_AGE_GROUPS)
    rng.shuffle(age_groups)
    chosen_groups = age_groups[:count]
    while len(chosen_groups) < count:
        chosen_groups.append(rng.choice(_AGE_GROUPS))
    rng.shuffle(chosen_groups)
    ages = [rng.randint(lo, hi) for lo, hi in chosen_groups]

    # --- Skin tones: all distinct (sample without replacement) ---
    skin_tones = rng.sample(_SKIN_TONES, min(count, len(_SKIN_TONES)))
    while len(skin_tones) < count:
        skin_tones.append(rng.choice(_SKIN_TONES))
    rng.shuffle(skin_tones)

    # --- Assemble ---
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

    logger.info("[Step A] DONE  — diverse demographics count=%d", len(results))
    return results
