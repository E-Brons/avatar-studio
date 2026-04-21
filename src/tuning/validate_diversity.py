"""DeepFace-based diversity validator for generated avatar images.

Compares a generated image against the persona.yml expected attributes:
- Age (±tolerance)
- Gender
- Race (via DeepFace dominant_race, mapped through ethnicity → race → deepface_race_id)
- Fitzpatrick type (computed from face skin via ITA, ±1 Fitzpatrick type tolerance)

Usage
-----
    from tuning.validate_diversity import validate_avatar_diversity

    report = validate_avatar_diversity(image_bytes, persona)
    print(f"score={report.score:.0%}")
    for mismatch in report.mismatches:
        print(f"  FAIL: {mismatch}")
"""

from __future__ import annotations

import logging
import math
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

try:
    import deepface.DeepFace as DeepFace  # requires tensorflow/torch at runtime
except Exception:  # noqa: BLE001
    DeepFace = None  # type: ignore[assignment]

from pipeline.persona.ethnicity import get_deepface_race_id

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ITA thresholds — Chardon (1991)
# ---------------------------------------------------------------------------

_FITZPATRICK_THRESHOLDS: list[tuple[float, str]] = [
    (55.0, "I"),
    (41.0, "II"),
    (28.0, "III"),
    (10.0, "IV"),
    (-30.0, "V"),
    (float("-inf"), "VI"),
]

_FITZPATRICK_ORDER = ["I", "II", "III", "IV", "V", "VI"]

# ---------------------------------------------------------------------------
# Scoring weights
# ---------------------------------------------------------------------------

_FIELD_WEIGHTS: dict[str, float] = {
    "age": 0.15,
    "gender": 0.25,
    "race": 0.35,
    "fitzpatrick_type": 0.25,
}

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class FieldValidation:
    """Validation result for a single demographic field."""

    field_name: str  # "age" | "gender" | "race" | "fitzpatrick_type"
    expected: str  # expected value from persona
    observed: str  # observed value from DeepFace / ITA
    match: bool
    confidence: float  # 0.0–1.0; 1.0 if no confidence info available


@dataclass
class DiversityReport:
    """Aggregate diversity validation result for one image."""

    validations: list[FieldValidation] = field(default_factory=list)
    ita_value: float | None = None
    deepface_raw: dict = field(default_factory=dict)

    @property
    def score(self) -> float:
        """Weighted match score in [0.0, 1.0]."""
        total_weight = sum(_FIELD_WEIGHTS.values())
        earned = 0.0
        for v in self.validations:
            w = _FIELD_WEIGHTS.get(v.field_name, 1.0 / max(len(self.validations), 1))
            if v.match:
                earned += w
        return earned / total_weight if total_weight > 0 else 0.0

    @property
    def mismatches(self) -> list[str]:
        """Human-readable descriptions of mismatched fields."""
        return [
            f"{v.field_name}: expected={v.expected!r}, observed={v.observed!r}"
            for v in self.validations
            if not v.match
        ]


# ---------------------------------------------------------------------------
# ITA helpers
# ---------------------------------------------------------------------------


def compute_ita(hex_color: str) -> float:
    """Compute the Individual Typology Angle (ITA) from a hex skin colour.

    ITA = arctan((L* - 50) / b*) × (180/π)

    Uses sRGB → XYZ D65 → CIE L*a*b* conversion.
    """
    h = hex_color.lstrip("#")
    if len(h) != 6:
        raise ValueError(f"Invalid hex colour: {hex_color!r}")
    r_int = int(h[0:2], 16)
    g_int = int(h[2:4], 16)
    b_int = int(h[4:6], 16)

    def _linearize(c: int) -> float:
        cv = c / 255.0
        if cv <= 0.04045:
            return cv / 12.92
        return ((cv + 0.055) / 1.055) ** 2.4

    rl, gl, bl = _linearize(r_int), _linearize(g_int), _linearize(b_int)

    # sRGB D65 → XYZ (normalised to D65 white); only y and z are used for ITA
    y = (rl * 0.2126 + gl * 0.7152 + bl * 0.0722) / 1.00000
    z = (rl * 0.0193 + gl * 0.1192 + bl * 0.9505) / 1.08883

    def _f(t: float) -> float:
        if t > 0.008856:
            return t ** (1.0 / 3.0)
        return 7.787 * t + 16.0 / 116.0

    fy, fz = _f(y), _f(z)
    L_star = 116.0 * fy - 16.0
    b_star = 200.0 * (fy - fz)

    if abs(b_star) < 1e-9:
        return 90.0 if L_star > 50 else 0.0
    return math.degrees(math.atan((L_star - 50.0) / b_star))


def ita_to_fitzpatrick(ita: float) -> str:
    """Convert an ITA value to a Fitzpatrick skin type using Chardon thresholds.

    Thresholds:
      > 55°        → I
      41° to 55°   → II
      28° to 41°   → III
      10° to 28°   → IV
      -30° to 10°  → V
      < -30°       → VI
    """
    for threshold, fitz_type in _FITZPATRICK_THRESHOLDS:
        if ita > threshold:
            return fitz_type
    return "VI"


