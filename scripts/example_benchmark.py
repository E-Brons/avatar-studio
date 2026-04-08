"""Benchmark — generate styled images from example personas and score them.

Generates images using the LLM pipeline, then scores via style classifier +
persona categorizer. Every result (including errors) is recorded in structured
JSON for later analysis.

Usage:
    python scripts/example_benchmark.py --sample 20 --style photorealistic
    python scripts/example_benchmark.py --style all --resume
    python scripts/example_benchmark.py --sample 5 --style clay --output reports/bench_clay.json
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import logging
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import yaml
from PIL import Image, PngImagePlugin
from tqdm import tqdm

# ── project root on sys.path ──────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from _example_utils import (  # noqa: E402
    EXAMPLES_DIR,
    REPORTS_DIR,
    append_learning,
    finalize_run_metadata,
    load_all_personas,
    make_run_metadata,
    normalize_persona,
)

from config.gateway import GatewayClient  # noqa: E402
from pipeline.render.llm.persona_sanitizer import sanitize_persona  # noqa: E402
from pipeline.render.llm.prompt_builder import build_prompt  # noqa: E402
from pipeline.render.llm.style_directive import build_style_directive  # noqa: E402
from tuning.classify_persona import CategoryReport, categorize_avatar_image  # noqa: E402
from tuning.classify_style import classify_image_style  # noqa: E402
from tuning.compare_side_by_side import compare_side_by_side  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

STYLES_YML = ROOT / "assets" / "styles" / "styles.yml"
GATEWAY_URL = "http://127.0.0.1:4096"
STYLE_PASS_THRESHOLD = 0.66
PERSONA_PASS_THRESHOLD = 0.50
COMPONENT_THRESHOLD = 0.80
TOTAL_THRESHOLD = 0.90

NEUTRAL_EXPR = {
    "expression": "Neutral",
    "facs_action_units": "",
    "description": "Resting face, relaxed muscles, eyes looking directly forward, mouth closed.",
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class BenchmarkEntry:
    example: str
    style_id: str
    run_idx: int
    gender: str
    style_score: float = 0.0
    persona_score: float = 0.0
    persona_failures: list[str] = field(default_factory=list)
    persona_passes: list[str] = field(default_factory=list)
    color_scores: dict[str, float] = field(default_factory=dict)
    property_notes: dict[str, str] = field(default_factory=dict)
    observed_colors: dict[str, str] = field(default_factory=dict)
    generation_time_s: float = 0.0
    image_path: str = ""
    prompt_excerpt: str = ""
    property_scores: dict[str, float] = field(default_factory=dict)
    sbs_identity_score: float = 0.0
    sbs_goal_score: float = 0.0
    sbs_quality_score: float = 0.0
    sbs_compound_score: float = 0.0
    sbs_reasoning: str = ""
    sbs_error: str | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_styles() -> list[dict]:
    with open(STYLES_YML) as f:
        data = yaml.safe_load(f)
    return [s for s in data["styles"] if s.get("engine") == "llm" and s.get("id") != "random"]


def embed_metadata(image_bytes: bytes, prompt: str, style_directive: str) -> bytes:
    img = Image.open(io.BytesIO(image_bytes))
    meta = PngImagePlugin.PngInfo()
    meta.add_text("Prompt", prompt)
    meta.add_text("StyleDirective", style_directive)
    meta.add_text("GeneratedAt", datetime.now().isoformat())
    out = io.BytesIO()
    img.save(out, format="PNG", pnginfo=meta)
    return out.getvalue()


def _extract_report_details(
    report: CategoryReport,
) -> tuple[dict[str, float], dict[str, str], dict[str, str]]:
    """Extract color_scores, property_notes, and observed_colors from CategoryReport."""
    color_scores: dict[str, float] = {}
    property_notes: dict[str, str] = {}
    observed_colors: dict[str, str] = {}

    for r in report.results:
        if r.note:
            property_notes[r.property_name] = r.note
        if r.color_score is not None:
            color_scores[r.property_name] = round(r.color_score, 3)
        # Extract observed_hex from the raw response for color properties
        observed_hex = getattr(r, "observed_hex", "")
        if not observed_hex:
            # Try to extract from note if it contains a hex
            hex_match = re.search(r"#[0-9A-Fa-f]{6}", r.note or "")
            if hex_match and r.property_name in (
                "skin_tone",
                "hair_color",
                "eye_color",
                "clothing",
            ):
                observed_hex = hex_match.group()
        if observed_hex:
            observed_colors[r.property_name] = observed_hex

    return color_scores, property_notes, observed_colors


# ---------------------------------------------------------------------------
# Generate + score
# ---------------------------------------------------------------------------


def generate_one(
    client: GatewayClient,
    example_dir: Path,
    persona: dict,
    style_entry: dict,
) -> tuple[bytes, float, str, str]:
    """Generate a single image. Returns (image_bytes, gen_time_s, prompt, error_or_empty)."""
    normalized = normalize_persona(persona)
    visual = sanitize_persona(normalized)
    style_directive = build_style_directive(
        style_entry, bg_color=persona.get("style", {}).get("bg_color", "#F5F0E8")
    )
    prompt = build_prompt(visual, NEUTRAL_EXPR, style_directive, reference_mode="person_photo")

    # Load reference image (original.jpg)
    image_path = example_dir / "original.jpg"
    with open(image_path, "rb") as f:
        ref_bytes = f.read()
    ref_b64 = base64.b64encode(ref_bytes).decode()

    t0 = time.time()
    raw_image = client.image_gen(
        prompt=prompt,
        width=512,
        height=512,
        optimize="quality",
        reference_images_b64=[ref_b64],
    )
    gen_time = time.time() - t0

    image_bytes = embed_metadata(raw_image, prompt, style_directive)
    return image_bytes, gen_time, prompt, ""


def score_one(
    client: GatewayClient,
    image_bytes: bytes,
    persona: dict,
    styles: list[dict],
    style_id: str,
) -> tuple[float, CategoryReport]:
    """Score an image for style + persona fidelity."""
    # Style classification
    style_result = classify_image_style(image_bytes, styles, gateway_url=client.base_url)
    style_score = style_result.scores.get(style_id, 0.0)
    if style_result.top_style_id == style_id and style_score == 0.0:
        style_score = STYLE_PASS_THRESHOLD

    # Persona categorization
    report = categorize_avatar_image(image_bytes, persona, gateway_url=client.base_url)

    return style_score, report


def _process_item(
    client: GatewayClient,
    name: str,
    persona: dict,
    style_entry: dict,
    run_idx: int,
    examples_dir: Path,
    all_styles: list[dict],
) -> dict:
    """Generate + score one work item. Returns a BenchmarkEntry as a dict."""
    style_id = style_entry["id"]
    gender = persona.get("personal", {}).get("gender", "unknown")
    example_dir = examples_dir / name

    entry = BenchmarkEntry(example=name, style_id=style_id, run_idx=run_idx, gender=gender)

    # Generate
    try:
        image_bytes, gen_time, prompt, _ = generate_one(client, example_dir, persona, style_entry)
        entry.generation_time_s = round(gen_time, 1)
        entry.prompt_excerpt = prompt[:300].replace("\n", " ")
    except Exception as exc:
        logger.warning("  generation FAILED %s x %s: %s", name, style_id, exc)
        entry.error = f"generation: {exc}"
        return asdict(entry)

    # Save image
    img_filename = f"{style_id}_benchmark_{run_idx}.png"
    img_path = example_dir / img_filename
    with open(img_path, "wb") as f:
        f.write(image_bytes)
    entry.image_path = str(img_path.relative_to(ROOT))

    # Score
    try:
        style_score, report = score_one(client, image_bytes, persona, all_styles, style_id)
        entry.style_score = round(style_score, 3)
        entry.persona_score = round(report.score, 3)
        entry.persona_failures = report.failures()
        entry.persona_passes = report.passes()

        color_scores, property_notes, observed_colors = _extract_report_details(report)
        entry.color_scores = color_scores
        entry.property_notes = property_notes
        entry.observed_colors = observed_colors

        # Per-property scores for component threshold check
        entry.property_scores = {
            r.property_name: round(
                r.color_score if r.color_score is not None else (1.0 if r.visible else 0.0), 3
            )
            for r in report.results
        }
    except Exception as exc:
        logger.warning("  scoring FAILED %s x %s: %s", name, style_id, exc)
        entry.error = f"scoring: {exc}"
        return asdict(entry)

    # Side-by-side comparison (§4.5)
    try:
        ref_path = example_dir / "original.jpg"
        with open(ref_path, "rb") as f:
            ref_bytes_sbs = f.read()
        sbs = compare_side_by_side(
            ref_bytes_sbs,
            image_bytes,
            goal=(
                "Re-render the person from the reference photo as a photorealistic portrait. "
                "The generated image should show the same individual: same face, same skin tone, "
                "same hair colour and style, same clothing, same accessories, same grooming. "
                "The rendering style should be clean and photorealistic."
            ),
            reference_label="REFERENCE",
            generated_label="GENERATED",
            gateway_url=client.base_url,
        )
        entry.sbs_identity_score = round(sbs.identity_score, 3)
        entry.sbs_goal_score = round(sbs.goal_score, 3)
        entry.sbs_quality_score = round(sbs.quality_score, 3)
        entry.sbs_compound_score = round(sbs.compound_score, 3)
        entry.sbs_reasoning = sbs.reasoning[:300] if sbs.reasoning else ""
    except Exception as exc:
        logger.warning("  SBS FAILED %s x %s: %s", name, style_id, exc)
        entry.sbs_error = f"sbs: {exc}"

    return asdict(entry)


# ---------------------------------------------------------------------------
# Resume logic
# ---------------------------------------------------------------------------


def _load_existing(output_path: Path) -> tuple[dict, list[dict], set[tuple[str, str, int]]]:
    """Load existing results for resume. Returns (data, entries, completed_keys)."""
    if not output_path.exists():
        return {}, [], set()

    with open(output_path) as f:
        data = json.load(f)

    entries = data.get("entries", [])
    completed = set()
    for e in entries:
        completed.add((e["example"], e["style_id"], e["run_idx"]))

    return data, entries, completed


def _atomic_write(output_path: Path, data: dict) -> None:
    """Write JSON atomically via tmp + rename."""
    tmp = output_path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp.rename(output_path)


# ---------------------------------------------------------------------------
# Summary computation
# ---------------------------------------------------------------------------


def _compute_summary(
    entries: list[dict],
    component_threshold: float = COMPONENT_THRESHOLD,
    total_threshold: float = TOTAL_THRESHOLD,
) -> dict:
    """Compute summary statistics from benchmark entries."""
    successful = [e for e in entries if not e.get("error")]
    failed = [e for e in entries if e.get("error")]

    if not successful:
        return {
            "total_entries": len(entries),
            "successful": 0,
            "failed": len(failed),
            "avg_style_score": 0.0,
            "avg_persona_score": 0.0,
            "avg_generation_time_s": 0.0,
            "style_pass_rate": 0.0,
            "persona_pass_rate": 0.0,
            "component_threshold": component_threshold,
            "total_threshold": total_threshold,
            "component_pass_rate": 0.0,
            "total_pass_rate": 0.0,
            "combined_pass_rate": 0.0,
            "avg_sbs_identity": 0.0,
            "avg_sbs_goal": 0.0,
            "avg_sbs_quality": 0.0,
            "avg_sbs_compound": 0.0,
            "by_gender": {},
            "most_failed_properties": [],
        }

    avg_style = sum(e["style_score"] for e in successful) / len(successful)
    avg_persona = sum(e["persona_score"] for e in successful) / len(successful)
    avg_time = sum(e["generation_time_s"] for e in successful) / len(successful)
    style_passes = sum(1 for e in successful if e["style_score"] >= STYLE_PASS_THRESHOLD)
    persona_passes = sum(1 for e in successful if e["persona_score"] >= PERSONA_PASS_THRESHOLD)

    # SBS averages
    avg_sbs_identity = sum(e.get("sbs_identity_score", 0.0) for e in successful) / len(successful)
    avg_sbs_goal = sum(e.get("sbs_goal_score", 0.0) for e in successful) / len(successful)
    avg_sbs_quality = sum(e.get("sbs_quality_score", 0.0) for e in successful) / len(successful)
    avg_sbs_compound = sum(e.get("sbs_compound_score", 0.0) for e in successful) / len(successful)

    # Two-threshold pass logic
    def _component_pass(e: dict) -> bool:
        prop_scores = e.get("property_scores", {})
        if prop_scores and any(v < component_threshold for v in prop_scores.values()):
            return False
        return e.get("sbs_quality_score", 0.0) >= component_threshold

    def _total_pass(e: dict) -> bool:
        return (
            e["persona_score"] >= total_threshold
            and e.get("sbs_compound_score", 0.0) >= total_threshold
        )

    component_passes = sum(1 for e in successful if _component_pass(e))
    total_passes = sum(1 for e in successful if _total_pass(e))
    combined_passes = sum(1 for e in successful if _component_pass(e) and _total_pass(e))

    # By gender
    by_gender: dict[str, dict] = {}
    for e in successful:
        g = e.get("gender", "unknown")
        if g not in by_gender:
            by_gender[g] = {"count": 0, "persona_scores": [], "style_scores": []}
        by_gender[g]["count"] += 1
        by_gender[g]["persona_scores"].append(e["persona_score"])
        by_gender[g]["style_scores"].append(e["style_score"])

    by_gender_summary = {}
    for g, info in by_gender.items():
        by_gender_summary[g] = {
            "count": info["count"],
            "avg_persona_score": round(
                sum(info["persona_scores"]) / len(info["persona_scores"]), 3
            ),
            "avg_style_score": round(sum(info["style_scores"]) / len(info["style_scores"]), 3),
        }

    # Most failed properties
    prop_failures: dict[str, int] = {}
    prop_totals: dict[str, int] = {}
    for e in successful:
        all_props = set(e.get("persona_failures", [])) | set(e.get("persona_passes", []))
        for p in all_props:
            prop_totals[p] = prop_totals.get(p, 0) + 1
        for p in e.get("persona_failures", []):
            prop_failures[p] = prop_failures.get(p, 0) + 1

    most_failed = []
    for p, fail_count in sorted(prop_failures.items(), key=lambda x: -x[1]):
        total = prop_totals.get(p, fail_count)
        rate = fail_count / total if total else 0
        most_failed.append(
            {
                "property": p,
                "failure_rate": round(rate, 3),
                "count": fail_count,
                "total": total,
            }
        )

    return {
        "total_entries": len(entries),
        "successful": len(successful),
        "failed": len(failed),
        "avg_style_score": round(avg_style, 3),
        "avg_persona_score": round(avg_persona, 3),
        "avg_generation_time_s": round(avg_time, 1),
        "style_pass_rate": round(style_passes / len(successful), 3),
        "persona_pass_rate": round(persona_passes / len(successful), 3),
        "component_threshold": component_threshold,
        "total_threshold": total_threshold,
        "component_pass_rate": round(component_passes / len(successful), 3),
        "total_pass_rate": round(total_passes / len(successful), 3),
        "combined_pass_rate": round(combined_passes / len(successful), 3),
        "avg_sbs_identity": round(avg_sbs_identity, 3),
        "avg_sbs_goal": round(avg_sbs_goal, 3),
        "avg_sbs_quality": round(avg_sbs_quality, 3),
        "avg_sbs_compound": round(avg_sbs_compound, 3),
        "by_gender": by_gender_summary,
        "most_failed_properties": most_failed[:10],
    }


# ---------------------------------------------------------------------------
# Learnings
# ---------------------------------------------------------------------------


def _append_learnings(metadata: dict, summary: dict, entries: list[dict]) -> None:
    """Append structured findings to learnings.jsonl."""
    run_id = metadata["run_id"]

    # Metric: overall scores
    append_learning(
        {
            "source": "example_benchmark",
            "run_id": run_id,
            "type": "metric",
            "category": "benchmark",
            "detail": (
                f"Benchmark: {summary['successful']}/{summary['total_entries']} successful, "
                f"style={summary['avg_style_score']:.0%}, persona={summary['avg_persona_score']:.0%}, "
                f"style_pass={summary['style_pass_rate']:.0%}, persona_pass={summary['persona_pass_rate']:.0%}"
            ),
            "severity": "low",
        }
    )

    # Finding: properties failing > 40%
    for prop_info in summary.get("most_failed_properties", []):
        if prop_info["failure_rate"] > 0.40:
            # Gather affected examples
            affected = [
                e["example"]
                for e in entries
                if prop_info["property"] in e.get("persona_failures", [])
            ]
            append_learning(
                {
                    "source": "example_benchmark",
                    "run_id": run_id,
                    "type": "finding",
                    "category": "systematic_failure",
                    "detail": (
                        f"{prop_info['property']} fails {prop_info['failure_rate']:.0%} "
                        f"({prop_info['count']}/{prop_info['total']})"
                    ),
                    "severity": "high" if prop_info["failure_rate"] > 0.50 else "medium",
                    "affected_examples": affected[:20],
                }
            )

    # Anomaly: persona_score = 0 on entries with no error
    successful = [e for e in entries if not e.get("error")]
    for e in successful:
        if e["persona_score"] == 0.0:
            append_learning(
                {
                    "source": "example_benchmark",
                    "run_id": run_id,
                    "type": "anomaly",
                    "category": "zero_score",
                    "detail": (
                        f"{e['example']} x {e['style_id']} got persona_score=0.0 "
                        f"despite having appearance data"
                    ),
                    "severity": "medium",
                    "affected_examples": [e["example"]],
                }
            )


# ---------------------------------------------------------------------------
# Main benchmark
# ---------------------------------------------------------------------------


def run_benchmark(
    examples_dir: Path,
    gateway_url: str,
    style_filter: str,
    example_range: tuple[int, int] | None,
    runs: int,
    resume: bool,
    output_path: Path,
    workers: int = 1,
    component_threshold: float = COMPONENT_THRESHOLD,
    total_threshold: float = TOTAL_THRESHOLD,
) -> dict:
    """Run the full benchmark. Returns the summary dict."""
    client = GatewayClient(gateway_url)
    all_styles = load_styles()
    style_map = {s["id"]: s for s in all_styles}

    # Determine styles to benchmark
    if style_filter == "all":
        styles = all_styles
    else:
        if style_filter not in style_map:
            logger.error("Unknown style: %s (available: %s)", style_filter, list(style_map.keys()))
            sys.exit(1)
        styles = [style_map[style_filter]]

    style_ids = [s["id"] for s in styles]

    # Load examples — require original.jpg + non-empty appearance
    raw_examples = load_all_personas(examples_dir)
    examples = [
        (name, persona)
        for name, persona in raw_examples
        if (examples_dir / name / "original.jpg").exists()
    ]

    if not examples:
        logger.error("No examples found with original.jpg and non-empty appearance")
        sys.exit(1)

    logger.info("Total available examples: %d (sorted alphabetically)", len(examples))

    # Slice by range
    if example_range:
        start, end = example_range
        end = min(end + 1, len(examples))  # inclusive end
        examples = examples[start:end]
        logger.info("Range [%d, %d]: selected %d examples", start, end - 1, len(examples))

    logger.info(
        "Benchmark: %d examples x %d styles x %d runs = %d images",
        len(examples),
        len(styles),
        runs,
        len(examples) * len(styles) * runs,
    )

    # Build work queue
    work: list[tuple[str, dict, dict, int]] = []
    for name, persona in examples:
        for style_entry in styles:
            for run_idx in range(1, runs + 1):
                work.append((name, persona, style_entry, run_idx))

    # Resume
    existing_entries: list[dict] = []
    completed: set[tuple[str, str, int]] = set()
    if resume:
        _, existing_entries, completed = _load_existing(output_path)
        before = len(work)
        work = [(n, p, s, r) for n, p, s, r in work if (n, s["id"], r) not in completed]
        logger.info(
            "Resume: %d already done, %d remaining (was %d)", len(completed), len(work), before
        )

    # Metadata
    metadata = make_run_metadata(
        "example_benchmark.py",
        {
            "style": style_filter,
            "styles": style_ids,
            "range": list(example_range) if example_range else None,
            "runs": runs,
            "resume": resume,
            "gateway_url": gateway_url,
            "image_size": "512x512",
            "optimize": "quality",
            "examples_count": len(examples),
        },
    )

    entries = list(existing_entries)
    total_work = len(work) + len(existing_entries)
    write_lock = threading.Lock()

    def _on_done(entry_dict: dict) -> None:
        """Append entry and flush to disk (called from main thread)."""
        entries.append(entry_dict)
        _atomic_write(output_path, {"run_metadata": metadata, "entries": entries})

    if workers <= 1:
        pbar = tqdm(
            work, desc="Benchmark", unit="img", initial=len(existing_entries), total=total_work
        )
        for name, persona, style_entry, run_idx in pbar:
            pbar.set_postfix_str(f"{name} x {style_entry['id']}")
            entry_dict = _process_item(
                client, name, persona, style_entry, run_idx, examples_dir, all_styles
            )
            _on_done(entry_dict)
    else:
        logger.info("Running benchmark with %d workers", workers)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_to_key = {
                pool.submit(
                    _process_item,
                    client,
                    name,
                    persona,
                    style_entry,
                    run_idx,
                    examples_dir,
                    all_styles,
                ): (name, style_entry["id"])
                for name, persona, style_entry, run_idx in work
            }
            pbar = tqdm(
                as_completed(future_to_key),
                desc="Benchmark",
                unit="img",
                initial=len(existing_entries),
                total=total_work,
            )
            for future in pbar:
                name, style_id = future_to_key[future]
                try:
                    entry_dict = future.result()
                except Exception as exc:
                    logger.error("Worker crashed %s x %s: %s", name, style_id, exc)
                    continue
                with write_lock:
                    _on_done(entry_dict)
                pbar.set_postfix_str(f"{name} x {style_id}")

    # Finalize
    metadata = finalize_run_metadata(metadata)
    summary = _compute_summary(entries, component_threshold, total_threshold)
    metadata["summary"] = summary

    final_data = {"run_metadata": metadata, "summary": summary, "entries": entries}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(output_path, final_data)

    # Append learnings
    _append_learnings(metadata, summary, entries)

    # Print summary
    print("\n=== Benchmark Complete ===")
    print(
        f"Total: {summary['total_entries']}  Successful: {summary['successful']}  Failed: {summary['failed']}"
    )
    print(
        f"Avg style:   {summary['avg_style_score']:.0%}  (pass rate: {summary['style_pass_rate']:.0%})"
    )
    print(
        f"Avg persona: {summary['avg_persona_score']:.0%}  (pass rate: {summary['persona_pass_rate']:.0%})"
    )
    print(f"Avg gen time: {summary['avg_generation_time_s']:.1f}s")
    print(
        f"\nSide-by-side (§4.5): identity={summary['avg_sbs_identity']:.0%}  "
        f"goal={summary['avg_sbs_goal']:.0%}  quality={summary['avg_sbs_quality']:.0%}  "
        f"compound={summary['avg_sbs_compound']:.0%}"
    )
    print(
        f"\nThresholds — component≥{summary['component_threshold']:.0%}  "
        f"total≥{summary['total_threshold']:.0%}"
    )
    print(
        f"  Component pass: {summary['component_pass_rate']:.0%}  "
        f"Total pass: {summary['total_pass_rate']:.0%}  "
        f"Combined pass: {summary['combined_pass_rate']:.0%}"
    )

    if summary["by_gender"]:
        print("\nBy gender:")
        for g, info in sorted(summary["by_gender"].items()):
            print(
                f"  {g:15s} persona={info['avg_persona_score']:.0%}  style={info['avg_style_score']:.0%}  ({info['count']} images)"
            )

    if summary["most_failed_properties"]:
        print("\nMost failed properties:")
        for p in summary["most_failed_properties"][:5]:
            print(f"  {p['property']:15s} {p['failure_rate']:.0%} fail ({p['count']}/{p['total']})")

    print(f"\nResults: {output_path}")
    logger.info("Learnings appended to %s", REPORTS_DIR / "learnings.jsonl")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Example benchmark — generate + score")
    parser.add_argument("--gateway", default=GATEWAY_URL, help="LLM gateway URL")
    parser.add_argument("--style", default="photorealistic", help="Style ID or 'all'")
    parser.add_argument(
        "--range",
        type=int,
        nargs=2,
        metavar=("START", "END"),
        default=None,
        help="Inclusive index range of examples to run (e.g. --range 0 49)",
    )
    parser.add_argument("--runs", type=int, default=1, help="Repeats per (example, style)")
    parser.add_argument("--resume", action="store_true", help="Skip already-completed entries")
    parser.add_argument("--workers", type=int, default=1, help="Parallel workers (default 1)")
    parser.add_argument(
        "--component-threshold",
        type=float,
        default=COMPONENT_THRESHOLD,
        help="Min per-property and SBS quality score to pass component check (default 0.80)",
    )
    parser.add_argument(
        "--total-threshold",
        type=float,
        default=TOTAL_THRESHOLD,
        help="Min persona score and SBS compound score to pass total check (default 0.90)",
    )
    parser.add_argument("--examples-dir", type=Path, default=EXAMPLES_DIR)
    parser.add_argument("--output", type=Path, default=None, help="Override output path")
    args = parser.parse_args()

    # Build default output filename with timestamp + run params
    if args.output is None:
        ts = datetime.now().strftime("%y-%m-%d-%H-%M")
        style_tag = args.style
        range_tag = f"_r{args.range[0]}-{args.range[1]}" if args.range else "_all"
        args.output = REPORTS_DIR / f"benchmark_{ts}_{style_tag}{range_tag}.json"

    run_benchmark(
        examples_dir=args.examples_dir,
        gateway_url=args.gateway,
        style_filter=args.style,
        example_range=tuple(args.range) if args.range else None,
        runs=args.runs,
        resume=args.resume,
        output_path=args.output,
        workers=args.workers,
        component_threshold=args.component_threshold,
        total_threshold=args.total_threshold,
    )
