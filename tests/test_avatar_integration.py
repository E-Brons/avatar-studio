"""Integration tests — full pipeline via LLM Gateway.

Runs the complete A→E avatar pipeline against the live gateway at
http://127.0.0.1:4096 and verifies the outputs are structurally valid.

Skips automatically if the gateway is unreachable.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml

from pipeline.persona.aggregator_llm import select_features
from pipeline.persona.generator import build_avatar_charachter, pick_demographics
from pipeline.render.expression_resolver import EXPRESSIONS_YML
from pipeline.render.llm.orchestrator import (
    generate_avatar_image,
)
from pipeline.render.postprocess.compositor import apply_circle_frame
from pipeline.render.style_resolver import STYLES_YML
from tuning.classify_persona import categorize_avatar_image

pytestmark = [pytest.mark.avatar, pytest.mark.integration]

_PASS_THRESHOLD = 0.75


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_pipeline(
    gateway: "GatewayClient",  # noqa: F821
    style: str = "photorealistic",
    size: int = 256,
    seed: int | None = None,
) -> tuple[bytes, dict]:
    """Run the full persona + image pipeline and return (raw_portrait_bytes, avatar_persona)."""
    url = gateway.base_url

    demo = pick_demographics(style=style, seed=seed)
    advisor: dict = {}

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


def test_select_features(gateway):
    """Feature selection returns a non-empty feature dict."""
    demo = pick_demographics(seed=99)
    advisor: dict = {}
    features = select_features(demo, advisor, gateway_url=gateway.base_url)
    assert features
    assert "HAIR_STYLE" in features
    assert "CLOTHING" in features


def test_pipeline_produces_valid_png(gateway):
    """Stages A–E: full pipeline generates a valid PNG."""
    raw, _ = _run_pipeline(gateway)
    assert raw[:4] == b"\x89PNG", "Output is not a valid PNG"
    assert len(raw) > 1024, "PNG is suspiciously small"


def test_pipeline_persona_has_required_sections(gateway):
    """Pipeline persona contains all required sections with non-empty appearance."""
    _, persona = _run_pipeline(gateway)
    for section in ("personal", "style", "personality", "appearance"):
        assert section in persona, f"Missing section: {section}"
    assert persona["personal"].get("name")
    assert persona["appearance"]


def test_pipeline_categorizer_score(gateway):
    """Categorizer identifies ≥ 75 % of persona properties in the generated image."""
    # seed=21: male, upturned eyes, long straight nose, long full brows, squared chin, medium-brown skin
    raw, persona = _run_pipeline(gateway, seed=21)
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
    raw, persona = _run_pipeline(gateway, size=256, seed=4)
    bg = persona.get("style", {}).get("bg_color", "#4A90D9")
    framed = apply_circle_frame(raw, bg, 256)
    report = categorize_avatar_image(framed, persona, gateway_url=gateway.base_url)
    assert report.score >= 0.65, (
        f"Circle-framed score {report.score:.0%} < 60 %\n"
        f"  Passed: {report.passes()}\n"
        f"  Failed: {report.failures()}"
    )
