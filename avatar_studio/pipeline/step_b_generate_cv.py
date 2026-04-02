"""Stage B — generate advisor CV via LLM."""

import logging
import re

import litellm
import yaml

from avatar_studio.config.config import SETTINGS

logger = logging.getLogger(__name__)

_MAX_RETRIES: int = SETTINGS["max_retries"]


def _reset_litellm_client() -> None:
    """Replace litellm's HTTP clients with no-keepalive instances.

    Ollama's /api/show returns ``Transfer-Encoding: chunked, chunked`` which
    httpx raises as RemoteProtocolError.  Under sustained load this corrupts
    the keep-alive TCP connection that gets reused for the actual /api/generate
    completion call.  Disabling keep-alive on both the module_level_client
    (used for /api/show) and the in_memory_llm_clients_cache entry (used for
    completions) ensures every request opens a fresh connection.
    """
    try:
        import httpx
        from litellm.llms.custom_httpx.http_handler import HTTPHandler

        no_keepalive = httpx.Limits(max_connections=10, max_keepalive_connections=0)

        # module_level_client — used by Ollama's get_model_info (/api/show)
        litellm.module_level_client = HTTPHandler(
            client=httpx.Client(limits=no_keepalive, follow_redirects=True)
        )

        # in_memory_llm_clients_cache — used by actual completion calls
        cache = getattr(litellm, "in_memory_llm_clients_cache", None)
        if cache is not None:
            fresh = HTTPHandler(
                client=httpx.Client(limits=no_keepalive, follow_redirects=True)
            )
            try:
                cache.set_cache("httpx_client", fresh)
                cache.set_cache("httpx_client_ssl_verify_None", fresh)
            except Exception:
                pass
    except Exception:
        pass


# Install a no-keepalive HTTP client on litellm's module_level_client at
# import time.  Ollama's /api/show returns duplicate Transfer-Encoding headers
# which httpx rejects; with keepalive disabled each request gets a fresh TCP
# connection so a bad /api/show can never poison the next call.
_reset_litellm_client()


def generate_advisor_profile(
    role: str,
    demographics: dict,
    *,
    ollama_text_model: str,
    ollama_text_model_api_base: str | None = None,
    max_retries: int = _MAX_RETRIES,
) -> dict:
    """Generate education, experience, and traits from role via LLM.

    Returns: {"education": [...], "experience": [...], "traits": [...]}
    """
    gender = demographics.get("gender", "person")
    age = demographics.get("age", 40)

    logger.info("[Step B] START — generate_cv (model=%s)", ollama_text_model)
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

    base_kwargs: dict = {
        "model": ollama_text_model,
        "temperature": SETTINGS["step_b"]["temperature"],
        "max_tokens": SETTINGS["step_b"]["max_tokens"],
        "timeout": SETTINGS["timeout"],
    }
    if ollama_text_model_api_base:
        base_kwargs["api_base"] = ollama_text_model_api_base

    for attempt in range(1, max_retries + 1):
        try:
            response = litellm.completion(messages=messages, **base_kwargs)
            content = response.choices[0].message.content
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
            if "Transfer-Encoding" in str(exc):
                _reset_litellm_client()

    raise ValueError(
        f"Failed to generate advisor profile after {max_retries} attempts"
    )


# Backward-compat alias
_generate_advisor_profile = generate_advisor_profile
