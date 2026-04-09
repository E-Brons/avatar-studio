"""Analyze benchmark results — multi-dimensional analysis + recommendations.

Reads benchmark JSON from _benchmark.py, optionally combines with coverage
audit data, and produces structured analysis with actionable recommendations.

Used by scripts/learn/learn_create.py.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from collections import Counter
from pathlib import Path

# ── project root on sys.path ──────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "examples"))

from _example_utils import (  # noqa: E402
    append_learning,
    finalize_run_metadata,
    hex_to_rgb,
    make_run_metadata,
    rgb_to_ycbcr,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

STYLE_PASS_THRESHOLD = 0.66
PERSONA_PASS_THRESHOLD = 0.50

_COLOR_PROPERTIES = frozenset({"skin_tone", "hair_color", "eye_color", "clothing"})


# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------


def _load_benchmark(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def _load_coverage(path: Path) -> dict | None:
    if not path or not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Analysis dimensions
# ---------------------------------------------------------------------------


def _analyze_by_style(entries: list[dict]) -> dict:
    """Dimension 1: aggregate by style_id."""
    by_style: dict[str, list[dict]] = {}
    for e in entries:
        if e.get("error"):
            continue
        by_style.setdefault(e["style_id"], []).append(e)

    result = {}
    for sid, items in sorted(by_style.items()):
        result[sid] = {
            "count": len(items),
            "avg_style_score": round(sum(e["style_score"] for e in items) / len(items), 3),
            "avg_persona_score": round(sum(e["persona_score"] for e in items) / len(items), 3),
            "style_pass_rate": round(
                sum(1 for e in items if e["style_score"] >= STYLE_PASS_THRESHOLD) / len(items), 3
            ),
            "persona_pass_rate": round(
                sum(1 for e in items if e["persona_score"] >= PERSONA_PASS_THRESHOLD) / len(items),
                3,
            ),
        }
    return result


def _analyze_by_gender(entries: list[dict]) -> dict:
    """Dimension 2: aggregate by gender."""
    by_gender: dict[str, list[dict]] = {}
    for e in entries:
        if e.get("error"):
            continue
        g = e.get("gender", "unknown")
        by_gender.setdefault(g, []).append(e)

    result = {}
    for g, items in sorted(by_gender.items()):
        result[g] = {
            "count": len(items),
            "avg_persona_score": round(sum(e["persona_score"] for e in items) / len(items), 3),
            "avg_style_score": round(sum(e["style_score"] for e in items) / len(items), 3),
        }
    return result


def _analyze_by_property(entries: list[dict]) -> dict:
    """Dimension 3: per-property failure rate + top failure notes."""
    successful = [e for e in entries if not e.get("error")]

    prop_fail: dict[str, int] = {}
    prop_total: dict[str, int] = {}
    prop_notes: dict[str, list[str]] = {}
    prop_color_scores: dict[str, list[float]] = {}

    for e in successful:
        all_props = set(e.get("persona_failures", [])) | set(e.get("persona_passes", []))
        for p in all_props:
            prop_total[p] = prop_total.get(p, 0) + 1
        for p in e.get("persona_failures", []):
            prop_fail[p] = prop_fail.get(p, 0) + 1
            note = e.get("property_notes", {}).get(p, "")
            if note:
                prop_notes.setdefault(p, []).append(note)
        # Color scores for all entries (not just failures)
        for p, score in e.get("color_scores", {}).items():
            prop_color_scores.setdefault(p, []).append(score)

    result = {}
    for p in sorted(prop_total.keys()):
        total = prop_total[p]
        fails = prop_fail.get(p, 0)
        info: dict = {
            "failure_rate": round(fails / total, 3) if total else 0,
            "total": total,
            "fail_count": fails,
        }

        # Top failure notes (deduplicated by similarity)
        notes = prop_notes.get(p, [])
        if notes:
            note_counts = Counter(notes).most_common(5)
            info["top_failure_notes"] = [{"note": n, "count": c} for n, c in note_counts]

        # Avg color score if applicable
        scores = prop_color_scores.get(p, [])
        if scores:
            info["avg_color_score"] = round(sum(scores) / len(scores), 3)

        result[p] = info
    return result


def _analyze_systematic_failures(entries: list[dict]) -> list[dict]:
    """Dimension 4: (property, gender, style) combos failing >50%."""
    successful = [e for e in entries if not e.get("error")]

    # Group by (property, gender, style)
    combos: dict[tuple[str, str, str], dict] = {}
    for e in successful:
        gender = e.get("gender", "unknown")
        style = e["style_id"]
        all_props = set(e.get("persona_failures", [])) | set(e.get("persona_passes", []))
        for p in all_props:
            key = (p, gender, style)
            if key not in combos:
                combos[key] = {"total": 0, "fails": 0, "notes": []}
            combos[key]["total"] += 1
        for p in e.get("persona_failures", []):
            key = (p, gender, style)
            combos[key]["fails"] += 1
            note = e.get("property_notes", {}).get(p, "")
            if note:
                combos[key]["notes"].append(note)

    result = []
    for (prop, gender, style), info in combos.items():
        if info["total"] < 3:
            continue
        rate = info["fails"] / info["total"]
        if rate > 0.50:
            top_notes = [n for n, _ in Counter(info["notes"]).most_common(3)]
            result.append(
                {
                    "property": prop,
                    "gender": gender,
                    "style": style,
                    "failure_rate": round(rate, 3),
                    "count": info["total"],
                    "fail_count": info["fails"],
                    "top_notes": top_notes,
                }
            )

    result.sort(key=lambda x: -x["failure_rate"])
    return result


def _analyze_worst_performers(entries: list[dict], bottom_n: int) -> list[dict]:
    """Dimension 5: bottom N by persona_score."""
    successful = [e for e in entries if not e.get("error")]
    sorted_entries = sorted(successful, key=lambda e: e["persona_score"])

    result = []
    for e in sorted_entries[:bottom_n]:
        failure_notes = {}
        for p in e.get("persona_failures", []):
            note = e.get("property_notes", {}).get(p, "")
            if note:
                failure_notes[p] = note

        result.append(
            {
                "example": e["example"],
                "style": e["style_id"],
                "persona_score": e["persona_score"],
                "style_score": e["style_score"],
                "failures": e.get("persona_failures", []),
                "failure_notes": failure_notes,
            }
        )
    return result


def _analyze_color_drift(entries: list[dict]) -> dict:
    """Dimension 6: color drift analysis per color property."""
    successful = [e for e in entries if not e.get("error")]
    result = {}

    for prop in ("skin_tone", "hair_color", "eye_color"):
        observed_list: list[dict] = []
        for e in successful:
            observed_hex = e.get("observed_colors", {}).get(prop, "")
            if not observed_hex or not re.match(r"^#[0-9A-Fa-f]{6}$", observed_hex):
                continue
            color_score = e.get("color_scores", {}).get(prop)
            observed_list.append(
                {
                    "example": e["example"],
                    "style": e["style_id"],
                    "observed": observed_hex,
                    "color_score": color_score,
                }
            )

        if not observed_list:
            continue

        scores = [o["color_score"] for o in observed_list if o["color_score"] is not None]
        avg_prox = round(sum(scores) / len(scores), 3) if scores else 0

        # Worst drifts
        worst = sorted(
            [o for o in observed_list if o["color_score"] is not None],
            key=lambda x: x["color_score"],
        )[:5]

        # Compute drift direction (lighter/darker) by comparing avg luminance
        drift_direction = _compute_drift_direction(observed_list)

        result[prop] = {
            "avg_proximity": avg_prox,
            "sample_size": len(observed_list),
            "drift_direction": drift_direction,
            "worst_drifts": worst,
        }

    return result


def _compute_drift_direction(observed_list: list[dict]) -> str:
    """Estimate whether observed colors drift lighter/darker on average."""
    # We'd need expected values too — for now just report based on observed luminance
    if not observed_list:
        return "unknown"

    luminances = []
    for o in observed_list:
        rgb = hex_to_rgb(o["observed"])
        if rgb:
            y, _, _ = rgb_to_ycbcr(*rgb)
            luminances.append(y)

    if not luminances:
        return "unknown"

    avg_lum = sum(luminances) / len(luminances)
    if avg_lum > 180:
        return "tends light"
    if avg_lum < 80:
        return "tends dark"
    return "mid-range"


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------


def _analyze_sbs(entries: list[dict]) -> dict:
    """Dimension 7: side-by-side score averages and low-scorers."""
    successful = [e for e in entries if not e.get("error") and not e.get("sbs_error")]
    if not successful:
        return {}

    def _avg(key: str) -> float:
        vals = [e.get(key, 0.0) for e in successful]
        return round(sum(vals) / len(vals), 3) if vals else 0.0

    avg_identity = _avg("sbs_identity_score")
    avg_goal = _avg("sbs_goal_score")
    avg_quality = _avg("sbs_quality_score")
    avg_compound = _avg("sbs_compound_score")

    worst = sorted(successful, key=lambda e: e.get("sbs_compound_score", 0.0))[:5]
    worst_list = [
        {
            "example": e["example"],
            "style": e["style_id"],
            "identity": e.get("sbs_identity_score", 0.0),
            "goal": e.get("sbs_goal_score", 0.0),
            "quality": e.get("sbs_quality_score", 0.0),
            "compound": e.get("sbs_compound_score", 0.0),
            "reasoning": (e.get("sbs_reasoning") or "")[:150],
        }
        for e in worst
    ]

    return {
        "sample_size": len(successful),
        "avg_identity": avg_identity,
        "avg_goal": avg_goal,
        "avg_quality": avg_quality,
        "avg_compound": avg_compound,
        "worst": worst_list,
    }


def _build_recommendations(
    by_property: dict,
    systematic: list[dict],
    color_drift: dict,
    coverage: dict | None,
    sbs: dict | None = None,
) -> list[dict]:
    """Build actionable recommendations from analysis + optional coverage data."""
    recs: list[dict] = []

    # From property failures
    for prop, info in by_property.items():
        if info["failure_rate"] > 0.40:
            top_notes_str = ""
            if info.get("top_failure_notes"):
                top_notes_str = f' — top note: "{info["top_failure_notes"][0]["note"]}"'
            recs.append(
                {
                    "severity": "high" if info["failure_rate"] > 0.50 else "medium",
                    "category": "prompt_failure",
                    "property": prop,
                    "detail": (
                        f"{prop} fails {info['failure_rate']:.0%} "
                        f"({info['fail_count']}/{info['total']}){top_notes_str}"
                    ),
                    "action": f"Investigate {prop} rendering — consider prompt wording changes",
                    "affected_count": info["fail_count"],
                }
            )

    # From systematic failures
    for sf in systematic:
        if sf["failure_rate"] > 0.60:
            recs.append(
                {
                    "severity": "high",
                    "category": "systematic_bias",
                    "property": sf["property"],
                    "detail": (
                        f"{sf['property']} x {sf['gender']} x {sf['style']} "
                        f"fails {sf['failure_rate']:.0%} ({sf['fail_count']}/{sf['count']})"
                    ),
                    "action": (
                        f"Investigate {sf['style']} style rendering for "
                        f"{sf['gender']} {sf['property']}"
                    ),
                    "affected_count": sf["fail_count"],
                }
            )

    # From color drift
    for prop, drift in color_drift.items():
        if drift["avg_proximity"] < 0.80:
            recs.append(
                {
                    "severity": "medium",
                    "category": "color_drift",
                    "property": prop,
                    "detail": (
                        f"{prop} avg proximity={drift['avg_proximity']:.0%} "
                        f"({drift['sample_size']} samples), {drift['drift_direction']}"
                    ),
                    "action": f"Consider prompt reinforcement for {prop} accuracy",
                    "affected_count": drift["sample_size"],
                }
            )

    # From SBS scores
    if sbs and sbs.get("sample_size", 0) > 0:
        compound = sbs["avg_compound"]
        identity = sbs["avg_identity"]
        goal = sbs["avg_goal"]
        if compound < 0.50:
            recs.append(
                {
                    "severity": "high",
                    "category": "sbs_failure",
                    "property": "sbs_compound",
                    "detail": (
                        f"SBS compound={compound:.0%}  identity={identity:.0%}  "
                        f"goal={goal:.0%}  ({sbs['sample_size']} images)"
                    ),
                    "action": (
                        "Identity fidelity is critically low — "
                        "the prompt/persona description may be overriding reference photo identity. "
                        "Consider reducing persona detail or adjusting reference_mode instruction."
                    ),
                    "affected_count": sbs["sample_size"],
                }
            )
        elif compound < 0.70:
            recs.append(
                {
                    "severity": "medium",
                    "category": "sbs_failure",
                    "property": "sbs_compound",
                    "detail": (
                        f"SBS compound={compound:.0%}  identity={identity:.0%}  "
                        f"goal={goal:.0%}  ({sbs['sample_size']} images)"
                    ),
                    "action": (
                        "Identity fidelity is below target — "
                        "review reference_mode instruction and persona prompt verbosity."
                    ),
                    "affected_count": sbs["sample_size"],
                }
            )

    # From coverage data (if provided)
    if coverage:
        attrs = coverage.get("attributes", {})
        for attr_name, attr_data in attrs.items():
            if attr_data.get("coverage_pct", 1.0) < 0.70:
                unmatched = attr_data.get("unmatched", [])
                gap_values = [u.get("value", "") for u in unmatched[:5]]
                recs.append(
                    {
                        "severity": "medium",
                        "category": "pool_gap",
                        "property": attr_name,
                        "detail": (
                            f"{attr_name} pool coverage only {attr_data['coverage_pct']:.0%} "
                            f"({attr_data.get('matched_count', 0)}/{attr_data.get('total_with_value', 0)})"
                        ),
                        "action": f"Expand {attr_name} pool — unmatched values: {gap_values}",
                        "affected_count": attr_data.get("unmatched_count", 0),
                    }
                )

    recs.sort(key=lambda r: 0 if r["severity"] == "high" else 1 if r["severity"] == "medium" else 2)
    return recs


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------


def run_analysis(
    input_path: Path,
    coverage_path: Path | None,
    output_path: Path,
    bottom_n: int,
) -> dict:
    """Run the full analysis. Returns the analysis dict."""
    metadata = make_run_metadata(
        "analyze_benchmark.py",
        {
            "input": str(input_path),
            "coverage": str(coverage_path) if coverage_path else None,
            "output": str(output_path),
            "bottom_n": bottom_n,
        },
    )

    benchmark = _load_benchmark(input_path)
    entries = benchmark.get("entries", [])
    bench_meta = benchmark.get("run_metadata", {})
    coverage = _load_coverage(coverage_path) if coverage_path else None

    if not entries:
        logger.error("No entries in benchmark file %s", input_path)
        sys.exit(1)

    successful = [e for e in entries if not e.get("error")]
    logger.info(
        "Loaded %d entries (%d successful) from %s", len(entries), len(successful), input_path
    )

    # Run all dimensions
    by_style = _analyze_by_style(entries)
    by_gender = _analyze_by_gender(entries)
    by_property = _analyze_by_property(entries)
    systematic = _analyze_systematic_failures(entries)
    worst = _analyze_worst_performers(entries, bottom_n)
    color_drift = _analyze_color_drift(entries)
    sbs = _analyze_sbs(entries)
    recommendations = _build_recommendations(by_property, systematic, color_drift, coverage, sbs)

    # Finalize
    metadata = finalize_run_metadata(metadata)
    analysis = {
        "run_metadata": metadata,
        "benchmark_run_id": bench_meta.get("run_id", ""),
        "benchmark_params": bench_meta.get("parameters", {}),
        "total_entries": len(entries),
        "successful": len(successful),
        "failed": len(entries) - len(successful),
        "by_style": by_style,
        "by_gender": by_gender,
        "by_property": by_property,
        "systematic_failures": systematic,
        "worst_performers": worst,
        "color_drift": color_drift,
        "sbs": sbs,
        "recommendations": recommendations,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(analysis, f, indent=2, ensure_ascii=False)
    logger.info("Analysis written: %s", output_path)

    # Append learnings
    _append_learnings(metadata, analysis)

    # Print summary
    _print_summary(analysis, bench_meta)

    return analysis


def _append_learnings(metadata: dict, analysis: dict) -> None:
    """Append structured findings to learnings.jsonl."""
    run_id = metadata["run_id"]

    # Metric entries
    for sid, info in analysis.get("by_style", {}).items():
        append_learning(
            {
                "source": "analyze_benchmark",
                "run_id": run_id,
                "type": "metric",
                "category": "style_score",
                "detail": (
                    f"{sid}: style={info['avg_style_score']:.0%} "
                    f"persona={info['avg_persona_score']:.0%} "
                    f"({info['count']} images)"
                ),
                "severity": "low",
            }
        )

    # Recommendations as findings
    for rec in analysis.get("recommendations", []):
        append_learning(
            {
                "source": "analyze_benchmark",
                "run_id": run_id,
                "type": "finding",
                "category": rec["category"],
                "detail": rec["detail"],
                "action": rec.get("action", ""),
                "severity": rec["severity"],
            }
        )

    # SBS metric
    sbs = analysis.get("sbs", {})
    if sbs.get("sample_size", 0) > 0:
        append_learning(
            {
                "source": "analyze_benchmark",
                "run_id": run_id,
                "type": "metric",
                "category": "sbs_score",
                "detail": (
                    f"SBS: identity={sbs['avg_identity']:.0%}  goal={sbs['avg_goal']:.0%}  "
                    f"quality={sbs['avg_quality']:.0%}  compound={sbs['avg_compound']:.0%}  "
                    f"({sbs['sample_size']} images)"
                ),
                "severity": "high" if sbs["avg_compound"] < 0.50 else "low",
            }
        )


def _print_summary(analysis: dict, bench_meta: dict) -> None:
    """Print human-readable summary to stdout."""
    total = analysis["total_entries"]
    ok = analysis["successful"]
    bench_run = bench_meta.get("run_id", "unknown")
    duration = bench_meta.get("duration_s", 0)
    duration_str = f"{duration / 3600:.1f}h" if duration > 3600 else f"{duration / 60:.0f}m"

    styles = analysis.get("by_style", {})
    n_styles = len(styles)

    print(f"\n=== Benchmark Analysis ({total} entries, {n_styles} styles) ===")
    print(f"Run: {bench_run} | Duration: {duration_str} | {ok}/{total} successful")

    # By style
    if styles:
        print("\nBy Style:")
        for sid, info in sorted(styles.items()):
            print(
                f"  {sid:18s} style={info['avg_style_score']:.0%}  "
                f"persona={info['avg_persona_score']:.0%}  "
                f"({info['count']} images)"
            )

    # By gender
    by_gender = analysis.get("by_gender", {})
    if by_gender:
        print("\nBy Gender:")
        for g, info in sorted(by_gender.items()):
            print(
                f"  {g:15s} persona={info['avg_persona_score']:.0%}  "
                f"style={info['avg_style_score']:.0%}  "
                f"({info['count']} images)"
            )

    # Most failed properties
    by_prop = analysis.get("by_property", {})
    failed_props = [(p, i) for p, i in by_prop.items() if i["failure_rate"] > 0.10]
    failed_props.sort(key=lambda x: -x[1]["failure_rate"])
    if failed_props:
        print("\nMost Failed Properties:")
        for p, info in failed_props[:7]:
            notes_str = ""
            if info.get("top_failure_notes"):
                top_note = info["top_failure_notes"][0]
                notes_str = f' — "{top_note["note"][:60]}" ({top_note["count"]}x)'
            print(
                f"  {p:15s} {info['failure_rate']:.0%} fail "
                f"({info['fail_count']}/{info['total']}){notes_str}"
            )

    # Color drift
    drift = analysis.get("color_drift", {})
    if drift:
        print("\nColor Drift:")
        for prop, info in sorted(drift.items()):
            print(
                f"  {prop:15s} avg proximity={info['avg_proximity']:.0%}  "
                f"{info['drift_direction']}  "
                f"({info['sample_size']} samples)"
            )

    # SBS scores
    sbs = analysis.get("sbs", {})
    if sbs.get("sample_size", 0) > 0:
        print(
            f"\nSide-by-side (§4.5) — {sbs['sample_size']} images:\n"
            f"  identity={sbs['avg_identity']:.0%}  goal={sbs['avg_goal']:.0%}  "
            f"quality={sbs['avg_quality']:.0%}  compound={sbs['avg_compound']:.0%}"
        )
        if sbs.get("worst"):
            print("  Worst by compound:")
            for w in sbs["worst"][:3]:
                print(
                    f"    {w['example']:25s} compound={w['compound']:.0%}  "
                    f"id={w['identity']:.0%}  goal={w['goal']:.0%}  "
                    f'"{w["reasoning"][:80]}"'
                )

    # Systematic failures
    systematic = analysis.get("systematic_failures", [])
    if systematic:
        print(f"\nSystematic Failures (>50% fail for gender x style): {len(systematic)} found")
        for sf in systematic[:5]:
            notes_str = ""
            if sf.get("top_notes"):
                notes_str = f' — "{sf["top_notes"][0][:50]}"'
            print(
                f"  {sf['property']} x {sf['gender']} x {sf['style']}  "
                f"{sf['failure_rate']:.0%} fail "
                f"({sf['fail_count']}/{sf['count']}){notes_str}"
            )

    # Worst performers
    worst = analysis.get("worst_performers", [])
    if worst:
        print(f"\nBottom {len(worst)} Performers:")
        for w in worst[:5]:
            failures_str = ", ".join(w["failures"][:4])
            print(
                f"  {w['example']:20s} x {w['style']:15s} "
                f"persona={w['persona_score']:.0%}  failures: {failures_str}"
            )

    # Recommendations
    recs = analysis.get("recommendations", [])
    if recs:
        high = sum(1 for r in recs if r["severity"] == "high")
        med = sum(1 for r in recs if r["severity"] == "medium")
        low = sum(1 for r in recs if r["severity"] == "low")
        print(f"\nRecommendations ({len(recs)} total — {high} high, {med} medium, {low} low):")
        for r in recs[:7]:
            sev = r["severity"].upper()
            print(f"  [{sev:4s}] {r['detail'][:80]}")
            if r.get("action"):
                print(f"         -> {r['action'][:80]}")

    count = len(recs)
    print(f"\nLearnings appended to reports/learnings.jsonl ({count + len(styles)} entries)")


if __name__ == "__main__":
    raise SystemExit("_analyze.py is a library — use learn_create.py instead.")
