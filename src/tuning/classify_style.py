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
import re
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
    """Parse the LLM JSON response into a StyleClassificationResult.

    Handles three response formats in priority order:
    1. Plain JSON object matching _STYLE_SCHEMA
    2. JSON object wrapped in markdown code fences (```json ... ```)
    3. Free-form Markdown analysis (regex fallback)
    """
    # Strip code fences if present
    text = raw.strip()
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence_match:
        text = fence_match.group(1).strip()

    parsed: dict = {}
    try:
        candidate = json.loads(text)
        if isinstance(candidate, dict):
            parsed = candidate
    except json.JSONDecodeError:
        pass

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

    reasoning = str(parsed.get("reasoning", "")).strip()

    # ── Markdown regex fallback ──────────────────────────────────────────────
    if not top or not scores:
        # Extract top style: **Best Match: `id`** or **top_style: id** etc.
        top_match = re.search(
            r"(?:Best [Mm]atch|[Tt]op(?:_style)?|[Vv]erdict)\s*[:\-–]?\s*[`'\"]?(\w+)[`'\"]?",
            raw,
        )
        if top_match:
            candidate_top = top_match.group(1).strip()
            if candidate_top in style_ids:
                top = candidate_top

        # Extract scores: `id` ... N/100  OR  | id | N |  OR  id — Score: N
        for sid in style_ids:
            if sid in scores:
                continue
            # table/bold pattern: id ... score N (0–100)
            pattern = rf"[`'\"]?{re.escape(sid)}[`'\"]?[^|\n]*?[Ss]core[^\d]*(\d+(?:\.\d+)?)"
            m = re.search(pattern, raw)
            if not m:
                # inline: id | N |
                m = re.search(rf"\b{re.escape(sid)}\b[^|\n]*\|\s*\*{{0,2}}(\d+(?:\.\d+)?)", raw)
            if not m:
                # bold score: **N** near id
                m = re.search(
                    rf"\b{re.escape(sid)}\b[^\n]{{0,60}}\*{{1,2}}(\d+(?:\.\d+)?)\*{{0,2}}",
                    raw,
                )
            if m:
                raw_val = float(m.group(1))
                # Normalize: scores > 1 are assumed out of 100
                scores[sid] = raw_val / 100.0 if raw_val > 1.0 else raw_val

        if not reasoning:
            # Use the first non-header line as reasoning excerpt
            for line in raw.splitlines():
                line = line.strip().lstrip("#").strip()
                if line and not line.startswith("**"):
                    reasoning = line[:300]
                    break

    # If top wasn't parsed but scores exist, derive top from highest score.
    if not top and scores:
        top = max(scores, key=lambda k: scores[k])

    if not top and not scores:
        logger.warning("classify_style: JSON parse failed — raw=%r", raw[:200])

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
