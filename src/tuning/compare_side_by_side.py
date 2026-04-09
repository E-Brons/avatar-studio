"""Vision-LLM-based side-by-side comparison scorer for avatar images.

Given a reference image and a generated image, stitches them side by side and asks a vision
LLM to score:
  A. Identity consistency (same person)
  B. Goal achievement
  C. Render quality

Compound score = sqrt(50% A + 30% B + 20% C), each component amplified via sqrt if > 0.60.

Used by callers that want to compare reference vs. generated portraits (e.g. style transfer,
expression variant, identity preservation checks).
"""

from __future__ import annotations

import io
import json
import logging
import math
import re
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

from config.gateway import GatewayClient

logger = logging.getLogger(__name__)

# JSON schema for the vision model response.
_COMPARISON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "identity_score": {"type": "integer", "minimum": 0, "maximum": 100},
        "goal_score": {"type": "integer", "minimum": 0, "maximum": 100},
        "quality_score": {"type": "integer", "minimum": 0, "maximum": 100},
        "reasoning": {"type": "string"},
    },
    "required": ["identity_score", "goal_score", "quality_score", "reasoning"],
    "additionalProperties": False,
}

_COMPARISON_OUTPUT_CONFIG: dict = {"format": {"type": "json_schema", "schema": _COMPARISON_SCHEMA}}

_CLASSIFIER_SYSTEM = """\
You are an expert visual comparison analyst for AI-generated portrait images.
You will be shown two images side by side: a REFERENCE image on the left and a GENERATED image
on the right.
Your task: score three attributes on a 0–100 integer scale.

Score A — Identity consistency: How likely is it that both images depict the same person?
  100 = clearly the same person; 0 = clearly different people.

Score B — Goal achievement: How well does the GENERATED image achieve the stated goal?
  100 = goal fully achieved; 0 = goal not achieved at all.

Score C — Render quality: How technically high-quality is the GENERATED image?
  100 = crisp, well-lit, no artifacts; 0 = heavily degraded or corrupted.

Be precise and evidence-based. Cite specific visual features in your reasoning."""


@dataclass
class ComparisonResult:
    """Comparison result from a side-by-side vision LLM evaluation."""

    identity_score: float  # 0–1
    goal_score: float  # 0–1
    quality_score: float  # 0–1
    compound_score: float  # sqrt(50% A + 30% B + 20% C), each component amplified
    reasoning: str = ""
    raw_response: str = ""


def _stitch_images(
    reference_bytes: bytes,
    generated_bytes: bytes,
    reference_label: str,
    generated_label: str,
) -> bytes:
    """Resize both images to 512×512, place side-by-side with a 20px gap, add text labels.

    Returns PNG bytes of the stitched image (1044×542 RGBA).
    """
    size = 512
    gap = 20
    footer_height = 30

    ref_img = Image.open(io.BytesIO(reference_bytes)).convert("RGBA").resize((size, size))
    gen_img = Image.open(io.BytesIO(generated_bytes)).convert("RGBA").resize((size, size))

    total_width = size + gap + size
    total_height = size + footer_height
    canvas = Image.new("RGBA", (total_width, total_height), (255, 255, 255, 255))

    canvas.paste(ref_img, (0, 0))
    canvas.paste(gen_img, (size + gap, 0))

    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()

    draw.text((5, size + 8), reference_label, fill=(0, 0, 0, 255), font=font)
    draw.text((size + gap + 5, size + 8), generated_label, fill=(0, 0, 0, 255), font=font)

    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue()


def _call_vision_model(
    gateway_url: str,
    system: str,
    prompt: str,
    image_bytes: bytes,
    timeout: int,
) -> str:
    """Call a vision-capable LLM via the gateway and return the raw text response."""
    return GatewayClient(gateway_url).image_inspector(
        image_bytes,
        system,
        prompt,
        timeout=timeout,
        output_config=_COMPARISON_OUTPUT_CONFIG,
    )


def compare_side_by_side(
    reference_bytes: bytes,
    generated_bytes: bytes,
    goal: str,
    *,
    reference_label: str = "REFERENCE",
    generated_label: str = "GENERATED",
    gateway_url: str = "http://127.0.0.1:4096",
    timeout: int = 180,
) -> ComparisonResult:
    """Compare a reference image against a generated image using a vision LLM.

    Parameters
    ----------
    reference_bytes:
        Raw PNG bytes of the reference portrait.
    generated_bytes:
        Raw PNG bytes of the generated portrait.
    goal:
        A plain-English description of what the generated image was trying to achieve
        (e.g. "happiness expression in studio_3d style").
    reference_label:
        Label shown below the left (reference) image in the stitched comparison.
    generated_label:
        Label shown below the right (generated) image in the stitched comparison.
    gateway_url:
        Base URL of the LLM Gateway server.
    timeout:
        Request timeout in seconds.

    Returns
    -------
    ComparisonResult
        Three 0–1 component scores, compound score, reasoning, and raw LLM response.
    """
    stitched = _stitch_images(reference_bytes, generated_bytes, reference_label, generated_label)

    user_text = (
        "Examine the side-by-side comparison image carefully.\n\n"
        f"- A text description of the goal: `{goal}`\n\n"
        "Instructions to output three integer scores (0–100) for:\n"
        "  A. Identity consistency — are both images the same person?\n"
        "  B. Goal achievement — does the generated image achieve the stated goal?\n"
        "  C. Render quality — is the generated image technically high quality?\n\n"
        "Also provide a one-sentence reasoning citing specific visual evidence."
    )

    try:
        raw = _call_vision_model(
            gateway_url=gateway_url,
            system=_CLASSIFIER_SYSTEM,
            prompt=user_text,
            image_bytes=stitched,
            timeout=timeout,
        )
    except Exception as exc:
        logger.error("compare_side_by_side: LLM call failed: %s", exc)
        raise

    result = _parse_comparison_response(raw)
    result.raw_response = raw
    return result


def _parse_comparison_response(raw: str) -> ComparisonResult:
    """Parse the LLM JSON response into a ComparisonResult.

    Handles plain JSON and markdown code-fence wrapped JSON. Returns zero scores on parse
    failure.
    """
    text = raw.strip()
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence_match:
        text = fence_match.group(1).strip()

    parsed: dict = {}
    try:
        candidate = json.loads(text)
        if isinstance(candidate, dict):
            parsed = candidate
    except json.JSONDecodeError as exc:
        logger.warning("compare_side_by_side: JSON parse failed: %s — raw=%r", exc, raw[:200])

    def _to_float(key: str) -> float:
        try:
            return float(parsed.get(key, 0)) / 100.0
        except TypeError, ValueError:
            return 0.0

    def _amplify(score: float) -> float:
        return math.sqrt(score) if score > 0.60 else score / 2.0

    identity = _amplify(_to_float("identity_score"))
    goal = _amplify(_to_float("goal_score"))
    quality = _amplify(_to_float("quality_score"))
    compound = math.sqrt(0.5 * identity + 0.3 * goal + 0.2 * quality)
    reasoning = str(parsed.get("reasoning", "")).strip()

    return ComparisonResult(
        identity_score=identity,
        goal_score=goal,
        quality_score=quality,
        compound_score=compound,
        reasoning=reasoning,
    )
