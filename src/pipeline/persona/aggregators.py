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


def random_from_range_color(min_hex: str, max_hex: str, rng: random.Random) -> str:
    """Interpolate uniformly between two hex colors in YCbCr space.

    A single ``t ~ Uniform(0, 1)`` is sampled (shared across all channels) so
    the result lies on the straight line between the two endpoints in perceptual
    YCbCr space rather than in the perceptually non-uniform RGB cube.
    """

    def _hex_to_rgb(h: str) -> tuple[int, int, int]:
        h = h.lstrip("#")
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

    def _rgb_to_ycbcr(r: int, g: int, b: int) -> tuple[float, float, float]:
        y  =  0.299 * r + 0.587 * g + 0.114 * b
        cb = -0.168736 * r - 0.331264 * g + 0.5 * b + 128
        cr =  0.5 * r - 0.418688 * g - 0.081312 * b + 128
        return y, cb, cr

    def _ycbcr_to_rgb(y: float, cb: float, cr: float) -> tuple[int, int, int]:
        cb -= 128
        cr -= 128
        r = y + 1.402 * cr
        g = y - 0.344136 * cb - 0.714136 * cr
        b = y + 1.772 * cb
        return (
            max(0, min(255, round(r))),
            max(0, min(255, round(g))),
            max(0, min(255, round(b))),
        )

    t = rng.random()
    y1, cb1, cr1 = _rgb_to_ycbcr(*_hex_to_rgb(min_hex))
    y2, cb2, cr2 = _rgb_to_ycbcr(*_hex_to_rgb(max_hex))
    y  = y1 + t * (y2 - y1)
    cb = cb1 + t * (cb2 - cb1)
    cr = cr1 + t * (cr2 - cr1)
    r, g, b = _ycbcr_to_rgb(y, cb, cr)
    return "#{:02X}{:02X}{:02X}".format(r, g, b)


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
