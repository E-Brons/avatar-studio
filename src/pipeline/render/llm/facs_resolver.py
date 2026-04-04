"""FACS resolver — handle unilateral AU placeholders."""

from __future__ import annotations

import random
import re


def resolve_unilateral(facs: str, rng: random.Random | None = None) -> str:
    """Replace ``AUNNx`` placeholders with a randomly chosen side (R or L)."""
    if rng is None:
        side = random.choice(["R", "L"])
    else:
        side = rng.choice(["R", "L"])
    return re.sub(r"AU(\d+)x", lambda m: f"AU{m.group(1)}{side}", facs)
