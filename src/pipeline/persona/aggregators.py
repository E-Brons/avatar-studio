"""Pure aggregator functions — no LLM, no I/O, deterministic given a seeded RNG.

Each function accepts a ``random.Random`` instance so all callers can be seeded
for reproducibility and tested with fixed expectations.
"""

from __future__ import annotations

import random


def fallthrough(value):
    """Return *value* unchanged — used when the attribute is pre-seeded."""
    return value


def random_from_list(pool: list, rng: random.Random) -> object:
    """Uniform random choice from *pool*."""
    if not pool:
        raise ValueError("random_from_list: pool is empty")
    return rng.choice(pool)


def random_from_range(lo: int, hi: int, rng: random.Random) -> int:
    """Uniform random integer in [lo, hi] (inclusive)."""
    return rng.randint(lo, hi)


def random_from_range_color(source_value: str, factor: float, darken_fn) -> str:
    """Derive a color from *source_value* by calling *darken_fn(hex, factor)*.

    *source_value* may be a single hex (``"#3B2314"``) or a space-separated
    pair (``"#3B2314 #261508"``).  Only the first hex is used as the base.
    """
    base_hex = source_value.split()[0]
    return darken_fn(base_hex, factor=factor)


def random_from_probability(options: list, weights: list[float], rng: random.Random) -> object:
    """Weighted random choice.

    *options* and *weights* must be the same length.  Weights are normalized
    internally so they need not sum to 1.
    """
    if len(options) != len(weights):
        raise ValueError("random_from_probability: options and weights must be the same length")
    return rng.choices(options, weights=weights, k=1)[0]


def pool_by_gender(option_dict: dict | list, gender: str, *, hard_type: bool = False) -> list:
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
