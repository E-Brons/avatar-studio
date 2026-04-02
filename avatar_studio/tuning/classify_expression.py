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

import base64
import logging
import re
from dataclasses import dataclass, field

import requests
import yaml

logger = logging.getLogger(__name__)

_CLASSIFIER_SYSTEM = """\
You are an expert in facial expression analysis for portrait images.
You will be shown an avatar portrait. Your task: identify which facial
expressions or emotional states are visually present based solely on what you
directly observe — muscle positions, brow shape, eye openness, mouth posture,
head angle, and similar visible cues.

Do NOT infer from context, clothing, or any metadata.  Read only the face.

Output ONLY YAML in this exact format (no markdown fences):

top_expression: <name>
expressions:
  <name>: <float 0.0-1.0>
  ...
reasoning: <one sentence citing key visible facial cues>

Rules:
- List between 5 and 10 expression names total.
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
        return [
            k
            for k, _ in sorted(
                self.scores.items(), key=lambda x: x[1], reverse=True
            )[:n]
        ]

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
            self.top_expression.lower() == expected_label.lower()
            and self.top_score() >= threshold
        )

    def is_visible(self, expected_label: str, threshold: float = 0.35) -> bool:
        """True when *expected_label* scores >= *threshold* (even if not top)."""
        return self.score_for(expected_label) >= threshold

    def in_top_n(self, expected_label: str, n: int = 3) -> bool:
        label_lower = expected_label.lower()
        return label_lower in [x.lower() for x in self.top_n(n)]


def _call_vision_model(
    model: str,
    system: str,
    prompt: str,
    image_b64: str,
    ollama_url: str,
    timeout: int,
) -> str:
    """Call a vision-capable LLM and return the raw text response.

    Routing by model prefix:
    - ``ollama/*``  → Ollama REST API directly (avoids litellm Transfer-Encoding bug)
    - ``cli/*``     → not supported in standalone package; raises NotImplementedError
    - anything else → litellm (API-key provider: OpenAI, Anthropic, etc.)
    """
    if "ollama" in model.lower():
        bare = model.removeprefix("ollama/")
        payload = {
            "model": bare,
            "system": system,
            "prompt": prompt,
            "images": [image_b64],
            "stream": False,
            "options": {"temperature": 0.1},
        }
        resp = requests.post(
            f"{ollama_url}/api/generate", json=payload, timeout=timeout
        )
        resp.raise_for_status()
        return resp.json().get("response", "")

    if model.startswith("cli/"):
        raise NotImplementedError(
            "cli/* model routing requires the 'core_llm' package from the dashboard repo. "
            "Use an ollama/* or litellm model instead."
        )

    # Non-Ollama, non-CLI path — use litellm
    import litellm  # noqa: PLC0415

    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                {"type": "text", "text": prompt},
            ],
        },
    ]
    response = litellm.completion(
        model=model,
        messages=messages,
        temperature=0.1,
        max_tokens=512,
        timeout=timeout,
    )
    return response.choices[0].message.content or ""


def classify_image_expression(
    image_bytes: bytes,
    expression_labels: list[str] | None = None,
    *,
    model: str,
    ollama_url: str = "http://127.0.0.1:4096",
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
    model:
        Model string.  Prefix determines routing:
        ``"ollama/<name>"`` → Ollama REST API;
        ``"cli/<name>"`` → not supported (raises NotImplementedError);
        anything else → litellm.
    ollama_url:
        Base URL of the Ollama server.
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
        yaml_template = "\n".join(f"  {label}: 0.0" for label in expression_labels)
        user_text = (
            "Examine this avatar portrait carefully.\n\n"
            "Score the following expression labels based on what you directly observe "
            "in the face:\n"
            f"{label_list}\n\n"
            "You may also add up to 5 additional expression names if you observe "
            "expressions not covered by the list above.\n"
            "Total entries in the 'expressions' block must be between 5 and 10.\n\n"
            "Reply ONLY as YAML (no markdown fences):\n"
            f"top_expression: <the name with the highest score>\n"
            f"expressions:\n{yaml_template}\n"
            "  <additional if observed>: 0.0\n"
            "reasoning: <one sentence citing key visible facial cues>"
        )
    else:
        user_text = (
            "Examine this avatar portrait carefully.\n\n"
            "Identify and score every facial expression or emotional state you can "
            "directly observe in the face.  Use whatever plain English words best "
            "describe what you see — there is no fixed vocabulary.\n\n"
            "List between 5 and 10 expression names. All scores must sum to "
            "approximately 1.0.\n\n"
            "Reply ONLY as YAML (no markdown fences):\n"
            "top_expression: <the name with the highest score>\n"
            "expressions:\n"
            "  <name>: <float 0.0-1.0>\n"
            "  ...\n"
            "reasoning: <one sentence citing key visible facial cues>"
        )

    b64 = base64.b64encode(image_bytes).decode()

    try:
        raw = _call_vision_model(
            model=model,
            system=_CLASSIFIER_SYSTEM,
            prompt=user_text,
            image_b64=b64,
            ollama_url=ollama_url,
            timeout=timeout,
        )
    except Exception as exc:
        logger.error("classify_image_expression: LLM call failed: %s", exc)
        raise

    result = _parse_expression_response(raw, expression_labels or [])
    result.raw_response = raw
    return result


def _call_text_model(
    model: str,
    prompt: str,
    ollama_url: str,
    timeout: int,
) -> str:
    """Call a text-only LLM and return the raw response.

    Routing:
    - ``ollama/*`` → Ollama REST API (no image field)
    - ``cli/*``    → not supported (raises NotImplementedError)
    - else         → litellm
    """
    if "ollama" in model.lower():
        bare = model.removeprefix("ollama/")
        payload = {
            "model": bare,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.0},
        }
        resp = requests.post(
            f"{ollama_url}/api/generate", json=payload, timeout=timeout
        )
        resp.raise_for_status()
        return resp.json().get("response", "")

    if model.startswith("cli/"):
        raise NotImplementedError(
            "cli/* model routing requires the 'core_llm' package from the dashboard repo. "
            "Use an ollama/* or litellm model instead."
        )

    import litellm  # noqa: PLC0415

    response = litellm.completion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=128,
        timeout=timeout,
    )
    return response.choices[0].message.content or ""


def semantic_effective_score(
    scores: dict[str, float],
    expected: str,
    *,
    model: str,
    ollama_url: str = "http://127.0.0.1:4096",
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
    model:
        Text model string (``ollama/*``, or a litellm model name).
    ollama_url, timeout:
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
            f"Does that face look the same as a face showing '{expected}'?\n"
            f"Answer with a single word: yes or no."
        )
        try:
            raw = _call_text_model(
                model=model, prompt=prompt, ollama_url=ollama_url, timeout=timeout
            )
        except Exception as exc:
            logger.warning(
                "semantic_effective_score: call failed for %r vs %r (%s)", name, expected, exc
            )
            continue
        if raw.strip().lower().startswith("yes"):
            total += score
            logger.debug(
                "semantic_effective_score: '%s' matches '%s' (score=%.2f, running=%.2f)",
                name, expected, score, total,
            )

    logger.debug(
        "semantic_effective_score: expected=%r, total=%.2f", expected, total
    )
    return total


def _parse_expression_response(
    raw: str,
    hint_labels: list[str],
) -> ExpressionClassificationResult:
    """Parse the LLM YAML response into an ExpressionClassificationResult."""
    cleaned = re.sub(r"^```(?:ya?ml)?\s*\n?", "", raw.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"\n?```\s*$", "", cleaned.strip())

    try:
        parsed = yaml.safe_load(cleaned) or {}
    except yaml.YAMLError as exc:
        logger.warning("classify_expression: YAML parse failed: %s — raw=%r", exc, raw[:200])
        parsed = {}

    if not isinstance(parsed, dict):
        parsed = {}

    raw_scores = parsed.get("expressions", {})
    scores: dict[str, float] = {}
    if isinstance(raw_scores, dict):
        for name, val in raw_scores.items():
            try:
                scores[str(name)] = float(val)
            except (TypeError, ValueError):
                scores[str(name)] = 0.0

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
