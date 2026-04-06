"""LLM-based expression classifier for generated avatar images.

Given an image and a list of expression label *suggestions*, asks a vision LLM
to identify which facial expressions are visually present — without seeing the
instructions used to generate them.

The classifier receives only human-readable label names (e.g. "Thinking") as
soft hints.  It may score those labels plus add any further expressions it
observes, producing 5–10 named scores in total.  The generation-side FACS
instructions and avatar_instructions are intentionally withheld.

Used by:
  - tuning/expression_tuner.py  (CLI tuning agent)
  - test_expression_classification.py  (pytest integration test)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from config.gateway import GatewayClient

logger = logging.getLogger(__name__)

VALIDATION_EXPRESSION_THRESHOLD: float = 0.50

# JSON schema for the vision model response.
_EXPRESSION_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "top_expression": {"type": "string"},
        "expressions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "score": {"type": "number"},
                },
                "required": ["name", "score"],
                "additionalProperties": False,
            },
        },
        "reasoning": {"type": "string"},
    },
    "required": ["top_expression", "expressions", "reasoning"],
    "additionalProperties": False,
}

_EXPRESSION_OUTPUT_CONFIG: dict = {"format": {"type": "json_schema", "schema": _EXPRESSION_SCHEMA}}

# JSON schema for the semantic yes/no text model response.
_SEMANTIC_SCHEMA: dict = {
    "type": "object",
    "properties": {"matches": {"type": "boolean"}},
    "required": ["matches"],
    "additionalProperties": False,
}

_SEMANTIC_OUTPUT_CONFIG: dict = {"format": {"type": "json_schema", "schema": _SEMANTIC_SCHEMA}}

_CLASSIFIER_SYSTEM = """\
You are an expert in facial expression analysis for portrait images.
You will be shown an avatar portrait. Your task: identify which facial
expressions or emotional states are visually present based solely on what you
directly observe — muscle positions, brow shape, eye openness, mouth posture,
head angle, and similar visible cues.

Do NOT infer from context, clothing, or any metadata.  Read only the face.

Rules:
- List between 5 and 10 expression names in the expressions array.
- All scores must sum to approximately 1.0.
- Use simple, common everyday words that anyone would immediately understand.
  Avoid rare or literary vocabulary.
