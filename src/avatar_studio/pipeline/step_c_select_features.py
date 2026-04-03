"""Stage C — select presentation features via per-field LLM calls.

Also contains persona marshalling and sanitization utilities previously in
persona.py (which is now a compatibility shim).
"""

import logging
import re
from pathlib import Path

import yaml

from avatar_studio.config.config import SETTINGS
from avatar_studio.config.gateway import GatewayClient
from avatar_studio.pipeline.step_a_randomise_person import _DEFAULT_STYLE

logger = logging.getLogger(__name__)

_MAX_RETRIES: int = SETTINGS["max_retries"]

# Step C system prompt — inlined (was generate_features_system_prompt.yml).
_STEP_C_SYSTEM_PROMPT = (
    "you are: a graphics designer for professional avatar illustrations\n"
    "task: Given the following advisor profile, select EXACTLY ONE value\n"
    "consideration: Choose features that is consistent for the persona\n"
    "this person is professional yet approachable, wearing corporate-friendly dress-code and hairstyle\n"
)

_NONE_PATTERNS = re.compile(r"^(none|n/a|no|nothing|null|empty|-|—)$", re.IGNORECASE)

# Fields that are simple pick-one-from-list — LLM-selected presentation only.
# Phenotype shape fields (EYE_SHAPE, BROWS_STYLE, NOSE_SHAPE, CHIN_SHAPE, CHEEKS_SHAPE)
# are now randomized in Step A and pre-seeded from demographics, not LLM-selected.
_SIMPLE_FIELDS = [
    "HAIR_STYLE",
]


def _load_required_feature_keys() -> list[str]:
    """Return the keys Step C LLM must produce (from step_c schema in settings)."""
    return list(SETTINGS.get("step_c", {}).get("schema", {}).keys())


_REQUIRED_FEATURE_KEYS = _load_required_feature_keys()


def _filter_none_values(d: dict) -> dict:
    """Remove entries whose value looks like 'none' / 'n/a' / empty."""
    return {
        k: v
        for k, v in d.items()
        if not (isinstance(v, str) and _NONE_PATTERNS.match(v.strip()))
    }


def _load_user_prompt_options(gender: str | None = None, *, hard_type: bool = False) -> dict:
    """Return gender-filtered option lists for Step C LLM fields.

    Default (hard_type=False) — nested male/female/neutral dicts are flattened:
      male       → male + neutral
      female     → female + neutral
      non-binary / None → all three buckets

    Hard-typed (hard_type=True) — strict single-bucket selection:
      male       → male only
      female     → female only
      non-binary / None → neutral only

    Plain lists are returned as-is.
    """
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
    """Build a short advisor profile string for per-field prompts."""
    role = advisor.get("role", "Advisor")
    traits = advisor.get("traits", [])
    traits_str = ", ".join(traits) if traits else "professional"
    return (
        f"Gender: {demographics['gender']}\n"
        f"Age: {demographics['age']}\n"
        f"Role: {role}, Traits: {traits_str}"
    )


def _build_feature_prompt(demographics: dict, advisor: dict) -> tuple[str, str]:
    """Build the Step C prompt for a per-field LLM call.

    Returns (system_message, user_message).
    """
    system_msg = _STEP_C_SYSTEM_PROMPT
    profile = _format_profile(demographics, advisor)
    user_msg = f"Advisor profile:\n{profile}"
    return system_msg, user_msg