def _fitzpatrick_adjacent(a: str, b: str) -> bool:
    """Return True if *a* and *b* are the same or adjacent Fitzpatrick types."""
    try:
        ia, ib = _FITZPATRICK_ORDER.index(a), _FITZPATRICK_ORDER.index(b)
    except ValueError:
        return False
    return abs(ia - ib) <= 1


# ---------------------------------------------------------------------------
# DeepFace validation
# ---------------------------------------------------------------------------


def validate_avatar_diversity(
    image_bytes: bytes,
    persona: dict,
    *,
    age_tolerance: int = 10,
) -> DiversityReport:
    """Compare a generated avatar image against the persona's demographic fields.

    Parameters
    ----------
    image_bytes:
        Raw bytes of the generated avatar image (JPEG or PNG).
    persona:
        The avatar persona dict (as returned by ``marshal_avatar_persona``).
        Expected to have at minimum::

            personal.age        int
            personal.gender     "male" | "female" | "non-binary"
            personal.ethnicity  str  (ethnicity ID from ethnicities.yml)
            appearance.skin_tone  str  (hex colour, e.g. "#C8A06A")

    age_tolerance:
        DeepFace age estimates are approximate — allow ±*age_tolerance* years.

    Returns
    -------
    DiversityReport
        Contains per-field validations, the ITA value, and the raw DeepFace output.
    """
    if DeepFace is None:
        raise ImportError(
            "deepface is not available in this environment. "
            "Install it with: pip install 'deepface[torch]'"
        )

    report = DiversityReport()

    # Write image to temp file (DeepFace requires a file path)
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp.write(image_bytes)
        tmp_path = Path(tmp.name)

    try:
        analysis = DeepFace.analyze(
            str(tmp_path),
            actions=["age", "gender", "race"],
            enforce_detection=False,
            silent=True,
        )
    finally:
        tmp_path.unlink(missing_ok=True)

    # DeepFace may return a list (one result per face) — take the first
    if isinstance(analysis, list):
        analysis = analysis[0]

    report.deepface_raw = dict(analysis)

    personal = persona.get("personal", {})
    appearance = persona.get("appearance", {})

    # ------------------------------------------------------------------
    # Age
    # ------------------------------------------------------------------
    expected_age = personal.get("age")
    observed_age = analysis.get("age")
    if expected_age is not None and observed_age is not None:
        age_match = abs(int(expected_age) - int(observed_age)) <= age_tolerance
        report.validations.append(
            FieldValidation(
                field_name="age",
                expected=str(expected_age),
                observed=str(observed_age),
                match=age_match,
                confidence=1.0,
            )
        )

    # ------------------------------------------------------------------
    # Gender
    # ------------------------------------------------------------------
    expected_gender_raw = personal.get("gender", "")
    observed_gender_raw = (analysis.get("dominant_gender") or "").lower()
    # Normalise: DeepFace returns "Man"/"Woman"; persona uses "male"/"female"/"non-binary"
    _gender_map = {"man": "male", "woman": "female", "male": "male", "female": "female"}
    expected_gender = _gender_map.get(expected_gender_raw.lower(), expected_gender_raw.lower())
    observed_gender = _gender_map.get(observed_gender_raw, observed_gender_raw)
    # non-binary is ambiguous — accept either DeepFace output
    gender_match = expected_gender == "non-binary" or expected_gender == observed_gender
    gender_conf = (
        analysis.get("gender", {}).get(
            "Man" if observed_gender_raw in ("man", "male") else "Woman", 0.5
        )
        / 100.0
    )
    report.validations.append(
        FieldValidation(
            field_name="gender",
            expected=expected_gender,
            observed=observed_gender,
            match=gender_match,
            confidence=gender_conf,
        )
    )

    # ------------------------------------------------------------------
    # Race (via ethnicity → deepface_race_id)
    # ------------------------------------------------------------------
    ethnicity_id = personal.get("ethnicity")
    observed_race = (analysis.get("dominant_race") or "").lower()
    if ethnicity_id:
        try:
            expected_deepface_race = get_deepface_race_id(ethnicity_id).lower()
        except KeyError:
            expected_deepface_race = ""
        race_match = expected_deepface_race == observed_race if expected_deepface_race else False
        race_conf = (
            analysis.get("race", {}).get(observed_race.title() if observed_race else "", 0.0)
            / 100.0
        )
        report.validations.append(
            FieldValidation(
                field_name="race",
                expected=expected_deepface_race,
                observed=observed_race,
                match=race_match,
                confidence=race_conf,
            )
        )

    # ------------------------------------------------------------------
    # Fitzpatrick type (via ITA from persona skin_tone hex)
    # ------------------------------------------------------------------
    skin_tone_hex = appearance.get("skin_tone", "")
    if skin_tone_hex:
        try:
            ita = compute_ita(skin_tone_hex)
        except ValueError:
            ita = None
        if ita is not None:
            report.ita_value = ita
            observed_fitzpatrick = ita_to_fitzpatrick(ita)
            expected_fitzpatrick = appearance.get("fitzpatrick_type", "")
            if expected_fitzpatrick:
                fitz_match = _fitzpatrick_adjacent(expected_fitzpatrick, observed_fitzpatrick)
                report.validations.append(
                    FieldValidation(
                        field_name="fitzpatrick_type",
                        expected=expected_fitzpatrick,
                        observed=observed_fitzpatrick,
                        match=fitz_match,
                        confidence=1.0,
                    )
                )

    return report
