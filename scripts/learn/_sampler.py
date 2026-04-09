"""Iterative sampling strategy for learning scripts.

Step 0  — pick X samples (random or by range) from the full example list.
Step N  — keep ALL examples from step N-1 (regression) + add up to X/2 fresh examples
          not seen in the previous iteration.

Retaining the full previous set ensures regressions are caught; injecting up to X/2
novelty each round keeps improving coverage. The sample size grows by up to X/2 per
step, so later iterations are progressively more robust.
"""

from __future__ import annotations

import random
from typing import TypeVar

T = TypeVar("T")


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

    Keeps ALL examples from *prev_scored* for regression testing, then adds up to
    ``target_n // 2`` fresh examples not already present in the previous iteration.

    Args:
        examples:    Full sorted example list (used as the fresh random pool).
        prev_scored: List of (example, score) from the previous iteration.
        target_n:    Initial sample size X — determines how many new examples to add (X/2).
        seed:        Optional RNG seed.

    Returns a shuffled list of all previous examples plus up to target_n // 2 fresh ones.
    """
    prev_items: list[T] = [ex for ex, _ in prev_scored]
    prev_set: set[int] = {id(ex) for ex in prev_items}

    fresh_pool: list[T] = [ex for ex in examples if id(ex) not in prev_set]
    add_n = max(1, target_n // 2)

    rng = random.Random(seed)
    fresh = rng.sample(fresh_pool, min(add_n, len(fresh_pool)))

    combined = prev_items + fresh
    rng.shuffle(combined)
    return combined