def _parse_feature_response(text: str) -> dict:
    """Extract a YAML block from the LLM response text.

    Strips optional code fences, parses the YAML, and validates that all 12
    required keys are present.  Returns a dict with string values.
    """
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
    """Select a single feature field via a small LLM call.

    Retries up to *max_retries* times on empty or unparseable responses.
    """
    # Build persona context from previously selected fields so each pick
    # is consistent with the emerging character (avoids "Mr Potato" effect).
    context = ""
    if selected_so_far:
        persona = _marshal_avatar_persona(demographics, advisor, selected_so_far)
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
            f"{profile}{context}\n"
            f"Pick ONE {key} from: {opts_str}\n"
            f"Reply with ONLY the value."
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
            logger.warning(
                "Field %s attempt %d/%d: empty response", key, attempt, max_retries
            )
            continue

        content = content.strip()

        # --- NAME: free text ---
        if key == "NAME":
            # Valid name: exactly two words, each starting with a capital letter,
            # no special/markdown characters.  Retry on contamination or bad format.
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
                cleaned = re.sub(
                    r"^```(?:ya?ml)?\s*\n?", "", content, flags=re.MULTILINE
                )
                cleaned = re.sub(r"\n?```\s*$", "", cleaned.strip())
                if cleaned.lower() == "none":
                    return {}
                # Truncate at first blank line or non-YAML-looking line
                # to discard trailing garbage the model may append.
                yaml_lines = []
                for line in cleaned.split("\n"):
                    stripped = line.strip()
                    if not stripped:
                        break
                    # Stop at lines that don't look like YAML key:value or list items
                    if not re.match(r"^-?\s*[\w\s\-]+:", line) and not line.startswith(
                        " "
                    ):
                        break
                    yaml_lines.append(line)
                cleaned = "\n".join(yaml_lines) if yaml_lines else cleaned
                parsed = yaml.safe_load(cleaned)

                # Flatten list of single-key dicts → dict
                def _flatten_list(lst):
                    merged = {}
                    for item in lst:
                        if isinstance(item, dict):
                            merged.update(item)
                    return merged

                if isinstance(parsed, list):
                    parsed = _flatten_list(parsed) or parsed

                # Unwrap field-name wrapper: model sometimes returns {"accessories": [...]}
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
                    # Reject contaminated responses: the LLM sometimes echoes back the
                    # full persona YAML (which is also a valid dict). Detect this by
                    # checking for known persona top-level keys, or nested dict values
                    # (clothing values must be hex strings; accessory values must be strings).
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

                    # Filter to valid option keys only.
                    # Normalize spaces, hyphens, and underscores so "button-down shirt"
                    # matches model output "button_down_shirt" etc.
                    def _norm(s: str) -> str:
                        return s.strip().lower().replace(" ", "_").replace("-", "_")

                    if options:
                        valid = {_norm(str(o)) for o in options}
                        parsed = {k: v for k, v in parsed.items() if _norm(k) in valid}

                    # Enforce count limits: max 4 clothing items, max 3 accessories
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
        # Strip system-prompt contamination that local models bleed into output.
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
            # Detect whether this is a color field by checking if the options
            # contain hex values.  Color fields (SKIN_TONE, HAIR_COLOR,
            # EYE_COLOR, BROWS_COLOR) use options only as palette examples —
            # the model may return any valid hex and that is acceptable.
            # Text fields (HAIR_STYLE, EYE_SHAPE, etc.) must match exactly.
            options_have_hex = any(
                re.search(r"#[0-9A-Fa-f]{6}", str(o)) for o in options
            )
            if options_have_hex:
                # Accept any response that contains at least one valid hex.
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
                # Text field: must match one of the listed options.
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
    """Call a text LLM per-field to select visual features for the avatar.

    Each feature is requested in its own small LLM call so local models
    can handle it reliably.  A warmup call health-checks the gateway first.

    If *session_dir* is provided, the assembled persona is written to
    ``session_dir/persona.yml`` for auditability.

    *hard_type_gender* — when True, gender-bucketed option lists are filtered
    to the strict gender bucket only (no neutral crossover).  Default is False.
    """
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

    # Simple pick-from-list fields
    for key in _SIMPLE_FIELDS:
        features[key] = _select_feature_field(
            key,
            profile,
            system_msg,
            options.get(key, []),
            features,
            demographics,
            advisor,
            **llm_kwargs,
        )
        logger.info("Selected %s: %s", key, features[key])

    # Structured dict fields
    features["CLOTHING"] = _select_feature_field(
        "CLOTHING",
        profile,
        system_msg,
        options.get("CLOTHING", []),
        features,
        demographics,
        advisor,
        **llm_kwargs,
    )
    logger.info("Selected CLOTHING: %s", features["CLOTHING"])

    features["ACCESSORIES"] = _select_feature_field(
        "ACCESSORIES",
        profile,
        system_msg,
        options.get("ACCESSORIES", []),
        features,
        demographics,
        advisor,
        **llm_kwargs,
    )
    logger.info("Selected ACCESSORIES: %s", features["ACCESSORIES"])

    if session_dir is not None:
        try:
            session_dir.mkdir(parents=True, exist_ok=True)
            persona = _build_avatar_charachter(advisor, demographics, features)
            with open(session_dir / "persona.yml", "w") as f:
                yaml.dump(
                    persona,
                    f,
                    default_flow_style=False,
                    sort_keys=False,
                    allow_unicode=True,
                )
            logger.info(
                "[Step C] DONE  — %d features selected, persona.yml written to %s",
                len(features or {}),
                session_dir,
            )
        except Exception as exc:
            logger.warning(
                "[Step C] Failed to write persona.yml to %s: %s", session_dir, exc
            )

    return features


# Backward-compat alias
_select_features = select_features


# ---------------------------------------------------------------------------
# Persona marshalling and sanitization (moved from persona.py)
# ---------------------------------------------------------------------------

_INJECTION_MARKERS = ("###", "### Instruction", "### System:", "```")

# Persona color metadata — loaded from settings (persona_hex_fields / persona_dict_fields).
_HEX_FIELD_NAMES: dict[str, tuple[str, ...]] = {}
_DICT_PASSTHROUGH_KEYS: set[str] = set()


def _load_persona_color_metadata() -> tuple[dict[str, tuple[str, ...]], set[str]]:
    """Load hex-field names and dict-passthrough keys from avatar_studio_settings.json."""
    hex_field_names = {
        k.upper(): tuple(v) for k, v in SETTINGS.get("persona_hex_fields", {}).items()
    }
    dict_passthrough_keys = {k.upper() for k in SETTINGS.get("persona_dict_fields", [])}
    return hex_field_names, dict_passthrough_keys


