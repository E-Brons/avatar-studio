"""Avatar studio — core pipeline logic.

Contains process_advisor, model resolution helpers, and re-exports for tests
and the API layer (as_api.py).
"""

import logging
from pathlib import Path

import requests
import yaml

from config.config import SETTINGS, _slug
from pipeline.persona.generator import pick_demographics
from pipeline.render.expression_resolver import EXPRESSION_IDS
from pipeline.render.programmatic.svg_generator import create_programmatic_avatar
from pipeline.render.renderer import DEFAULT_SIZE, create_abbreviation_avatar, create_face_avatar

logger = logging.getLogger(__name__)

_DEFAULT_TEXT_MODEL: str = SETTINGS["default_text_gen_model"]
_DEFAULT_IMAGE_MODEL: str = SETTINGS["default_image_gen_model"]
_DEFAULT_VISUAL_DESC_MODEL: str = SETTINGS["default_visual_desc_model"]
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

_GENDERS = ["male", "female", "non-binary"]


def _ollama_available_models(gateway_url: str = "http://127.0.0.1:4096") -> set[str]:
    """Return the set of model names currently available in Ollama."""
    try:
        resp = requests.get(f"{gateway_url}/api/tags", timeout=5)
        resp.raise_for_status()
        return {m["name"] for m in resp.json().get("models", [])}
    except Exception:
        return set()


def _resolve_default_model(
    preferred: str,
    available: set[str],
    label: str,
) -> str | None:
    """Return the preferred model name if it exists in Ollama, else None."""
    preferred = preferred.removeprefix("ollama/")
    if preferred in available:
        return preferred
    bare = preferred.split(":")[0]
    for name in available:
        if name == bare or name.startswith(bare + ":"):
            return name
    return None


def _build_demographics_for_gender(gender: str, seed: int | None = None) -> dict:
    """Return a demographics dict with the given gender forced."""
    demo = pick_demographics(seed=seed)
    demo["gender"] = gender
    return demo


def process_advisor(
    advisor_path: Path,
    out_dir: Path,
    size: int = DEFAULT_SIZE,
    expressions: list[str] | None = None,
    *,
    gateway_url: str = "http://127.0.0.1:4096",
    width: int = 128,
    height: int = 128,
    seed: int | None = None,
) -> None:
    """Generate avatars for one advisor and update its YAML in-place."""
    with open(advisor_path) as f:
        advisor = yaml.safe_load(f)

    name = advisor["name"]
    slug = _slug(name)
    expressions = expressions or EXPRESSION_IDS

    if "neutral" not in expressions:
        expressions = ["neutral", *expressions]

    expr_map, demographics = create_face_avatar(
        advisor,
        expressions,
        out_dir,
        slug,
        gateway_url=gateway_url,
        width=width,
        height=height,
        seed=seed,
    )

    abbr_filename = f"{slug}-abbreviation.png"
    abbr_path = out_dir / abbr_filename
    create_abbreviation_avatar(
        name,
        abbr_path,
        size=size,
        color=demographics.get("bg_color"),
    )
    print(f"  [abbreviation] {abbr_path}")

    pa_filename = f"{slug}-programmatic-avatar.svg"
    pa_path = out_dir / pa_filename
    try:
        create_programmatic_avatar(name, pa_path, size=size, demographics=demographics)
        print(f"  [programmatic-avatar] {pa_path}")
    except Exception as exc:
        logger.warning("[Step D] programmatic-avatar failed (non-fatal): %s", exc)
        pa_filename = None

    picture: dict = {
        "abbreviation": str(abbr_filename),
        "expressions": expr_map,
    }
    if pa_filename:
        picture["programmatic_avatar"] = str(pa_filename)
    advisor["picture"] = picture

    with open(advisor_path, "w") as f:
        yaml.dump(advisor, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print(f"  Updated {advisor_path}")

