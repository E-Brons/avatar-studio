"""Avatar studio — core pipeline logic.

Contains process_advisor, model resolution helpers, and re-exports for tests
and the API layer (as_api.py).
"""

import logging
from pathlib import Path

import requests
import yaml

from avatar_studio.config.config import SETTINGS, _slug
from avatar_studio.pipeline.step_a_randomise_person import pick_demographics as _pick_demographics
from avatar_studio.pipeline.step_d_make_abbreviation import (
    DEFAULT_SIZE,
    create_abbreviation_avatar,
)
from avatar_studio.pipeline.step_ef_generate_image import (
    EXPRESSION_IDS,
    create_face_avatar,
)

logger = logging.getLogger(__name__)

_DEFAULT_TEXT_MODEL: str = SETTINGS["default_text_gen_model"]
_DEFAULT_IMAGE_MODEL: str = SETTINGS["default_image_gen_model"]
_DEFAULT_VISUAL_DESC_MODEL: str = SETTINGS["default_visual_desc_model"]


def _ollama_available_models(ollama_url: str = "http://127.0.0.1:4096") -> set[str]:
    """Return the set of model names currently available in Ollama."""
    try:
        resp = requests.get(f"{ollama_url}/api/tags", timeout=5)
        resp.raise_for_status()
        return {m["name"] for m in resp.json().get("models", [])}
    except Exception:
        return set()


def _resolve_default_model(
    preferred: str,
    available: set[str],
    label: str,
) -> str | None:
    """Return the preferred model name if it exists in Ollama, else None.

    Strips the ``ollama/`` prefix before comparing against Ollama API names.
    """
    preferred = preferred.removeprefix("ollama/")
    if preferred in available:
        return preferred
    # Also try without :latest tag
    bare = preferred.split(":")[0]
    for name in available:
        if name == bare or name.startswith(bare + ":"):
            return name
    return None


def _load_expression_ids() -> list[str]:
    from avatar_studio.pipeline.step_ef_generate_image import _load_expression_ids as _lei

    return _lei()


_GENDERS = ["male", "female", "non-binary"]


def _build_demographics_for_gender(gender: str, seed: int | None = None) -> dict:
    """Return a demographics dict with the given gender forced."""
    demo = _pick_demographics(seed=seed)
    demo["gender"] = gender
    return demo


def process_advisor(
    advisor_path: Path,
    out_dir: Path,
    size: int = DEFAULT_SIZE,
    expressions: list[str] | None = None,
    *,
    ollama_url: str = "http://127.0.0.1:4096",
    ollama_image_model: str,
    width: int = 128,
    height: int = 128,
    ollama_text_model: str,
    ollama_text_model_api_base: str | None = None,
) -> None:
    """Generate avatars for one advisor and update its YAML in-place."""
    with open(advisor_path) as f:
        advisor = yaml.safe_load(f)

    name = advisor["name"]
    slug = _slug(name)
    expressions = expressions or EXPRESSION_IDS

    # Ensure "neutral" is always included (required as the portrait base).
    if "neutral" not in expressions:
        expressions = ["neutral", *expressions]

    # --- face expression avatars (two-stage: portrait → expressions) ---
    expr_map, demographics = create_face_avatar(
        advisor,
        expressions,
        out_dir,
        slug,
        ollama_url=ollama_url,
        ollama_image_model=ollama_image_model,
        width=width,
        height=height,
        ollama_text_model=ollama_text_model,
        ollama_text_model_api_base=ollama_text_model_api_base,
    )

    # --- abbreviation avatar (uses frame colors from demographics) ---
    abbr_filename = f"{slug}-abbreviation.png"
    abbr_path = out_dir / abbr_filename
    create_abbreviation_avatar(
        name,
        abbr_path,
        size=size,
        color=demographics.get("bg_color"),
    )
    print(f"  [abbreviation] {abbr_path}")

    # --- update advisor YAML in-place ---
    advisor["picture"] = {
        "abbreviation": str(abbr_filename),
        "expressions": expr_map,
    }

    with open(advisor_path, "w") as f:
        yaml.dump(advisor, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print(f"  Updated {advisor_path}")


# Re-exports for backward compatibility
from avatar_studio.pipeline.step_d_make_abbreviation import DEFAULT_SIZE  # noqa: E402