_HEX_FIELD_NAMES, _DICT_PASSTHROUGH_KEYS = _load_persona_color_metadata()


def _parse_color_value(key: str, raw_value: str) -> str | dict:
    """Parse a raw feature value into a structured color dict or plain string.

    Multi-hex colors (e.g. HAIR_COLOR: '#3B2314 #261508') are split into
    named hex fields per the persona schema.  Single-hex values are returned
    as plain strings.
    """
    hexes = re.findall(r"#[0-9A-Fa-f]{6}", raw_value)
    if not hexes:
        return raw_value

    field_names = _HEX_FIELD_NAMES.get(key)
    if field_names and len(hexes) >= len(field_names):
        result: dict = {}
        for fname, hval in zip(field_names, hexes):
            result[fname] = hval
        return result

    # Single hex — return as plain string
    return hexes[0]


def _marshal_avatar_persona(
    demographics: dict, advisor: dict, features: dict | None
) -> dict:
    """Combine demographics + advisor + features into the avatar_persona dict.

    This is the single structured representation used by both the image prompt
    (YAML-dumped) and the UI panel.
    """
    name = demographics.get("name") or (features.get("NAME", "") if features else "")

    persona: dict = {
        "personal": {
            "name": name,
            "gender": demographics["gender"],
            "age": demographics["age"],
        },
        "style": {
            "bg_color": demographics.get("bg_color", "#4A90D9"),
            "fg_color": demographics.get("fg_color", "#FFFFFF"),
        },
        "advisor": {
            "role": advisor.get("role", "Advisor"),
            "education": advisor.get("education", []),
            "experience": advisor.get("experience", []),
            "traits": advisor.get("traits", []),
        },
    }

    if not features:
        persona["appearance"] = {}
        return persona

    appearance: dict = {}
    for key, value in features.items():
        if key == "NAME":
            continue
        snake_key = key.lower()
        if key in _DICT_PASSTHROUGH_KEYS:
            # Already a dict from LLM — passthrough
            appearance[snake_key] = value
        elif key in _HEX_FIELD_NAMES:
            # Multi-hex color — parse into named hex fields
            appearance[snake_key] = (
                _parse_color_value(key, value) if isinstance(value, str) else value
            )
        else:
            # Plain string (including single-hex colors) — passthrough
            appearance[snake_key] = value
    persona["appearance"] = appearance

    return persona


def build_avatar_charachter(
    advisor: dict,
    demographics: dict,
    features: dict | None = None,
) -> dict:
    """Build a complete avatar charachter definition.

    This avatar charachter is the single charachter builder used
    by both Step C (portrait) and Step D (expression variants).
    to create visualisation
    """
    role = advisor.get("role", "Advisor")
    traits = advisor.get("traits", [])
    traits_str = ", ".join(traits) if traits else "professional"

    avatar_persona = _marshal_avatar_persona(demographics, advisor, features)

    return dict(
        gender=demographics["gender"],
        age=demographics["age"],
        role=role,
        traits_str=traits_str,
        avatar_persona=avatar_persona,
    )


# Backward-compat alias
_build_avatar_charachter = build_avatar_charachter


def _sanitize_str(v: str, max_chars: int = 100) -> str:
    """Strip prompt-injection contamination and truncate a string value."""
    for marker in _INJECTION_MARKERS:
        if marker in v:
            v = v.split(marker)[0].strip()
    v = v.splitlines()[0].strip()
    return v[:max_chars]


def _visual_only_persona(persona: dict) -> dict:
    """Return a stripped persona with only visual cues for the image model.

    Removes text-heavy fields (education, experience, traits, name) that
    the image model may render as literal text in the generated image.
    Sanitizes all string values to strip any system-prompt contamination
    that leaked through from the text LLM.
    """
    personal = persona.get("personal", {})
    advisor = persona.get("advisor", {})
    appearance = persona.get("appearance", {})

    # personal: visual descriptors only — no name, no frame colors
    visual_personal = {}
    for k in ("gender", "age", "appearance_id"):
        v = personal.get(k)
        if v is not None:
            visual_personal[k] = _sanitize_str(str(v)) if isinstance(v, str) else v

    # advisor: role only — no education / experience / traits
    visual_advisor = {"role": _sanitize_str(str(advisor.get("role", "professional")))}

    # appearance: sanitize every string value; recurse into color dicts.
    # eye_shape is excluded — it is a rendering directive that contradicts
    # stylized system prompts (e.g. "dot eyes" vs "almond eyes").
    # Style owns rendering; persona owns identity.
    _APPEARANCE_EXCLUDE = {"eye_shape"}
    visual_appearance: dict = {}
    for k, v in appearance.items():
        if k in _APPEARANCE_EXCLUDE:
            continue
        if isinstance(v, str):
            visual_appearance[k] = _sanitize_str(v)
        elif isinstance(v, dict):
            visual_appearance[k] = {
                sk: _sanitize_str(sv) if isinstance(sv, str) else sv
                for sk, sv in v.items()
            }

    return {
        "personal": visual_personal,
        "advisor": visual_advisor,
        "appearance": visual_appearance,
    }
