"""LLM-based aggregator — per-field feature selection."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml

from config.config import SETTINGS
from config.gateway import GatewayClient
from pipeline.persona.marshal import marshal_avatar_persona

logger = logging.getLogger(__name__)

_MAX_RETRIES: int = SETTINGS["max_retries"]


# ---------------------------------------------------------------------------
# Feature selection
# ---------------------------------------------------------------------------

# System prompt — inlined (was generate_features_system_prompt.yml).
_STEP_C_SYSTEM_PROMPT = (
    "you are: a graphics designer for professional avatar illustrations\n"
    "task: Given the following advisor profile, select EXACTLY ONE value\n"
    "consideration: Choose features that is consistent for the persona\n"
    "this person is professional yet approachable, wearing corporate-friendly dress-code and hairstyle\n"
)

_NONE_PATTERNS = re.compile(r"^(none|n/a|no|nothing|null|empty|-|—)$", re.IGNORECASE)


def _load_required_feature_keys() -> list[str]:
    """Return the keys the feature selection LLM must produce (from schema in settings)."""
    return list(SETTINGS.get("feature_selection", {}).get("schema", {}).keys())


_REQUIRED_FEATURE_KEYS = _load_required_feature_keys()


def _filter_none_values(d: dict) -> dict:
    """Remove entries whose value looks like 'none' / 'n/a' / empty."""
    return {
        k: v for k, v in d.items() if not (isinstance(v, str) and _NONE_PATTERNS.match(v.strip()))
    }


def _load_user_prompt_options(gender: str | None = None, *, hard_type: bool = False) -> dict:
    """Return gender-filtered option lists for feature selection LLM fields."""

    def _flatten(opt_src: dict | list) -> list:
        if isinstance(opt_src, list):
            return opt_src
        if not isinstance(opt_src, dict):
            return []
        if hard_type:
            if gender == "male":
                buckets = ["male"]
            elif gender == "female":
                buckets = ["female"]
            else:
                buckets = ["neutral"]
        else:
            if gender == "male":
                buckets = ["male", "neutral"]
            elif gender == "female":
                buckets = ["female", "neutral"]
            else:
                buckets = ["male", "female", "neutral"]
        result: list = []
        for b in buckets:
            result.extend(opt_src.get(b, []))
        return result

    return {
        "HAIR_STYLE": _flatten(SETTINGS.get("hair_styles", [])),
        "CLOTHING": _flatten(SETTINGS.get("clothing_options", [])),
        "ACCESSORIES": _flatten(SETTINGS.get("accessories_options", [])),
    }


def _format_profile(demographics: dict, advisor: dict) -> str:
    """Build a short persona profile string for per-field prompts."""
    traits = advisor.get("traits", [])
    traits_str = ", ".join(traits) if traits else "professional"
    return f"Gender: {demographics['gender']}\nAge: {demographics['age']}\nTraits: {traits_str}"


def _build_feature_prompt(demographics: dict, advisor: dict) -> tuple[str, str]:
    """Build the feature selection prompt for a per-field LLM call.

    Returns (system_message, user_message).
    """
    system_msg = _STEP_C_SYSTEM_PROMPT
    profile = _format_profile(demographics, advisor)
    user_msg = f"Advisor profile:\n{profile}"
    return system_msg, user_msg


def _parse_feature_response(text: str) -> dict:
    """Extract a YAML block from the LLM response text."""
    # Strip code fences if present
    cleaned = re.sub(r"^```(?:ya?ml)?\s*\n?", "", text.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"\n?```\s*$", "", cleaned.strip())

    # Strip markdown bold markers that LLMs sometimes wrap keys in (**KEY:** → KEY:)
    cleaned = re.sub(r"\*\*([A-Z_]+):\*\*", r"\1:", cleaned)
    cleaned = re.sub(r"\*\*([A-Z_]+)\*\*:", r"\1:", cleaned)

    parsed = yaml.safe_load(cleaned)
    if not isinstance(parsed, dict):
        raise ValueError(f"Expected YAML dict, got {type(parsed).__name__}")

    missing = [k for k in _REQUIRED_FEATURE_KEYS if k not in parsed]
    if missing:
        raise ValueError(f"Missing required feature keys: {missing}")

    # Normalize values — most are strings, but CLOTHING and ACCESSORIES may be dicts
    result = {}
    for k in _REQUIRED_FEATURE_KEYS:
        if k in parsed:
            result[k] = parsed[k] if isinstance(parsed[k], dict) else str(parsed[k])
    return result


def _select_feature_field(
    key: str,
    profile: str,
    system_msg: str,
    options: list | None,
    selected_so_far: dict,
    demographics: dict,
    advisor: dict,
    *,
    gateway_url: str = "http://127.0.0.1:4096",
    max_retries: int = _MAX_RETRIES,
) -> str | dict:
    """Select a single feature field via a small LLM call."""
    # Build persona context from previously selected fields so each pick
    # is consistent with the emerging character.
    context = ""
    if selected_so_far:
        persona = marshal_avatar_persona(demographics, advisor, selected_so_far)
        persona_yaml = yaml.dump(
            persona,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )
        context = f"\nCurrent persona so far:\n{persona_yaml}"

    # Build the user message per field type
    if key == "NAME":
        user_content = (
            f"{profile}{context}\n"
            f"Generate a full name (first + last) for this advisor. "
            f"Reply with ONLY the name."
        )
    elif key == "CLOTHING":
        opts_str = ", ".join(str(o) for o in options) if options else ""
        user_content = (
            f"{profile}{context}\n"
            f"Pick 1 to 4 clothing items from: {opts_str}\n"
            f"Reply as YAML only — use the actual item name as the key and a hex color as the value.\n"
            f'Example:\n  blazer: "#3C3C3C"\n  shirt: "#A8C4E0"'
        )
    elif key == "ACCESSORIES":
        opts_str = ", ".join(str(o) for o in options) if options else ""
        user_content = (
            f"{profile}{context}\n"
            f"Pick 0 to 3 accessories from: {opts_str}\n"
            f"Reply as YAML only — use the actual accessory name as the key and a short visual description as the value.\n"
            f"Example:\n  glasses: thin-frame rectangular\n  pendant necklace: small gold chain\n"
            f"If none, reply: none"
        )
    else:
        # Simple pick-one field
        opts_str = ", ".join(str(o) for o in options) if options else ""
        user_content = (
            f"{profile}{context}\nPick ONE {key} from: {opts_str}\nReply with ONLY the value."
        )

    messages: list[dict] = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_content},
    ]

    client = GatewayClient(gateway_url)

    for attempt in range(1, max_retries + 1):
        try:
            content = client.text_gen(messages)
        except Exception as exc:
            if attempt == max_retries:
                raise
            logger.warning(
                "Field %s attempt %d/%d connection error: %s",
                key,
                attempt,
                max_retries,
                exc,
            )
            continue
        if not content or not content.strip():
            logger.warning("Field %s attempt %d/%d: empty response", key, attempt, max_retries)
            continue

        content = content.strip()

        # --- NAME: free text ---
        if key == "NAME":
            for line in content.splitlines():
                line = line.strip().strip("\"'")
                if not line or len(line) >= 60:
                    continue
                if any(c in line for c in ("#", "```", "###", "\\")):
                    continue
                words = line.split()
                if len(words) == 2 and words[0][0].isupper() and words[1][0].isupper():
                    return line
            logger.warning(
                "Field NAME attempt %d/%d: no valid 'First Last' name found — retrying",
                attempt,
                max_retries,
            )
            continue

        # --- CLOTHING / ACCESSORIES: parse as YAML dict ---
        if key in ("CLOTHING", "ACCESSORIES"):
            try:
                cleaned = re.sub(r"^```(?:ya?ml)?\s*\n?", "", content, flags=re.MULTILINE)
                cleaned = re.sub(r"\n?```\s*$", "", cleaned.strip())
                if cleaned.lower() == "none":
                    return {}
                # Truncate at first blank line or non-YAML-looking line
                yaml_lines = []
                for line in cleaned.split("\n"):
                    stripped = line.strip()
                    if not stripped:
                        break
                    if not re.match(r"^-?\s*[\w\s\-]+:", line) and not line.startswith(" "):
                        break
                    yaml_lines.append(line)
                cleaned = "\n".join(yaml_lines) if yaml_lines else cleaned
                parsed = yaml.safe_load(cleaned)

                def _flatten_list(lst):
                    merged = {}
                    for item in lst:
                        if isinstance(item, dict):
                            merged.update(item)
                    return merged

                if isinstance(parsed, list):
                    parsed = _flatten_list(parsed) or parsed

                # Unwrap field-name wrapper
                if isinstance(parsed, dict) and len(parsed) == 1:
                    only_key = next(iter(parsed))
                    if only_key.lower() == key.lower():
                        inner = parsed[only_key]
                        if isinstance(inner, list):
                            parsed = _flatten_list(inner)
                        elif isinstance(inner, dict):
                            parsed = inner
                        else:
                            parsed = {}

                if isinstance(parsed, dict):
                    _PERSONA_KEYS = {
                        "advisor_persona",
                        "personal",
                        "advisor",
                        "appearance",
                    }
                    if _PERSONA_KEYS.intersection(parsed.keys()):
                        logger.warning(
                            "Field %s attempt %d/%d: response looks like echoed persona — retrying",
                            key,
                            attempt,
                            max_retries,
                        )
                        continue
                    if key == "CLOTHING":
                        bad = [v for v in parsed.values() if not isinstance(v, str)]
                    else:  # ACCESSORIES
                        bad = [v for v in parsed.values() if isinstance(v, dict)]
                    if bad:
                        logger.warning(
                            "Field %s attempt %d/%d: unexpected value types — retrying",
                            key,
                            attempt,
                            max_retries,
                        )
                        continue

                    def _norm(s: str) -> str:
                        return s.strip().lower().replace(" ", "_").replace("-", "_")

                    if options:
                        valid = {_norm(str(o)) for o in options}
                        parsed = {k: v for k, v in parsed.items() if _norm(k) in valid}

                    max_count = 4 if key == "CLOTHING" else 3
                    if len(parsed) > max_count:
                        parsed = dict(list(parsed.items())[:max_count])

                    return _filter_none_values(parsed)
                logger.warning(
                    "Field %s attempt %d/%d: expected dict, got %s",
                    key,
                    attempt,
                    max_retries,
                    type(parsed).__name__,
                )
            except Exception as exc:
                logger.warning(
                    "Field %s attempt %d/%d: YAML parse failed: %s",
                    key,
                    attempt,
                    max_retries,
                    exc,
                )
            continue

        # --- Simple field: strip quotes, strip prompt injection, validate ---
        value = content.strip("\"'")
        for marker in ("###", "\n###", "### Instruction", "### System:", "```"):
            if marker in value:
                value = value.split(marker)[0].strip()

        lines = value.splitlines()
        if not lines:
            logger.warning(
                "Field %s attempt %d/%d: empty after sanitize — retrying",
                key,
                attempt,
                max_retries,
            )
            continue
        value = lines[0].strip()

        if not value:
            logger.warning(
                "Field %s attempt %d/%d: empty after sanitize — retrying",
                key,
                attempt,
                max_retries,
            )
            continue

        if options:
            options_have_hex = any(re.search(r"#[0-9A-Fa-f]{6}", str(o)) for o in options)
            if options_have_hex:
                if re.search(r"#[0-9A-Fa-f]{6}", value):
                    return value
                logger.warning(
                    "Field %s attempt %d/%d: '%s' has no valid hex — retrying",
                    key,
                    attempt,
                    max_retries,
                    value,
                )
                continue
            else:
                opts_lower = {str(o).strip().lower(): str(o).strip() for o in options}
                if value.lower() in opts_lower:
                    return opts_lower[value.lower()]
                logger.warning(
                    "Field %s attempt %d/%d: '%s' not in options — retrying",
                    key,
                    attempt,
                    max_retries,
                    value,
                )
                continue

        # No options constraint — return as-is.
        return value

    raise ValueError(f"Failed to select {key} after {max_retries} attempts")


def _parse_dict_field(
    raw: object,
    key: str,
    options: list,
    *,
    max_items: int,
) -> dict | None:
    """Parse a YAML dict field (CLOTHING or ACCESSORIES) from a batch response.

    Returns a dict on success, None if the value is structurally invalid.
    """
    if raw is None:
        return {}
    if isinstance(raw, str) and _NONE_PATTERNS.match(raw.strip()):
        return {}
    if not isinstance(raw, dict):
        return None

    _PERSONA_KEYS = {"advisor_persona", "personal", "advisor", "appearance", "personality"}
    if _PERSONA_KEYS.intersection(raw.keys()):
        return None  # echoed persona — reject

    if key == "CLOTHING":
        if any(not isinstance(v, str) for v in raw.values()):
            return None

    def _norm(s: str) -> str:
        return s.strip().lower().replace(" ", "_").replace("-", "_")

    if options:
        valid = {_norm(str(o)) for o in options}
        raw = {k: v for k, v in raw.items() if _norm(k) in valid}

    if len(raw) > max_items:
        raw = dict(list(raw.items())[:max_items])

    return raw


def _select_appearance_batch(
    profile: str,
    system_msg: str,
    options: dict,
    context_features: dict,
    demographics: dict,
    advisor: dict,
    *,
    gateway_url: str = "http://127.0.0.1:4096",
    max_retries: int = _MAX_RETRIES,
) -> dict:
    """Select HAIR_STYLE, CLOTHING, and ACCESSORIES in a single LLM call."""
    hair_opts = options.get("HAIR_STYLE", [])
    clothing_opts = options.get("CLOTHING", [])
    accessories_opts = options.get("ACCESSORIES", [])

    context = ""
    if context_features:
        persona = marshal_avatar_persona(demographics, advisor, context_features)
        persona_yaml = yaml.dump(
            persona, default_flow_style=False, sort_keys=False, allow_unicode=True
        )
        context = f"\nCurrent persona:\n{persona_yaml}"

    user_content = (
        f"{profile}{context}\n\n"
        f"Select appearance attributes. Reply as YAML only — no extra text.\n\n"
        f"HAIR_STYLE: pick ONE from: {', '.join(str(o) for o in hair_opts)}\n"
        f"CLOTHING: pick 1-4 items from: {', '.join(str(o) for o in clothing_opts)}\n"
        f"  (key = item name, value = hex color #RRGGBB)\n"
        f"ACCESSORIES: pick 0-3 items from: {', '.join(str(o) for o in accessories_opts)}\n"
        f"  (key = item name, value = brief description — or write the word 'none')\n\n"
        f"Example:\n"
        f"HAIR_STYLE: bob cut\n"
        f"CLOTHING:\n"
        f'  blazer: "#3C3C3C"\n'
        f'  shirt: "#A8C4E0"\n'
        f"ACCESSORIES:\n"
        f"  glasses: thin-frame rectangular\n"
    )

    messages: list[dict] = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_content},
    ]

    client = GatewayClient(gateway_url)

    for attempt in range(1, max_retries + 1):
        try:
            content = client.text_gen(messages)
        except Exception as exc:
            if attempt == max_retries:
                raise
            logger.warning("Appearance batch attempt %d/%d error: %s", attempt, max_retries, exc)
            continue

        if not content or not content.strip():
            logger.warning("Appearance batch attempt %d/%d: empty response", attempt, max_retries)
            continue

        try:
            cleaned = re.sub(r"^```(?:ya?ml)?\s*\n?", "", content.strip(), flags=re.MULTILINE)
            cleaned = re.sub(r"\n?```\s*$", "", cleaned.strip())
            parsed = yaml.safe_load(cleaned)

            if not isinstance(parsed, dict):
                logger.warning(
                    "Appearance batch attempt %d/%d: expected dict, got %s",
                    attempt,
                    max_retries,
                    type(parsed).__name__,
                )
                continue

            # --- HAIR_STYLE ---
            hair_raw = parsed.get("HAIR_STYLE") or parsed.get("hair_style", "")
            hair = str(hair_raw).strip()
            if hair_opts:
                opts_lower = {str(o).strip().lower(): str(o).strip() for o in hair_opts}
                if hair.lower() not in opts_lower:
                    logger.warning(
                        "Appearance batch attempt %d/%d: HAIR_STYLE %r not in options",
                        attempt,
                        max_retries,
                        hair,
                    )
                    continue
                hair = opts_lower[hair.lower()]

            # --- CLOTHING ---
            clothing = _parse_dict_field(
                parsed.get("CLOTHING") or parsed.get("clothing"),
                "CLOTHING",
                clothing_opts,
                max_items=4,
            )
            if clothing is None:
                logger.warning(
                    "Appearance batch attempt %d/%d: CLOTHING invalid", attempt, max_retries
                )
                continue

            # --- ACCESSORIES ---
            accessories = _parse_dict_field(
                parsed.get("ACCESSORIES") or parsed.get("accessories"),
                "ACCESSORIES",
                accessories_opts,
                max_items=3,
            )
            if accessories is None:
                logger.warning(
                    "Appearance batch attempt %d/%d: ACCESSORIES invalid", attempt, max_retries
                )
                continue

            logger.info(
                "Appearance batch OK — HAIR_STYLE=%r CLOTHING=%r ACCESSORIES=%r",
                hair,
                clothing,
                accessories,
            )
            return {
                "HAIR_STYLE": hair,
                "CLOTHING": _filter_none_values(clothing),
                "ACCESSORIES": _filter_none_values(accessories),
            }

        except Exception as exc:
            logger.warning(
                "Appearance batch attempt %d/%d: parse error: %s", attempt, max_retries, exc
            )
            continue

    raise ValueError(f"Failed to select appearance after {max_retries} attempts")


def _warmup_model(
    *,
    gateway_url: str = "http://127.0.0.1:4096",
) -> None:
    """Send a trivial request to health-check the gateway."""
    client = GatewayClient(gateway_url)
    try:
        client.text_gen([{"role": "user", "content": "hi"}], max_retries=1, timeout=10)
        logger.info("Gateway warmup complete: %s", gateway_url)
    except Exception as exc:
        logger.warning("Gateway warmup failed (continuing anyway): %s", exc)


def select_features(
    demographics: dict,
    advisor: dict,
    *,
    gateway_url: str = "http://127.0.0.1:4096",
    max_retries: int = _MAX_RETRIES,
    session_dir: Path | None = None,
    hard_type_gender: bool = False,
) -> dict:
    """Call a text LLM per-field to select visual features for the avatar."""
    system_msg, _ = _build_feature_prompt(demographics, advisor)
    profile = _format_profile(demographics, advisor)
    options = _load_user_prompt_options(demographics.get("gender"), hard_type=hard_type_gender)

    llm_kwargs: dict = {
        "gateway_url": gateway_url,
        "max_retries": max_retries,
    }

    # Warmup: health-check the gateway with a trivial request.
    _warmup_model(gateway_url=gateway_url)

    features: dict = {}

    # Seed name and PHENO fields from §A demographics — no LLM needed.
    features["NAME"] = demographics.get("name", "")
    for key in (
        "SKIN_TONE",
        "HAIR_COLOR",
        "EYE_COLOR",
        "BROWS_COLOR",
        "EYE_SHAPE",
        "BROWS_STYLE",
        "NOSE_SHAPE",
        "CHIN_SHAPE",
        "CHEEKS_SHAPE",
    ):
        if key in demographics:
            features[key] = demographics[key]
            logger.info("Pre-seeded from §A — %s: %s", key, demographics[key])

    # Batch: HAIR_STYLE + CLOTHING + ACCESSORIES in a single LLM call.
    appearance = _select_appearance_batch(
        profile,
        system_msg,
        options,
        features,
        demographics,
        advisor,
        **llm_kwargs,
    )
    features.update(appearance)
    logger.info(
        "Selected appearance batch — HAIR_STYLE=%r CLOTHING=%r ACCESSORIES=%r",
        features.get("HAIR_STYLE"),
        features.get("CLOTHING"),
        features.get("ACCESSORIES"),
    )

    if session_dir is not None:
        try:
            session_dir.mkdir(parents=True, exist_ok=True)
            persona = marshal_avatar_persona(demographics, advisor, features)
            with open(session_dir / "persona.yml", "w") as f:
                yaml.dump(
                    persona,
                    f,
                    default_flow_style=False,
                    sort_keys=False,
                    allow_unicode=True,
                )
            logger.info(
                "DONE  — %d features selected, persona.yml written to %s",
                len(features or {}),
                session_dir,
            )
        except Exception as exc:
            logger.warning("Failed to write persona.yml to %s: %s", session_dir, exc)

    return features


# ---------------------------------------------------------------------------
# from_llm — single-attribute LLM selection
# ---------------------------------------------------------------------------


def from_llm(
    attr: str,
    options: list | None,
    resolved: dict,
    *,
    gateway_url: str = "http://127.0.0.1:4096",
) -> str | dict | None:
    """Select a single feature attribute via LLM.

    Returns None on failure (caller should fall back or skip).
    """
    demographics = {k: resolved[k] for k in ("gender", "age") if k in resolved}
    advisor = {
        "traits": resolved.get("traits", []),
    }
    profile = _format_profile(demographics, advisor)

    try:
        return _select_feature_field(
            attr,
            profile,
            _STEP_C_SYSTEM_PROMPT,
            options,
            resolved,
            demographics,
            advisor,
            gateway_url=gateway_url,
        )
    except Exception as exc:
        logger.warning("aggregator_llm.from_llm: %r failed: %s", attr, exc)
        return None
