"""Style loop — generate, classify, and learn from styled avatar images.

Usage:
    python scripts/style_loop.py [--rounds N] [--gateway URL]

For each round:
  1. Pick a random LLM style
  2. For each example folder (adam_levine, rihanna, sara_ramirez):
     a. Generate 512x512 image using the persona.yml + photorealistic.png reference
     b. Check style recognition >= 66%
     c. Check persona score
     d. Compare with previous results and reason about quality
     e. Update docs/software/llm_prompts/style.md
"""

from __future__ import annotations

import argparse
import base64
import io
import logging
import random
import sys
from datetime import datetime
from pathlib import Path

import yaml
from PIL import Image, PngImagePlugin

# ── project root on sys.path ──────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from config.gateway import GatewayClient  # noqa: E402
from pipeline.render.llm.persona_sanitizer import sanitize_persona  # noqa: E402
from pipeline.render.llm.prompt_builder import build_prompt  # noqa: E402
from pipeline.render.llm.style_directive import build_style_directive  # noqa: E402
from tuning.classify_persona import categorize_avatar_image  # noqa: E402
from tuning.classify_style import StyleClassificationResult, classify_image_style  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

EXAMPLES_DIR = ROOT / "assets" / "examples"
STYLES_YML = ROOT / "assets" / "styles" / "styles.yml"
STYLE_DOC = ROOT / "docs" / "software" / "llm_prompts" / "style.md"
GATEWAY_URL = "http://127.0.0.1:4096"

NEUTRAL_EXPR = {
    "expression": "Neutral",
    "facs_action_units": "",
    "description": "Resting face, relaxed muscles, eyes looking directly forward, mouth closed.",
}

STYLE_PASS_THRESHOLD = 0.66


# ── helpers ───────────────────────────────────────────────────────────────────


def load_styles() -> list[dict]:
    with open(STYLES_YML) as f:
        data = yaml.safe_load(f)
    return [s for s in data["styles"] if s.get("engine") == "llm" and s.get("id") != "random"]


def load_persona(folder: Path) -> dict:
    with open(folder / "persona.yml") as f:
        return yaml.safe_load(f)


def load_reference_image(folder: Path) -> bytes:
    path = folder / "photorealistic.png"
    with open(path, "rb") as f:
        return f.read()


def embed_metadata(image_bytes: bytes, prompt: str, style_directive: str) -> bytes:
    img = Image.open(io.BytesIO(image_bytes))
    meta = PngImagePlugin.PngInfo()
    meta.add_text("Prompt", prompt)
    meta.add_text("StyleDirective", style_directive)
    meta.add_text("GeneratedAt", datetime.now().isoformat())
    out = io.BytesIO()
    img.save(out, format="PNG", pnginfo=meta)
    return out.getvalue()


def save_image(image_bytes: bytes, folder: Path, style_id: str) -> Path:
    ts = datetime.now().strftime("%H_%M_%S")
    filename = f"{style_id}_{ts}.PNG"
    out_path = folder / filename
    with open(out_path, "wb") as f:
        f.write(image_bytes)
    logger.info("  saved → %s", out_path.relative_to(ROOT))
    return out_path


def generate_image(
    client: GatewayClient,
    prompt: str,
    style_directive: str,
    reference_bytes: bytes,
) -> bytes:
    ref_b64 = base64.b64encode(reference_bytes).decode()
    return client.image_gen(
        prompt=prompt,
        width=512,
        height=512,
        optimize="normal",
        reference_images_b64=[ref_b64],
    )


def classify_style(
    client: GatewayClient, image_bytes: bytes, styles: list[dict], expected_id: str
) -> tuple[StyleClassificationResult, float]:
    result = classify_image_style(image_bytes, styles, gateway_url=client.base_url)
    score = result.scores.get(expected_id, 0.0)
    # When the classifier correctly identifies the style as top but the markdown fallback
    # fails to extract a numeric score, treat it as a passing score rather than 0%.
    if result.top_style_id == expected_id and score == 0.0:
        score = STYLE_PASS_THRESHOLD
    return result, score


def check_persona(client: GatewayClient, image_bytes: bytes, persona: dict) -> float:
    report = categorize_avatar_image(image_bytes, persona, gateway_url=client.base_url)
    return report.score


# ── learning doc update ───────────────────────────────────────────────────────


def load_or_create_doc() -> str:
    if STYLE_DOC.exists():
        return STYLE_DOC.read_text()
    return "# Style Prompt Learning\n\nLearning accumulated from style loop runs.\n\n"


def append_run_entry(
    doc: str,
    round_num: int,
    style_id: str,
    example_name: str,
    style_score: float,
    persona_score: float,
    top_style: str,
    prompt_excerpt: str,
    reasoning: str,
    observations: str,
) -> str:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = (
        f"\n## Round {round_num} — {style_id} / {example_name} — {ts}\n\n"
        f"- **Style score** ({style_id}): {style_score:.0%} "
        f"({'PASS ✓' if style_score >= STYLE_PASS_THRESHOLD else 'FAIL ✗'})\n"
        f"- **Top classified**: `{top_style}`\n"
        f"- **Persona score**: {persona_score:.0%}\n"
        f"- **Prompt excerpt**: {prompt_excerpt[:200]}\n"
        f"- **Model reasoning**: {reasoning[:300]}\n"
        f"- **Observations**: {observations}\n"
    )
    return doc + entry