- top_expression must be the name with the highest score."""


@dataclass
class ExpressionClassificationResult:
    """Classification result for a single avatar image."""

    top_expression: str
    scores: dict[str, float] = field(default_factory=dict)
    reasoning: str = ""
    raw_response: str = ""

    def top_n(self, n: int = 3) -> list[str]:
        """Return the top-n expression names by score, highest first."""
        return [k for k, _ in sorted(self.scores.items(), key=lambda x: x[1], reverse=True)[:n]]

    def top_score(self) -> float:
        """Return the probability of the top expression."""
        return self.scores.get(self.top_expression, 0.0)

    def score_for(self, label: str) -> float:
        """Return the score for *label* (case-insensitive lookup, 0.0 if absent)."""
        label_lower = label.lower()
        for k, v in self.scores.items():
            if k.lower() == label_lower:
                return v
        return 0.0

    def is_correct(self, expected_label: str, threshold: float = 0.35) -> bool:
        """True when the top expression matches *expected_label* with score >= *threshold*."""
        return (
            self.top_expression.lower() == expected_label.lower() and self.top_score() >= threshold
        )

    def is_visible(self, expected_label: str, threshold: float = 0.35) -> bool:
        """True when *expected_label* scores >= *threshold* (even if not top)."""
        return self.score_for(expected_label) >= threshold

    def in_top_n(self, expected_label: str, n: int = 3) -> bool:
        label_lower = expected_label.lower()
        return label_lower in [x.lower() for x in self.top_n(n)]


def _call_vision_model(
    gateway_url: str,
    system: str,
    prompt: str,
    image_bytes_decoded: bytes,
    timeout: int,
) -> str:
    """Call a vision-capable LLM via the gateway and return the raw text response."""
    return GatewayClient(gateway_url).image_inspector(
        image_bytes_decoded,
        system,
        prompt,
        timeout=timeout,
        output_config=_EXPRESSION_OUTPUT_CONFIG,
    )


def classify_image_expression(
    image_bytes: bytes,
    expression_labels: list[str] | None = None,
    *,
    gateway_url: str = "http://127.0.0.1:4096",
    timeout: int = 180,
) -> ExpressionClassificationResult:
    """Ask a vision LLM which facial expressions are visible in *image_bytes*.

    Parameters
    ----------
    image_bytes:
        Raw PNG bytes of the generated avatar portrait.
    expression_labels:
        Optional list of expression label names to score (e.g.
        ``["Cautious", "Thinking"]``).  When provided, the classifier is asked
        to score each label in addition to any extras it freely observes — useful
        for differentiating closely related expressions.  When ``None`` (default)
        the classifier operates blind: it receives no label hints and assigns
        names entirely from its own vocabulary.
        Either way, only plain label names are passed — no definitions,
        FACS specs, or generation instructions are ever shown to the classifier.
    gateway_url:
        Base URL of the LLM Gateway server.
    timeout:
        Request timeout in seconds.

    Returns
    -------
    ExpressionClassificationResult
        Top expression name, per-expression scores (5–10 entries), reasoning,
        and raw LLM response.
    """
    if expression_labels:
        label_list = "\n".join(f"  - {label}" for label in expression_labels)
        user_text = (
            "Examine this avatar portrait carefully.\n\n"
            "Score the following expression labels based on what you directly observe "
            "in the face:\n"
            f"{label_list}\n\n"
            "You may also add up to 5 additional expression names if you observe "
            "expressions not covered by the list above.\n"
            "Total entries in the expressions array must be between 5 and 10."
        )
    else:
        user_text = (
            "Examine this avatar portrait carefully.\n\n"
            "Identify and score every facial expression or emotional state you can "
            "directly observe in the face.  Use whatever plain English words best "
            "describe what you see — there is no fixed vocabulary.\n\n"
            "List between 5 and 10 expression names. All scores must sum to "
            "approximately 1.0."
        )

    try:
        raw = _call_vision_model(
            gateway_url=gateway_url,
            system=_CLASSIFIER_SYSTEM,
            prompt=user_text,
            image_bytes_decoded=image_bytes,
            timeout=timeout,
        )
    except Exception as exc:
        logger.error("classify_image_expression: LLM call failed: %s", exc)
        raise

    result = _parse_expression_response(raw, expression_labels or [])
    result.raw_response = raw
    return result


def _call_text_model(
    gateway_url: str,
    prompt: str,
    timeout: int,
) -> str:
    """Call a text-only LLM via the gateway and return the raw response."""
    return GatewayClient(gateway_url).text_gen(
        [{"role": "user", "content": prompt}],
        timeout=timeout,
        output_config=_SEMANTIC_OUTPUT_CONFIG,
    )


def semantic_effective_score(
    scores: dict[str, float],
    expected: str,
    *,
    gateway_url: str = "http://127.0.0.1:4096",
    timeout: int = 30,
) -> float:
    """Return the summed probability of all output phrases semantically matching *expected*.

    Each phrase in *scores* is checked individually against *expected* with a
    separate LLM call.  Phrases that match contribute their score to the total.

    Example: target "Thinking", classifier output
    {"pensive": 0.25, "focused": 0.20, "contemplative": 0.15, "neutral": 0.25, ...}
    → if "pensive", "focused", "contemplative" all match → effective score = 0.60.

    Parameters
    ----------
    scores:
        The ``scores`` dict from ``ExpressionClassificationResult``.
    expected:
        The human-readable target label (e.g. ``"Thinking"``).
    gateway_url:
        Base URL of the LLM Gateway server.
    timeout:
        Forwarded to the underlying model call.

    Returns
    -------
    float
        Summed score of all semantically matching phrases (0.0 if none match or
        the LLM call fails).
    """
    total = 0.0
    for name, score in scores.items():
        if score <= 0.0:
            continue
        prompt = (
            f"Look at a portrait photo where someone's face shows a '{name}' expression. "
            f"Does that face look the same as a face showing '{expected}'? "
            f"Set matches to true if yes, false if no."
        )
        try:
            raw = _call_text_model(gateway_url=gateway_url, prompt=prompt, timeout=timeout)
            parsed = json.loads(raw)
            matched = bool(parsed.get("matches", False))
        except Exception as exc:
            logger.warning(
                "semantic_effective_score: call failed for %r vs %r (%s)", name, expected, exc
            )
            continue
        if matched:
            total += score
            logger.debug(
                "semantic_effective_score: '%s' matches '%s' (score=%.2f, running=%.2f)",
                name,
                expected,
                score,
                total,
            )

    logger.debug("semantic_effective_score: expected=%r, total=%.2f", expected, total)
    return total


def calculate_expression_score(
    result: ExpressionClassificationResult,
    expected: str,
    *,
    gateway_url: str = "http://127.0.0.1:4096",
    timeout: int = 30,
) -> float:
    """Compute the Expression Score for *result* against *expected* label.

    Returns 1.0 on direct match, semantic effective score on semantic match,
    or semantic score squared to amplify failure.
    """
    if (
        result.top_expression.lower() == expected.lower()
        and result.top_score() >= VALIDATION_EXPRESSION_THRESHOLD
    ):
        return 1.0

    sum_score = semantic_effective_score(
        result.scores, expected, gateway_url=gateway_url, timeout=timeout
    )
    if sum_score >= VALIDATION_EXPRESSION_THRESHOLD:
        return sum_score
    return sum_score**2


def _parse_expression_response(
    raw: str,
    hint_labels: list[str],
) -> ExpressionClassificationResult:
    """Parse the LLM JSON response into an ExpressionClassificationResult."""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("classify_expression: JSON parse failed: %s — raw=%r", exc, raw[:200])
        parsed = {}

    if not isinstance(parsed, dict):
        parsed = {}

    raw_expressions = parsed.get("expressions", [])
    scores: dict[str, float] = {}
    if isinstance(raw_expressions, list):
        for entry in raw_expressions:
            if isinstance(entry, dict):
                name = str(entry.get("name", "")).strip()
                try:
                    score = float(entry.get("score", 0.0))
                except TypeError, ValueError:
                    score = 0.0
                if name:
                    scores[name] = score

    # Ensure all hint labels have an entry (default 0.0 if the classifier skipped them).
    for label in hint_labels:
        if label not in scores:
            scores[label] = 0.0

    top = str(parsed.get("top_expression", "")).strip()
    # If the model didn't set top_expression, derive it from the highest score.
    if not top and scores:
        top = max(scores, key=lambda k: scores[k])

    reasoning = str(parsed.get("reasoning", "")).strip()

    return ExpressionClassificationResult(
        top_expression=top,
        scores=scores,
        reasoning=reasoning,
    )
