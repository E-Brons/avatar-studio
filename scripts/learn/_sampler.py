"""Iterative sampling strategy for learning scripts.

Step 0  — pick X samples (random or by range) from the full example list.
Step N  — keep ALL examples from step N-1 (regression) + add fresh examples to reach
          target_n (doubling schedule: 32 → 64 → 128 → 256 → 512 → 512).

Retaining the full previous set ensures regressions are caught; doubling the sample
each round provides exponentially more coverage until the pool cap is reached.
"""

from __future__ import annotations

import random
from typing import TypeVar

T = TypeVar("T")


def iteration_schedule(initial_n: int, max_n: int, max_iterations: int) -> list[int]:
    """Return per-iteration sample sizes using a doubling schedule capped at *max_n*.

    Example: initial_n=32, max_n=512, max_iterations=6 → [32, 64, 128, 256, 512, 512]
    """
    sizes: list[int] = []
    n = initial_n
    for _ in range(max_iterations):
        sizes.append(min(n, max_n))
        n *= 2
    return sizes


def initial_sample(
    examples: list[T],
    *,
    n: int | None,
    range_: tuple[int, int] | None,
    seed: int | None = None,
) -> list[T]:
    """Return the initial sample for iteration 0.

    Args:
        examples: Full sorted example list.
        n:        Number of random samples (mutually exclusive with range_).
        range_:   (start, end) inclusive index range.
        seed:     Optional RNG seed for reproducibility.

    Returns the full list when both *n* and *range_* are None.
    """
    if range_ is not None:
        start, end = range_
        return examples[start : end + 1]
    if n is not None:
        rng = random.Random(seed)
        return rng.sample(examples, min(n, len(examples)))
    return list(examples)


def next_sample(
    examples: list[T],
    prev_scored: list[tuple[T, float]],
    *,
    target_n: int,
    seed: int | None = None,
) -> list[T]:
    """Build the sample for iteration N (N >= 1).

    Keeps ALL examples from *prev_scored* for regression testing, then adds fresh
    examples until the total reaches *target_n*.

    Args:
        examples:    Full sorted example list (used as the fresh random pool).
        prev_scored: List of (example, score) from the previous iteration.
        target_n:    Desired total sample size for this iteration.
        seed:        Optional RNG seed.

    Returns a shuffled list of all previous examples plus enough fresh ones to reach target_n.
    """
    prev_items: list[T] = [ex for ex, _ in prev_scored]
    prev_set: set[int] = {id(ex) for ex in prev_items}

    fresh_pool: list[T] = [ex for ex in examples if id(ex) not in prev_set]
    add_n = max(0, target_n - len(prev_items))

    rng = random.Random(seed)
    fresh = rng.sample(fresh_pool, min(add_n, len(fresh_pool)))

    combined = prev_items + fresh
    rng.shuffle(combined)
    return combined
