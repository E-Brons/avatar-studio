"""Stage B — generate advisor CV via LLM."""

import logging
import re

import yaml

from avatar_studio.config.config import SETTINGS
from avatar_studio.config.gateway import GatewayClient

logger = logging.getLogger(__name__)

_MAX_RETRIES: int = SETTINGS["max_retries"]


def generate_advisor_profile(
    role: str,
    demographics: dict,
    *,
    gateway_url: str = "http://127.0.0.1:4096",
    max_retries: int = _MAX_RETRIES,
) -> dict:
    """Generate education, experience, and traits from role via LLM.

    Returns: {"education": [...], "experience": [...], "traits": [...]}
    """
    gender = demographics.get("gender", "person")
    age = demographics.get("age", 40)

    logger.info("[Step B] START — generate_cv (gateway=%s)", gateway_url)
    system_msg = (
        "You are an advisor profile generator. "
        "Given a role, gender, and age, create a realistic professional profile. "
        "Reply ONLY as YAML with exactly three keys: education, experience, traits. "
        "Each key maps to a short list. "
        "Experience entries must be SHORT: job title and employer only, no dates or descriptions."
    )
    user_msg = (
        f"Generate a realistic advisor profile for a {gender}, age {age}, "
        f"working as a {role}.\n\n"
        f"Reply as YAML only:\n"
        f"education:\n"
        f"  - <degree or certification 1>\n"
        f"  - <degree or certification 2>\n"
        f"experience:\n"
        f"  - <Job Title, Employer>  # e.g. Senior Analyst, Goldman Sachs\n"
        f"  - <Job Title, Employer>\n"
        f"  - <Job Title, Employer>  # optional 3rd\n"
        f"traits:\n"
        f"  - <personality trait 1>\n"
        f"  - <personality trait 2>\n"
        f"  - <personality trait 3>\n"
    )

    messages: list[dict] = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]

    client = GatewayClient(gateway_url)

    # The retry loop here handles YAML parsing/validation failures only.
    # Network-level retries are delegated to the gateway via max_retries.
    for attempt in range(1, max_retries + 1):
        try:
            content = client.text_gen(messages, max_retries=max_retries)
            if not content or not content.strip():
                logger.warning(
                    "Profile gen attempt %d/%d: empty response", attempt, max_retries
                )
                continue

            # Strip code fences
            cleaned = re.sub(
                r"^```(?:ya?ml)?\s*\n?", "", content.strip(), flags=re.MULTILINE
            )
            cleaned = re.sub(r"\n?```\s*$", "", cleaned.strip())

            parsed = yaml.safe_load(cleaned)
            if not isinstance(parsed, dict):
                logger.warning(
                    "Profile gen attempt %d/%d: expected dict, got %s",
                    attempt, max_retries, type(parsed).__name__,
                )
                continue

            education = parsed.get("education", [])
            experience = parsed.get("experience", [])
            traits = parsed.get("traits", [])

            # Validate: at least one item in each
            if not education or not experience or not traits:
                logger.warning(
                    "Profile gen attempt %d/%d: missing fields (edu=%d, exp=%d, traits=%d)",
                    attempt, max_retries, len(education), len(experience), len(traits),
                )
                continue

            # Normalize to lists of strings
            result = {
                "education": [str(e) for e in education][:2],
                "experience": [str(e) for e in experience][:3],
                "traits": [str(t) for t in traits][:3],
            }
            logger.info("Generated advisor profile: %s", result)
            logger.info("[Step B] DONE  — role=%s, traits=%d", role, len(result.get("traits", [])))
            return result

        except Exception as exc:
            if attempt == max_retries:
                raise
            logger.warning(
                "Profile gen attempt %d/%d failed: %s", attempt, max_retries, exc
            )

    raise ValueError(
        f"Failed to generate advisor profile after {max_retries} attempts"
    )


# Backward-compat alias
_generate_advisor_profile = generate_advisor_profile
