"""Skin tone helpers — loading, ID construction, Fitzpatrick grouping, weighted selection.

Skin tones are loaded from assets/persona/skin_tones.yml (120 entries).
Each entry is identified by a composite ID: "tone-name/undertone-name".
"""

from __future__ import annotations

import random
from functools import lru_cache
from pathlib import Path

from ruamel.yaml import YAML

_ASSETS_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "assets" / "persona"
_SKIN_TONES_PATH = _ASSETS_ROOT / "skin_tones.yml"

_REQUIRED_FIELDS = frozenset(
    [
        "fitzpatrick-scale",
        "monk-scale",
        "tone-name",
        "undertone-name",
        "tone",
        "undertone",
        "surface",
        "shadow",
        "lip",
        "shine",
    ]
)


def skin_tone_id(entry: dict) -> str:
    """Return the composite ID ``'tone-name/undertone-name'`` from a skin tone entry."""
    return f"{entry['tone-name']}/{entry['undertone-name']}"


@lru_cache(maxsize=1)
def load_skin_tones() -> dict[str, dict]:
    """Load skin_tones.yml and return a dict keyed by ``'tone-name/undertone-name'``.

    The file is read once and cached for the lifetime of the process.
    """
    y = YAML()
    y.preserve_quotes = True
    with open(_SKIN_TONES_PATH) as fh:
        raw = y.load(fh)

    entries = raw["skin_tones"]
    result: dict[str, dict] = {}
    for entry in entries:
        tid = skin_tone_id(entry)
        result[tid] = dict(entry)  # convert ruamel CommentedMap → plain dict

    return result


def tones_by_fitzpatrick(fitz: str) -> dict[str, dict]:
    """Return all skin tones whose ``fitzpatrick-scale`` equals *fitz* (e.g. ``"III"``).

    Returns a sub-dict keyed by the same composite ID format.
    """
    all_tones = load_skin_tones()
    return {tid: entry for tid, entry in all_tones.items() if entry["fitzpatrick-scale"] == fitz}


def pick_skin_tone(skin_probs: dict[str, float], rng: random.Random) -> dict:
    """Weighted random selection from a ``{skin_id: probability}`` mapping.

    *skin_probs* maps composite skin IDs (``"tone-name/undertone-name"``) to their
    relative probabilities (need not sum to 1.0 — they are normalised internally).

    Returns the full skin tone entry dict from ``skin_tones.yml``.
    Raises ``KeyError`` if any referenced skin ID is not in ``skin_tones.yml``.
    Raises ``ValueError`` if *skin_probs* is empty.
    """
    if not skin_probs:
        raise ValueError("skin_probs must not be empty")

    all_tones = load_skin_tones()
    ids = list(skin_probs.keys())
    weights = [skin_probs[i] for i in ids]

    chosen_id = rng.choices(ids, weights=weights, k=1)[0]
    return all_tones[chosen_id]