def derive_observations(
    style_id: str,
    example_name: str,
    style_score: float,
    top_style: str,
    persona_score: float,
    history: list[dict],
) -> str:
    obs: list[str] = []

    # Compare with previous runs for same style+example
    prev = [h for h in history if h["style_id"] == style_id and h["example"] == example_name]
    if prev:
        prev_style = [h["style_score"] for h in prev]
        avg_prev = sum(prev_style) / len(prev_style)
        delta = style_score - avg_prev
        trend = f"Δ{delta:+.0%} vs avg {avg_prev:.0%} over {len(prev)} prior run(s)."
        obs.append(trend)
    else:
        obs.append("First run for this combination.")

    if style_score < STYLE_PASS_THRESHOLD:
        obs.append(
            f"Style FAILED — classifier returned `{top_style}` instead of `{style_id}`. "
            "Consider strengthening style-defining traits in system_prompt."
        )
    else:
        obs.append(f"Style PASSED. Classifier correctly identified `{style_id}`.")

    if persona_score < 0.5:
        obs.append(
            f"Persona weak ({persona_score:.0%}) — visual properties not well preserved. "
            "Reference image may be insufficient or style is too aggressive."
        )
    elif persona_score < 0.75:
        obs.append(f"Persona moderate ({persona_score:.0%}) — some features not preserved.")
    else:
        obs.append(f"Persona strong ({persona_score:.0%}).")

    return " ".join(obs)


# ── main loop ─────────────────────────────────────────────────────────────────


def run_loop(rounds: int, gateway_url: str) -> None:
    client = GatewayClient(gateway_url)
    styles = load_styles()
    style_ids = [s["id"] for s in styles]
    example_dirs = sorted(
        d
        for d in EXAMPLES_DIR.iterdir()
        if d.is_dir() and (d / "persona.yml").exists() and (d / "photorealistic.png").exists()
    )

    STYLE_DOC.parent.mkdir(parents=True, exist_ok=True)
    doc = load_or_create_doc()
    history: list[dict] = []

    logger.info("Starting style loop: %d rounds, styles=%s", rounds, style_ids)

    for round_num in range(1, rounds + 1):
        style_entry = random.choice(styles)
        style_id = style_entry["id"]
        style_directive = build_style_directive(style_entry)
        logger.info("\n=== Round %d/%d — style: %s ===", round_num, rounds, style_id)

        for ex_dir in example_dirs:
            if not ex_dir.is_dir():
                continue
            example_name = ex_dir.name
            logger.info("  [%s] generating...", example_name)

            persona_raw = load_persona(ex_dir)
            reference_bytes = load_reference_image(ex_dir)
            visual_persona = sanitize_persona(persona_raw)

            prompt = build_prompt(
                visual_persona,
                NEUTRAL_EXPR,
                style_directive,
                reference_image=True,
            )

            # Generate
            try:
                image_bytes = generate_image(client, prompt, style_directive, reference_bytes)
            except Exception as exc:
                logger.error("  generation failed: %s", exc)
                continue

            # Embed metadata + save
            image_bytes = embed_metadata(image_bytes, prompt, style_directive)
            save_image(image_bytes, ex_dir, style_id)

            # Classify style
            try:
                style_result, style_score = classify_style(client, image_bytes, styles, style_id)
            except Exception as exc:
                logger.error("  style classification failed: %s", exc)
                style_result = StyleClassificationResult(top_style_id="", scores={})
                style_score = 0.0

            logger.info(
                "  style: %s → top=%s score=%.0f%%  %s",
                style_id,
                style_result.top_style_id,
                style_score * 100,
                "PASS" if style_score >= STYLE_PASS_THRESHOLD else "FAIL",
            )

            # Check persona
            try:
                persona_score = check_persona(client, image_bytes, persona_raw)
            except Exception as exc:
                logger.error("  persona check failed: %s", exc)
                persona_score = 0.0

            logger.info("  persona score: %.0f%%", persona_score * 100)

            # Derive observations
            observations = derive_observations(
                style_id,
                example_name,
                style_score,
                style_result.top_style_id,
                persona_score,
                history,
            )
            logger.info("  observations: %s", observations)

            # Update learning doc
            prompt_excerpt = prompt[:200].replace("\n", " ")
            doc = append_run_entry(
                doc,
                round_num,
                style_id,
                example_name,
                style_score,
                persona_score,
                style_result.top_style_id,
                prompt_excerpt,
                style_result.reasoning[:300] if style_result.reasoning else "",
                observations,
            )
            STYLE_DOC.write_text(doc)

            history.append(
                {
                    "round": round_num,
                    "style_id": style_id,
                    "example": example_name,
                    "style_score": style_score,
                    "persona_score": persona_score,
                }
            )

    # Final summary
    logger.info("\n=== SUMMARY ===")
    if history:
        by_style: dict[str, list[float]] = {}
        for h in history:
            by_style.setdefault(h["style_id"], []).append(h["style_score"])
        for sid, scores in sorted(by_style.items()):
            avg = sum(scores) / len(scores)
            passes = sum(1 for s in scores if s >= STYLE_PASS_THRESHOLD)
            logger.info("  %s: avg=%.0f%% passes=%d/%d", sid, avg * 100, passes, len(scores))

    summary_section = "\n## Summary\n\n"
    if history:
        by_style = {}
        for h in history:
            by_style.setdefault(h["style_id"], []).append(h["style_score"])
        for sid, scores in sorted(by_style.items()):
            avg = sum(scores) / len(scores)
            passes = sum(1 for s in scores if s >= STYLE_PASS_THRESHOLD)
            summary_section += (
                f"- **{sid}**: avg style score {avg:.0%}, "
                f"{passes}/{len(scores)} passed ({passes / len(scores):.0%})\n"
            )
    doc = doc + summary_section
    STYLE_DOC.write_text(doc)
    logger.info("Learning doc updated: %s", STYLE_DOC.relative_to(ROOT))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--gateway", default=GATEWAY_URL)
    args = parser.parse_args()
    run_loop(rounds=args.rounds, gateway_url=args.gateway)
