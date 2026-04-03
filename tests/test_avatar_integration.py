"""Integration tests — full pipeline via LLM Gateway.

Runs the complete A→E avatar pipeline against the live gateway at
http://127.0.0.1:4096 and verifies the outputs are structurally valid.

Skips automatically if the gateway is unreachable.
"""
from __future__ import annotations

import base64
import tempfile
from pathlib import Path

import pytest
import yaml

from avatar_studio.pipeline.step_a_randomise_person import pick_demographics
from avatar_studio.pipeline.step_b_generate_cv import generate_advisor_profile
from avatar_studio.pipeline.step_c_select_features import build_avatar_charachter, select_features
from avatar_studio.pipeline.step_d_make_abbreviation import apply_circle_frame
from avatar_studio.pipeline.step_ef_generate_image import (
    EXPRESSIONS_YML,
    STYLES_YML,
    generate_avatar_image,
)
from avatar_studio.tuning.classify_persona import categorize_avatar_image

pytestmark = [pytest.mark.avatar, pytest.mark.integration]

_PASS_THRESHOLD = 0.75


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_pipeline(
    role: str,
    gateway: "GatewayClient",  # noqa: F821
    style: str = "photorealistic",
    size: int = 256,
    seed: int | None = None,
) -> tuple[bytes, dict]:
    """Run Stages A–E and return (raw_portrait_bytes, avatar_persona)."""
    url = gateway.base_url

    demo = pick_demographics(style=style, seed=seed)

    profile = generate_advisor_profile(role, demo, gateway_url=url)
    advisor = {"role": role, **profile}

    features = select_features(demo, advisor, gateway_url=url)
    avatar = build_avatar_charachter(advisor, demo, features)
    persona = avatar["avatar_persona"]

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        persona_path = tmp_dir / "persona.yml"
        with open(persona_path, "w") as f:
            yaml.dump(persona, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

        out = tmp_dir / "portrait.png"
        generate_avatar_image(
            persona_path,
            style={
                "name": style,
                "bg_color": demo.get("bg_color", "#F5F0E8"),
                "styles_yml": STYLES_YML,
            },
            expression={"name": "neutral", "expressions_yml": EXPRESSIONS_YML},
            gateway_url=url,
            width=size,
            height=size,
            out_path=out,
        )
        raw_bytes = out.read_bytes()

    return raw_bytes, persona


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_gateway_health(gateway):
    """Gateway is reachable and healthy."""
    import requests
    r = requests.get(f"{gateway.base_url}/health", timeout=5)
    assert r.status_code == 200


def test_step_b_generates_valid_profile(gateway):
    """Step B: generate_advisor_profile returns education/experience/traits."""
    demo = pick_demographics(seed=42)
    profile = generate_advisor_profile(
        "Financial Advisor", demo, gateway_url=gateway.base_url
    )
    assert isinstance(profile.get("education"), list) and profile["education"]
    assert isinstance(profile.get("experience"), list) and profile["experience"]
    assert isinstance(profile.get("traits"), list) and profile["traits"]


def test_step_c_selects_features(gateway):
    """Step C: select_features returns a non-empty feature dict."""
    demo = pick_demographics(seed=99)
    advisor = {"role": "Wealth Manager", "traits": ["analytical"], "education": [], "experience": []}
    features = select_features(demo, advisor, gateway_url=gateway.base_url)
    assert features
    assert "HAIR_STYLE" in features
    assert "CLOTHING" in features


def test_pipeline_produces_valid_png(gateway):
    """Stages A–E: full pipeline generates a valid PNG."""
    raw, _ = _run_pipeline("Financial Advisor", gateway)
    assert raw[:4] == b"\x89PNG", "Output is not a valid PNG"
    assert len(raw) > 1024, "PNG is suspiciously small"


def test_pipeline_persona_has_required_sections(gateway):
    """Pipeline persona contains all required sections with non-empty appearance."""
    _, persona = _run_pipeline("Portfolio Manager", gateway)
    for section in ("personal", "style", "advisor", "appearance"):
        assert section in persona, f"Missing section: {section}"
    assert persona["personal"].get("name")
    assert persona["appearance"]


def test_pipeline_categorizer_score(gateway):
    """Categorizer identifies ≥ 75 % of persona properties in the generated image."""
    # seed=21: male, upturned eyes, long straight nose, long full brows, squared chin, medium-brown skin
    raw, persona = _run_pipeline("Risk Analyst", gateway, seed=21)
    report = categorize_avatar_image(raw, persona, gateway_url=gateway.base_url)
    report = categorize_avatar_image(raw, persona, gateway_url=gateway.base_url)
    assert report.score >= _PASS_THRESHOLD, (
        f"Categorizer score {report.score:.0%} < {_PASS_THRESHOLD:.0%}\n"
        f"  Passed: {report.passes()}\n"
        f"  Failed: {report.failures()}\n"
        f"  Raw response:\n{report.raw_response}"
    )


def test_circle_frame_categorizer(gateway):
    """Circle-framed portrait still scores ≥ 65 % with the categorizer."""
    # seed=4: male, almond eyes, bulbous tip nose, high arch thick brows — clear features
    raw, persona = _run_pipeline("Compliance Officer", gateway, size=256, seed=4)
    bg = persona.get("style", {}).get("bg_color", "#4A90D9")
    framed = apply_circle_frame(raw, bg, 256)
    report = categorize_avatar_image(framed, persona, gateway_url=gateway.base_url)
    assert report.score >= 0.65, (
        f"Circle-framed score {report.score:.0%} < 60 %\n"
        f"  Passed: {report.passes()}\n"
        f"  Failed: {report.failures()}"
    )
