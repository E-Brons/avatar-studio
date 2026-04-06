"""LLM-based style classifier for generated avatar images.

Given an image and a list of style definitions from styles.yml, asks a vision LLM
to identify which style best represents the image.

Used by:
  - tuning/style_tuner.py  (CLI tuning agent)
  - test_style_classification.py  (pytest test)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from config.gateway import GatewayClient

logger = logging.getLogger(__name__)

# JSON schema for the vision model response.
_STYLE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "top_style": {"type": "string"},
        "scores": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "style_id": {"type": "string"},
                    "score": {"type": "number"},
                },
                "required": ["style_id", "score"],
                "additionalProperties": False,
            },
        },
        "reasoning": {"type": "string"},
    },
    "required": ["top_style", "scores", "reasoning"],
    "additionalProperties": False,
}

_STYLE_OUTPUT_CONFIG: dict = {"format": {"type": "json_schema", "schema": _STYLE_SCHEMA}}

_CLASSIFIER_SYSTEM = """\
You are an expert visual style analyst for AI-generated portrait images.
You will be shown an avatar portrait and a list of named visual styles, each with key technical traits.
Your task: identify which style the portrait most closely represents.

Assign higher scores to styles whose technical traits are clearly visible in the image.
Be specific — cite evidence such as "thick dark outlines", "subsurface scattering", "flat fills", etc."""


@dataclass
class StyleClassificationResult:
    """Classification result for a single image."""

    top_style_id: str
    scores: dict[str, float] = field(default_factory=dict)
    reasoning: str = ""
    raw_response: str = ""

    def top_n(self, n: int = 3) -> list[str]:
        """Return the top-n style IDs by score, highest first."""
        return [k for k, _ in sorted(self.scores.items(), key=lambda x: x[1], reverse=True)[:n]]

    def is_correct(self, expected_style_id: str) -> bool:
        return self.top_style_id == expected_style_id

    def in_top_n(self, expected_style_id: str, n: int = 3) -> bool:
        return expected_style_id in self.top_n(n)


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
        output_config=_STYLE_OUTPUT_CONFIG,
    )


def classify_image_style(
    image_bytes: bytes,
    styles: list[dict],
    *,
    gateway_url: str = "http://127.0.0.1:4096",
    timeout: int = 180,
) -> StyleClassificationResult:
    """Ask a vision LLM to classify which style the image best represents.

    Parameters
    ----------
    image_bytes:
        Raw PNG bytes of the generated avatar portrait.
    styles:
        Style entries from styles.yml (the ``styles`` list).  ``random`` is
        automatically excluded since it has no defined visual traits.
    gateway_url:
        Base URL of the LLM Gateway server.
    timeout:
        Request timeout in seconds.

    Returns
    -------
    StyleClassificationResult
        Top classified style, per-style scores, reasoning, and raw LLM response.
    """
    checkable = [s for s in styles if s.get("id") != "random" and s.get("key_technical_traits")]

    if not checkable:
        logger.warning("classify_image_style: no checkable styles (all have empty traits)")
        return StyleClassificationResult(top_style_id="")

    style_lines: list[str] = []
    for s in checkable:
        traits = s.get("key_technical_traits") or []
        traits_str = "; ".join(traits) if traits else s.get("description", "(no traits listed)")
        style_lines.append(f"- {s['id']} ({s.get('name', s['id'])}):\n    {traits_str}")
    style_block = "\n".join(style_lines)

    style_ids = [s["id"] for s in checkable]

    user_text = (
        "Examine this avatar portrait carefully.\n\n"
        "Available styles and their key visual traits:\n"
        f"{style_block}\n\n"
        f"Choose the best matching style_id from: {', '.join(style_ids)}\n\n"
        "Return scores for every style_id listed above."
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
        logger.error("classify_image_style: LLM call failed: %s", exc)
        raise

    result = _parse_classification_response(raw, style_ids)
    result.raw_response = raw
    return result


def _parse_classification_response(raw: str, style_ids: list[str]) -> StyleClassificationResult:
    """Parse the LLM JSON response into a StyleClassificationResult."""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("classify_style: JSON parse failed: %s — raw=%r", exc, raw[:200])
        parsed = {}

    if not isinstance(parsed, dict):
        parsed = {}

    top = str(parsed.get("top_style", "")).strip()
    if top not in style_ids:
        top = ""

    raw_scores = parsed.get("scores", [])
    scores: dict[str, float] = {}
    if isinstance(raw_scores, list):
        for entry in raw_scores:
            if isinstance(entry, dict):
                sid = str(entry.get("style_id", "")).strip()
                if sid in style_ids:
                    try:
                        scores[sid] = float(entry.get("score", 0.0))
                    except TypeError, ValueError:
                        scores[sid] = 0.0

    # If top wasn't parsed but scores exist, derive top from highest score.
    if not top and scores:
        top = max(scores, key=lambda k: scores[k])

    reasoning = str(parsed.get("reasoning", "")).strip()

    return StyleClassificationResult(
        top_style_id=top,
        scores=scores,
        reasoning=reasoning,
    )


def calculate_style_score(result: StyleClassificationResult, expected_style_id: str) -> float:
    """Compute the Style Score for *result* against *expected_style_id*.

    Returns sqrt of the style's score on correct classification (amplifying success),
    or the raw score on mismatch.
    """
    style_score = result.scores.get(expected_style_id, 0.0)
    if result.top_style_id == expected_style_id:
        return style_score**0.5
    return style_score
