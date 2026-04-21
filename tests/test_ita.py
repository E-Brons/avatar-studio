"""Tests for ITA (Individual Typology Angle) computation and Fitzpatrick mapping.

ITA = arctan((L* - 50) / b*) × (180/π)

Chardon thresholds:
  > 55°  → I
  41–55° → II
  28–41° → III
  10–28° → IV
  -30–10°→ V
  < -30° → VI
"""

from __future__ import annotations

import math

import pytest

from pipeline.persona.skin_tones import load_skin_tones
from tuning.validate_diversity import compute_ita, ita_to_fitzpatrick

# ---------------------------------------------------------------------------
# Helpers — inline minimal ITA implementation for test reference values
# ---------------------------------------------------------------------------


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _linearize(c: float) -> float:
    c /= 255.0
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def _rgb_to_lab(r: int, g: int, b_int: int) -> tuple[float, float, float]:
    rl, gl, bl = _linearize(r), _linearize(g), _linearize(b_int)
    y = (rl * 0.2126 + gl * 0.7152 + bl * 0.0722) / 1.00000
    z = (rl * 0.0193 + gl * 0.1192 + bl * 0.9505) / 1.08883

    def f(t: float) -> float:
        if t > 0.008856:
            return t ** (1.0 / 3.0)
        return 7.787 * t + 16.0 / 116.0

    fy, fz = f(y), f(z)
    L = 116.0 * fy - 16.0
    b_val = 200.0 * (fy - fz)
    return L, 0.0, b_val  # we only need L* and b* for ITA


def _ita(hex_color: str) -> float:
    r, g, b = _hex_to_rgb(hex_color)
    L, _, b_val = _rgb_to_lab(r, g, b)
    if abs(b_val) < 1e-9:
        return 90.0 if L > 50 else 0.0
    return math.degrees(math.atan((L - 50.0) / b_val))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestComputeIta:
    def test_callable(self):
        assert callable(compute_ita)

    def test_white_skin_positive_ita(self):
        # Very pale skin — Fitzpatrick I territory
        ita = compute_ita("#F9E4E1")
        assert ita > 40, f"Expected ITA > 40 for pale skin, got {ita:.1f}"

    def test_dark_skin_negative_ita(self):
        # Very dark skin — Fitzpatrick VI territory
        ita = compute_ita("#3C1E0C")
        assert ita < -20, f"Expected ITA < -20 for dark skin, got {ita:.1f}"

    def test_matches_reference_implementation(self):
        """compute_ita must agree with the reference inline implementation."""
        test_colors = [
            "#F9E4E1",  # MST-01 porcelain
            "#C8A06A",  # MST-05 warm sand
            "#8C5C34",  # MST-07 mocha
            "#3C1E0C",  # MST-10 obsidian
        ]
        for hex_color in test_colors:
            result = compute_ita(hex_color)
            expected = _ita(hex_color)
            assert abs(result - expected) < 0.5, (
                f"ITA mismatch for {hex_color}: got {result:.2f}, expected {expected:.2f}"
            )

    def test_invalid_hex_raises(self):
        with pytest.raises((ValueError, AttributeError)):
            compute_ita("not_a_color")


class TestItaToFitzpatrick:
    def test_callable(self):
        assert callable(ita_to_fitzpatrick)

    def test_type_i_threshold(self):
        assert ita_to_fitzpatrick(60.0) == "I"
        assert ita_to_fitzpatrick(55.1) == "I"

    def test_type_ii_threshold(self):
        # Chardon: > 55° → I, 41° < ITA ≤ 55° → II
        assert ita_to_fitzpatrick(55.0) == "II"
        assert ita_to_fitzpatrick(41.1) == "II"

    def test_type_iii_threshold(self):
        # Chardon: 28° < ITA ≤ 41° → III
        assert ita_to_fitzpatrick(41.0) == "III"
        assert ita_to_fitzpatrick(28.1) == "III"

    def test_type_iv_threshold(self):
        # Chardon: 10° < ITA ≤ 28° → IV
        assert ita_to_fitzpatrick(28.0) == "IV"
        assert ita_to_fitzpatrick(10.1) == "IV"

    def test_type_v_threshold(self):
        # Chardon: -30° < ITA ≤ 10° → V
        assert ita_to_fitzpatrick(10.0) == "V"
        assert ita_to_fitzpatrick(-29.9) == "V"

    def test_type_vi_threshold(self):
        # Chardon: ITA ≤ -30° → VI
        assert ita_to_fitzpatrick(-30.0) == "VI"
        assert ita_to_fitzpatrick(-60.0) == "VI"


class TestSkinToneITAMatchFitzpatrick:
    """Every skin tone in skin_tones.yml must ITA-map to its declared Fitzpatrick type
    within ±2 types (ITA is a photometric measure; it doesn't perfectly reproduce the
    Fitzpatrick clinical classification, especially for cool-undertone light variants
    whose hex values sit in visually lighter ranges)."""

    _FITZ_ORDER = ["I", "II", "III", "IV", "V", "VI"]

    def _close_enough(self, declared: str, observed: str, tolerance: int = 2) -> bool:
        if declared == observed:
            return True
        d_idx = self._FITZ_ORDER.index(declared)
        o_idx = self._FITZ_ORDER.index(observed)
        return abs(d_idx - o_idx) <= tolerance

    def test_all_tones_ita_close_to_declared_fitzpatrick(self):
        tones = load_skin_tones()
        failures = []
        for tid, entry in tones.items():
            ita = compute_ita(entry["tone"])
            observed = ita_to_fitzpatrick(ita)
            declared = entry["fitzpatrick-scale"]
            if not self._close_enough(declared, observed):
                failures.append(f"{tid}: declared={declared}, observed={observed} (ITA={ita:.1f})")

        assert not failures, (
            f"{len(failures)} skin tones have ITA→Fitzpatrick mismatch (>±2 types):\n"
            + "\n".join(failures)
        )
