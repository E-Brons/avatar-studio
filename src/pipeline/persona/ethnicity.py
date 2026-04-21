"""Ethnicity derivation helpers — loading, selection, and fallback chain.

The derivation chain for a persona:
  1. Pick nationality  (from demographics.yml)
  2. Resolve ethnicity (nationality_map  → regional_defaults → universal)
  3. Pick skin tone    (weighted from ethnicity's skin_tones dict)
  4. Read fitzpatrick  (from skin tone entry)
  5. Pick eye/nose     (weighted from ethnicity's feature-weight dicts)
"""

from __future__ import annotations

import random
from functools import lru_cache
from pathlib import Path

from ruamel.yaml import YAML

_ASSETS_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "assets" / "persona"
_ETHNICITIES_PATH = _ASSETS_ROOT / "ethnicities.yml"
_DEMOGRAPHICS_PATH = _ASSETS_ROOT / "demographics.yml"


# ---------------------------------------------------------------------------
# YAML loading
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def load_ethnicity_config() -> dict:
    """Load ethnicities.yml and return the full config dict.

    Cached — file is read once per process.
    Keys: ``races``, ``ethnicities``, ``nationality_map``, ``regional_defaults``.
    """
    y = YAML()
    y.preserve_quotes = True
    with open(_ETHNICITIES_PATH) as fh:
        raw = y.load(fh)
    # Convert ruamel CommentedMaps → plain dicts recursively
    return _to_plain(raw)


@lru_cache(maxsize=1)
def _load_nationality_groups() -> dict[str, str]:
    """Return ``{nationality_id: regional_group_id}`` from demographics.yml.

    Each non-group entry is assigned to its most-recent group header.
    """
    y = YAML()
    with open(_DEMOGRAPHICS_PATH) as fh:
        raw = y.load(fh)
    result: dict[str, str] = {}
    current_group: str = "universal"
    for entry in raw["nationality"]:
        entry = _to_plain(entry)
        if entry.get("group"):
            current_group = entry["id"]
        else:
            result[entry["id"]] = current_group
    return result


def _to_plain(obj):  # type: ignore[return]
    """Recursively convert ruamel objects to plain Python dicts/lists."""
    if isinstance(obj, dict):
        return {k: _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_plain(v) for v in obj]
    return obj


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def pick_ethnicity_from_nationality(nationality_id: str, rng: random.Random) -> str:
    """Resolve a nationality to a specific ethnicity ID using the three-level fallback.

    Level 1 — ``nationality_map``: direct probability mapping for this nationality.
    Level 2 — ``regional_defaults``: look up the nationality's regional group.
    Level 3 — universal fallback (``regional_defaults["universal"]``).

    Returns an ethnicity ID string, e.g. ``"scandinavian"`` or ``"west_african"``.
    """
    cfg = load_ethnicity_config()
    nat_map: dict[str, dict[str, float]] = cfg["nationality_map"]
    regional_defaults: dict[str, dict[str, float]] = cfg["regional_defaults"]
    ethnicities: dict[str, dict] = cfg["ethnicities"]

    # Level 1: direct nationality mapping
    probs = nat_map.get(nationality_id)
    if probs and _nonempty(probs):
        return _weighted_choice(probs, rng, fallback=ethnicities)

    # Level 2: regional default
    nationality_groups = _load_nationality_groups()
    group_id = nationality_groups.get(nationality_id, "universal")
    probs = regional_defaults.get(group_id)
    if probs and _nonempty(probs):
        return _weighted_choice(probs, rng, fallback=ethnicities)

    # Level 3: universal fallback
    probs = regional_defaults.get("universal", {})
    if probs:
        return _weighted_choice(probs, rng, fallback=ethnicities)

    # Last resort: uniform over all ethnicities
    return rng.choice(list(ethnicities.keys()))


def get_ethnicity(ethnicity_id: str) -> dict:
    """Return the ethnicity config dict for *ethnicity_id*.

    Raises ``KeyError`` if the ethnicity is not found.
    """
    cfg = load_ethnicity_config()
    ethnicities = cfg["ethnicities"]
    if ethnicity_id not in ethnicities:
        raise KeyError(f"Unknown ethnicity: {ethnicity_id!r}")
    return ethnicities[ethnicity_id]


def get_race_for_ethnicity(ethnicity_id: str) -> str:
    """Return the race ID for the given ethnicity (e.g. ``"white"``, ``"black"``).

    Raises ``KeyError`` if ethnicity is not found.
    """
    eth = get_ethnicity(ethnicity_id)
    return eth["race"]


def get_deepface_race_id(ethnicity_id: str) -> str:
    """Return the DeepFace race label for the given ethnicity.

    E.g. ``"scandinavian"`` → ``"white"``,  ``"korean"`` → ``"asian"``.
    Raises ``KeyError`` if ethnicity or race is not found.
    """
    cfg = load_ethnicity_config()
    race_id = get_race_for_ethnicity(ethnicity_id)
    return cfg["races"][race_id]["deepface_race_id"]


def pick_weighted_feature(
    ethnicity_id: str,
    weight_key: str,
    fallback_pool: list[str],
    rng: random.Random,
) -> str:
    """Pick a feature value using the ethnicity's weighted distribution.

    *weight_key* is e.g. ``"eye_shape_weights"`` or ``"nose_shape_weights"``.
    Falls back to uniform random from *fallback_pool* if the ethnicity has no
    weights for this feature.
    """
    eth = get_ethnicity(ethnicity_id)
    weights: dict[str, float] = eth.get(weight_key, {})
    if weights:
        return _weighted_choice(weights, rng)
    return rng.choice(fallback_pool)


def all_ethnicity_ids() -> list[str]:
    """Return a sorted list of all configured ethnicity IDs."""
    return sorted(load_ethnicity_config()["ethnicities"].keys())


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _nonempty(probs: dict[str, float]) -> bool:
    """Return True if there is at least one positive-weight entry."""
    return any(v > 0 for v in probs.values())


def _weighted_choice(
    probs: dict[str, float],
    rng: random.Random,
    fallback: dict | None = None,
) -> str:
    """Weighted random choice over *probs* dict.

    If *fallback* is provided, entries whose keys are absent from *fallback*
    are silently skipped (guards against stale config references).
    """
    if fallback is not None:
        probs = {k: v for k, v in probs.items() if k in fallback and v > 0}
    else:
        probs = {k: v for k, v in probs.items() if v > 0}

    if not probs:
        raise ValueError("No valid entries in probability dict after filtering")

    ids = list(probs.keys())
    weights = list(probs.values())
    return rng.choices(ids, weights=weights, k=1)[0]
