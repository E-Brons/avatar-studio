"""Inherited aggregator — gender-bucketed pool selection.

Extracts the _pool_by_gender pattern from step_a into a standalone function
so it can be used from request.py and tested independently.
"""

from __future__ import annotations

import random

from pipeline.persona.aggregators import pool_by_gender, random_from_list


def from_inherited(
    attr: str,
    pool_source: dict | list,
    resolved: dict,
    rng: random.Random,
    *,
    hard_type: bool = False,
) -> object:
    """Select an attribute from a gender-bucketed pool.

    *pool_source* is either a plain list (used as-is) or a nested dict with
    ``male`` / ``female`` / ``neutral`` buckets.  The gender is taken from
    ``resolved["gender"]``.
    """
    gender = resolved.get("gender", "")
    pool = pool_by_gender(pool_source, gender, hard_type=hard_type)
    return random_from_list(pool, rng)
