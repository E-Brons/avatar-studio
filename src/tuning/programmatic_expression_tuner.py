#! .venv/bin/python
"""Programmatic expression tuner — generate → classify → (optionally) improve loop.

Generates programmatic avatar PNGs for each (expression × style × seed), classifies
them with the vision model, and reports pass rates.  With ``--improve``, it searches
for better component-option combos when pass rates are below ``--improve-threshold``,
and with ``--apply`` writes the improvements back to expression_mapper.py.

Usage
-----
# Tune all expressions for a random style, 3 seeds each:
  avatar-programmatic-expression-tuner --style random --runs 3

# Tune happiness/surprise for toon-head, run improvement search:
  avatar-programmatic-expression-tuner --style toon-head --expression happiness surprise \\
      --runs 5 --improve

# Tune all styles, apply best combos found:
  avatar-programmatic-expression-tuner --style all --runs 3 --improve --apply
"""

from __future__ import annotations

import argparse
import logging
import random as _random
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from itertools import product
from pathlib import Path

import yaml

from pipeline.render.programmatic.expression_mapper import EXPRESSION_OPTIONS
from pipeline.render.programmatic.svg_generator import create_programmatic_avatar, svg_to_png
from tuning.classify_expression import (
    classify_image_expression,
    semantic_effective_score,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PA_STYLES = ["toon-head", "avataaars", "bottts", "micah", "opeeps"]
_EXPRESSIONS = ["happiness", "surprise", "anger", "sadness", "contempt"]
_PASS_THRESHOLD = 0.35
_IMPROVE_THRESHOLD = 0.60  # trigger search when baseline is below this
_MAX_IMPROVE_TRIES = 20  # random combos to test per low-pass expression
_GATEWAY_MAX_PARALLEL = 3
_print_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Synonym loader (from assets/expressions/expressions.yml)
# ---------------------------------------------------------------------------


def _load_synonyms() -> dict[str, set[str]]:
    """Return {lower-cased expression: {lower-cased synonyms}} from expressions.yml."""
    candidate = Path(__file__).resolve()
    for _ in range(8):
        candidate = candidate.parent
        yml = candidate / "assets" / "expressions" / "expressions.yml"
        if yml.exists():
            data = yaml.safe_load(yml.read_text())
            out: dict[str, set[str]] = {}
            for entry in data.get("expressions", []):
                name = entry.get("expression", "").lower()
                syns = {s.lower() for s in entry.get("synonyms", [])}
                if name:
                    out[name] = syns
            return out
    logger.warning("expressions.yml not found — synonyms disabled")
    return {}


_SYNONYMS: dict[str, set[str]] = _load_synonyms()


# ---------------------------------------------------------------------------
# Available component options per style (from DiceBear schemas + opeeps API)
# ---------------------------------------------------------------------------

_AVAILABLE_OPTIONS: dict[str, dict[str, list[str]]] = {
    "toon-head": {
        "eyes": ["happy", "wide", "bow", "humble", "wink"],
        "mouth": ["laugh", "angry", "agape", "smile", "sad"],
        "eyebrows": ["raised", "angry", "happy", "sad", "neutral"],
    },
    "avataaars": {
        "eyes": [
            "closed",
            "cry",
            "default",
            "eyeRoll",
            "happy",
            "hearts",
            "side",
            "squint",
            "surprised",
            "winkWacky",
            "wink",
            "xDizzy",
        ],
        "mouth": [
            "concerned",
            "default",
            "disbelief",
            "eating",
            "grimace",
            "sad",
            "screamOpen",
            "serious",
            "smile",
            "tongue",
            "twinkle",
            "vomit",
        ],
        "eyebrows": [
            "angryNatural",
            "defaultNatural",
            "flatNatural",
            "frownNatural",
            "raisedExcitedNatural",
            "sadConcernedNatural",
            "unibrowNatural",
            "upDownNatural",
            "angry",
            "default",
            "raisedExcited",
            "sadConcerned",
            "upDown",
        ],
    },
    "bottts": {
        "eyes": [
            "bulging",
            "dizzy",
            "eva",
            "frame1",
            "frame2",
            "glow",
            "happy",
            "hearts",
            "robocop",
            "round",
            "roundFrame01",
            "roundFrame02",
            "sensor",
            "shade01",
        ],
        "mouth": [
            "bite",
            "diagram",
            "grill01",
            "grill02",
            "grill03",
            "smile01",
            "smile02",
            "square01",
            "square02",
        ],
    },
    "micah": {
        "eyes": ["eyes", "round", "eyesShadow", "smiling", "smilingShadow"],
        "mouth": ["surprised", "laughing", "nervous", "smile", "sad", "pucker", "frown", "smirk"],
        "eyebrows": ["up", "down", "eyelashesUp", "eyelashesDown"],
    },
    "opeeps": {
        "eye": ["Round", "Smiling", "Ellipse", "EllipseShadow"],
        "mouth": ["Smile", "Laughing", "Surprised", "Frown", "Sad", "Smirk"],
        "eyebrow": ["Up", "EyelashesUp", "Down", "EyelashesDown"],
    },
}

# ---------------------------------------------------------------------------
# ANSI colours
# ---------------------------------------------------------------------------

_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_RESET = "\033[0m"
_BOLD = "\033[1m"


def _fmt_pass(ok: bool, semantic: bool = False) -> str:
    if ok:
        return f"{_GREEN}✓ PASS{_RESET}"
    if semantic:
        return f"{_GREEN}✓ SEMANTIC{_RESET}"
    return f"{_RED}✗ FAIL{_RESET}"


# ---------------------------------------------------------------------------
# Image generation helpers
# ---------------------------------------------------------------------------


def _make_seed_name(base_seed: int, run_idx: int) -> str:
    """Derive a deterministic avatar name from a numeric seed + run index."""
    combined = base_seed + run_idx * 1000
    _random.seed(combined)
    first = _random.choice(
        [
            "Alice",
            "Bob",
            "Carlos",
            "Diana",
            "Emre",
            "Fiona",
            "Gao",
            "Hira",
            "Ivan",
            "Julia",
            "Kenji",
            "Luna",
            "Marco",
            "Nadia",
            "Omar",
            "Priya",
            "Quinn",
            "Rosa",
            "Sam",
            "Tara",
            "Uma",
            "Victor",
            "Wren",
            "Xiu",
            "Yuki",
            "Zara",
        ]
    )
    last = _random.choice(
        [
            "Smith",
            "Johnson",
            "Lee",
            "Brown",
            "Kim",
            "Patel",
            "Garcia",
            "Wang",
            "Chen",
            "Singh",
            "Ahmed",
            "Yamamoto",
            "Gonzalez",
            "Muller",
            "Dupont",
        ]
    )
    return f"{first} {last}"


def _generate_pa_png(
    style: str,
    expression: str,
    seed: int,
    run_idx: int,
    out_dir: Path,
    options_override: dict | None = None,
) -> tuple[bytes, Path]:
    """Generate a programmatic avatar PNG and return (bytes, path)."""
    name = _make_seed_name(seed, run_idx)
    # Build a unique filename
    safe_expr = expression.replace(" ", "_")
    fname = f"{style}_{safe_expr}_{seed}_{run_idx}.png"
    svg_path = out_dir / fname.replace(".png", ".svg")
    png_path = out_dir / fname

    # create_programmatic_avatar writes the SVG; then convert to PNG
    # We pass expression only when no override is given (mapper handles it).
    # When override is given we pass options directly via a temporary approach:
    # call svg_generator with expression=None and inject options manually.
    if options_override is not None:
        # Temporarily patch: generate with expression=None then apply override
        # via the demographics trick — but actually the cleanest way is to call
        # create_programmatic_avatar with expression=None and pass options in
        # demographics.  Since demographics only extracts bg_color, we need a
        # different approach.  We'll call it with expression=None and the
        # options_override injected by monkey-patching EXPRESSION_OPTIONS.
        _orig = EXPRESSION_OPTIONS.get(style, {}).get(expression)
        EXPRESSION_OPTIONS.setdefault(style, {})[expression] = options_override
        try:
            create_programmatic_avatar(name, svg_path, size=256, expression=expression, style=style)
        finally:
            if _orig is not None:
                EXPRESSION_OPTIONS[style][expression] = _orig
            else:
                EXPRESSION_OPTIONS[style].pop(expression, None)
    else:
        create_programmatic_avatar(name, svg_path, size=256, expression=expression, style=style)

    svg_bytes = svg_path.read_bytes()
    svg_to_png(svg_bytes, png_path)
    return png_path.read_bytes(), png_path


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def _score_image(
    img_bytes: bytes,
    expr_label: str,
    expr_synonyms: set[str],
    gateway_url: str,
    threshold: float,
) -> tuple[bool, float, str]:
    """Classify an image and return (passed, effective_score, top_label)."""
    result = classify_image_expression(img_bytes, gateway_url=gateway_url)
    top_label = result.top_expression or "?"

    exact_ok = result.is_correct(expr_label, threshold)
    if exact_ok:
        return True, result.score_for(expr_label), top_label

    valid_names = {expr_label.lower()} | expr_synonyms
    synonym_score = sum(
        score for name, score in result.scores.items() if name.lower() in valid_names
    )
    if synonym_score >= threshold:
        return True, synonym_score, top_label

    try:
        sem_score = semantic_effective_score(result.scores, expr_label, gateway_url=gateway_url)
    except Exception:
        sem_score = 0.0

    passed = max(synonym_score, sem_score) >= threshold
    return passed, max(result.score_for(expr_label), synonym_score, sem_score), top_label


# ---------------------------------------------------------------------------
# Baseline evaluation
# ---------------------------------------------------------------------------


def _run_baseline(
    style: str,
    expressions: list[str],
    runs: int,
    seed: int,
    tmp_dir: Path,
    gateway_url: str,
    threshold: float,
) -> dict[str, tuple[int, int]]:
    """Generate + classify baseline images.  Returns {expr: (correct, total)}."""
    results: dict[str, tuple[int, int]] = {}

    for expr in expressions:
        print(f"\n{_BOLD}[{style} / {expr}]{_RESET}", flush=True)
        synonyms: set[str] = _SYNONYMS.get(expr.lower(), set())
        expr_label = expr.title()  # e.g. "happiness" → "Happiness"

        # Build generation tasks: (run_idx, seed)
        tasks = [(i, seed + i) for i in range(runs)]

        # Parallel generation
        gen_results: list[tuple | Exception] = [None] * runs  # type: ignore[assignment]
        with ThreadPoolExecutor(max_workers=_GATEWAY_MAX_PARALLEL) as pool:
            future_map = {
                pool.submit(_generate_pa_png, style, expr, s, i, tmp_dir): i for i, s in tasks
            }
            for fut in as_completed(future_map):
                idx = future_map[fut]
                try:
                    gen_results[idx] = fut.result()
                except Exception as exc:
                    gen_results[idx] = exc

        correct = 0
        total = 0
        for run_idx, res in enumerate(gen_results):
            if isinstance(res, Exception):
                print(f"  gen FAILED run {run_idx + 1}: {res}", file=sys.stderr, flush=True)
                total += 1
                continue

            img_bytes, png_path = res
            try:
                passed, score, top_label = _score_image(
                    img_bytes, expr_label, synonyms, gateway_url, threshold
                )
            except Exception as exc:
                print(f"  classify FAILED run {run_idx + 1}: {exc}", file=sys.stderr, flush=True)
                total += 1
                continue

            status = _fmt_pass(passed)
            with _print_lock:
                print(
                    f"  run {run_idx + 1} | score={score:.2f} | {status} | top={top_label} | {png_path.name}",
                    flush=True,
                )
            if passed:
                correct += 1
            total += 1

        pct = correct / total * 100 if total else 0
        color = _GREEN if pct >= 80 else (_YELLOW if pct >= 50 else _RED)
        print(f"  baseline: {color}{correct}/{total} ({pct:.0f}%){_RESET}", flush=True)
        results[expr] = (correct, total)

    return results


# ---------------------------------------------------------------------------
# Improvement search
# ---------------------------------------------------------------------------


def _build_combos(style: str, max_tries: int) -> list[dict]:
    """Return up to *max_tries* random combinations of available options for *style*."""
    avail = _AVAILABLE_OPTIONS.get(style, {})
    if not avail:
        return []

    keys = list(avail.keys())
    all_values = [avail[k] for k in keys]

    # Full enumeration if small enough, else random sample
    total = 1
    for vals in all_values:
        total *= len(vals)

    if total <= max_tries:
        combos = [dict(zip(keys, combo)) for combo in product(*all_values)]
    else:
        seen: set[tuple] = set()
        combos = []
        for _ in range(max_tries * 10):
            if len(combos) >= max_tries:
                break
            pick = tuple(_random.choice(v) for v in all_values)
            if pick not in seen:
                seen.add(pick)
                combos.append(dict(zip(keys, pick)))

    # DiceBear expects lists for options, not plain strings
    # toon-head/avataaars/bottts/micah wrap values in lists; opeeps uses plain strings
    if style != "opeeps":
        combos = [{k: [v] for k, v in c.items()} for c in combos]

    return combos


def _score_combo(
    style: str,
    expr: str,
    combo: dict,
    improve_runs: int,
    seed: int,
    tmp_dir: Path,
    gateway_url: str,
    threshold: float,
    expr_label: str,
    synonyms: set[str],
) -> float:
    """Generate *improve_runs* images for *combo* and return average pass rate."""
    tasks = [(i, seed + 10000 + i) for i in range(improve_runs)]
    results: list[tuple | Exception] = [None] * improve_runs  # type: ignore[assignment]

    with ThreadPoolExecutor(max_workers=_GATEWAY_MAX_PARALLEL) as pool:
        future_map = {
            pool.submit(_generate_pa_png, style, expr, s, i, tmp_dir, combo): i for i, s in tasks
        }
        for fut in as_completed(future_map):
            idx = future_map[fut]
            try:
                results[idx] = fut.result()
            except Exception as exc:
                results[idx] = exc

    passed = 0
    total = 0
    for res in results:
        if isinstance(res, Exception):
            total += 1
            continue
        img_bytes, _ = res
        try:
            ok, _, _ = _score_image(img_bytes, expr_label, synonyms, gateway_url, threshold)
        except Exception:
            ok = False
        if ok:
            passed += 1
        total += 1

    return passed / total if total else 0.0


def _run_improvement(
    style: str,
    expressions: list[str],
    baseline: dict[str, tuple[int, int]],
    improve_threshold: float,
    max_improve_tries: int,
    improve_runs: int,
    seed: int,
    tmp_dir: Path,
    gateway_url: str,
    threshold: float,
    apply_changes: bool,
) -> dict[str, dict]:
    """Search for better component combos for low-pass expressions.

    Returns {expr: best_combo} for any expression where improvement was found.
    """
    improvements: dict[str, dict] = {}

    for expr in expressions:
        correct, total = baseline.get(expr, (0, 0))
        base_rate = correct / total if total else 0.0
        if base_rate >= improve_threshold:
            print(
                f"\n  [{expr}] pass={base_rate:.0%} ≥ threshold — skipping improvement search",
                flush=True,
            )
            continue

        print(
            f"\n{_BOLD}[improvement search: {style} / {expr} | baseline={base_rate:.0%}]{_RESET}",
            flush=True,
        )
        combos = _build_combos(style, max_improve_tries)
        if not combos:
            print(f"  no option variants available for style={style}", flush=True)
            continue

        expr_label = expr.title()
        synonyms: set[str] = _SYNONYMS.get(expr.lower(), set())
        best_rate = base_rate
        best_combo: dict | None = None

        for i, combo in enumerate(combos):
            rate = _score_combo(
                style,
                expr,
                combo,
                improve_runs,
                seed,
                tmp_dir,
                gateway_url,
                threshold,
                expr_label,
                synonyms,
            )
            color = _GREEN if rate > best_rate else (_YELLOW if rate == best_rate else _RED)
            print(
                f"  try {i + 1:02d}/{len(combos)} | rate={color}{rate:.0%}{_RESET}"
                f" | {_fmt_combo(combo)}"
            )
            if rate > best_rate:
                best_rate = rate
                best_combo = combo

        if best_combo is not None:
            print(
                f"  {_GREEN}IMPROVED{_RESET}: {expr} {base_rate:.0%} → {best_rate:.0%}"
                f" | {_fmt_combo(best_combo)}"
            )
            improvements[expr] = best_combo
            if apply_changes:
                _apply_improvement(style, expr, best_combo)
        else:
            print(f"  no improvement found for {expr} (best={best_rate:.0%})", flush=True)

    return improvements


def _fmt_combo(combo: dict) -> str:
    """Human-readable combo string."""
    return " | ".join(f"{k}={v[0] if isinstance(v, list) else v}" for k, v in combo.items())


# ---------------------------------------------------------------------------
# Apply improvements to expression_mapper.py
# ---------------------------------------------------------------------------


def _apply_improvement(style: str, expression: str, combo: dict) -> None:
    """Write the best combo back into expression_mapper.py for (style, expression)."""
    mapper_path = (
        Path(__file__).resolve().parent.parent
        / "pipeline"
        / "render"
        / "programmatic"
        / "expression_mapper.py"
    )
    if not mapper_path.exists():
        logger.error("expression_mapper.py not found at %s", mapper_path)
        return

    text = mapper_path.read_text()
    # Serialise combo as a Python dict literal
    combo_repr = "{" + ", ".join(f'"{k}": {repr(v)}' for k, v in combo.items()) + "}"

    # Pattern: find the expression key inside the style block and replace its value
    # e.g.: "happiness": {"eyes": ["happy"], "mouth": ["laugh"], "eyebrows": ["happy"]},
    pattern = r'("' + re.escape(expression) + r'"\s*:\s*)\{[^}]*\}'

    # Simple approach: find the style block, then replace within it
    style_block_pat = r'("' + re.escape(style) + r'"\s*:\s*\{)(.*?)(\n    \})'
    match = re.search(style_block_pat, text, re.DOTALL)
    if not match:
        logger.error("Could not find style block for %r in expression_mapper.py", style)
        return

    block_inner = match.group(2)
    new_inner = re.sub(
        pattern,
        r"\g<1>" + combo_repr,
        block_inner,
    )
    new_text = text[: match.start(2)] + new_inner + text[match.end(2) :]
    mapper_path.write_text(new_text)
    print(
        f"  {_BOLD}[applied]{_RESET} expression_mapper.py updated: "
        f"{style}/{expression} → {_fmt_combo(combo)}"
    )
    logger.info("[PA tuner] applied: %s/%s → %s", style, expression, combo)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def _print_summary(style: str, results: dict[str, tuple[int, int]]) -> None:
    total_correct = sum(c for c, _ in results.values())
    total_runs = sum(t for _, t in results.values())
    pct = total_correct / total_runs * 100 if total_runs else 0
    color = _GREEN if pct >= 80 else (_YELLOW if pct >= 50 else _RED)
    print(
        f"\n{_BOLD}Summary [{style}]{_RESET}: "
        f"{color}{total_correct}/{total_runs} ({pct:.0f}%){_RESET}"
    )
    for expr, (c, t) in results.items():
        p = c / t * 100 if t else 0
        col = _GREEN if p >= 80 else (_YELLOW if p >= 50 else _RED)
        bar = "#" * round(20 * c / t) + "-" * (20 - round(20 * c / t)) if t else "-" * 20
        print(f"  {expr:<12} [{col}{bar}{_RESET}] {col}{c}/{t} ({p:.0f}%){_RESET}", flush=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Programmatic expression tuner: generate → classify → report.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--style",
        nargs="*",
        metavar="STYLE",
        help=(
            f"Programmatic style(s). 'all' uses all 5 styles. 'random' picks one. "
            f"Choices: {_PA_STYLES + ['all', 'random']}"
        ),
    )
    parser.add_argument(
        "--expression",
        nargs="*",
        metavar="EXPR",
        help=(f"Expression(s) to tune. Default: all. Choices: {_EXPRESSIONS + ['all', 'random']}"),
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        help="Number of diverse seeds to generate per (expression × style) (default: 3)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Base seed for reproducibility (default: random)",
    )
    parser.add_argument(
        "--improve",
        action="store_true",
        default=False,
        help="Search for better component options when pass rate is below --improve-threshold",
    )
    parser.add_argument(
        "--improve-threshold",
        type=float,
        default=_IMPROVE_THRESHOLD,
        help=f"Pass rate below which improvement search is triggered (default: {_IMPROVE_THRESHOLD})",
    )
    parser.add_argument(
        "--improve-runs",
        type=int,
        default=3,
        help="Images per candidate combo during improvement search (default: 3)",
    )
    parser.add_argument(
        "--max-improve-tries",
        type=int,
        default=_MAX_IMPROVE_TRIES,
        help=f"Max combos to try per low-pass expression (default: {_MAX_IMPROVE_TRIES})",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Write improved options back to expression_mapper.py",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=_PASS_THRESHOLD,
        help=f"Min classifier score to count as PASS (default: {_PASS_THRESHOLD})",
    )
    parser.add_argument(
        "--ollama-url",
        default="http://127.0.0.1:4096",
        help="LLM Gateway URL (default: http://127.0.0.1:4096)",
    )
    parser.add_argument(
        "--tmp-dir",
        default=None,
        metavar="DIR",
        help="Output directory (default: /tmp/avatar_studio/pa-expression-tuner/<timestamp>/)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO)",
    )

    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s %(message)s")

    # Resolve styles
    raw_styles = args.style
    if not raw_styles or "all" in raw_styles:
        styles = list(_PA_STYLES)
        random_style = False
    elif "random" in raw_styles:
        styles = list(_PA_STYLES)
        random_style = True
    else:
        styles = [s for s in raw_styles if s in _PA_STYLES]
        if not styles:
            print(
                f"No valid styles in {raw_styles}. Valid: {_PA_STYLES}", file=sys.stderr, flush=True
            )
            sys.exit(1)
        random_style = False

    if random_style:
        styles = [_random.choice(styles)]

    # Resolve expressions
    raw_exprs = args.expression
    if not raw_exprs or "all" in raw_exprs:
        expressions = list(_EXPRESSIONS)
    elif "random" in raw_exprs:
        expressions = [_random.choice(_EXPRESSIONS)]
    else:
        expressions = [e for e in raw_exprs if e in _EXPRESSIONS]
        if not expressions:
            print(
                f"No valid expressions in {raw_exprs}. Valid: {_EXPRESSIONS}",
                file=sys.stderr,
                flush=True,
            )
            sys.exit(1)

    base_seed = args.seed if args.seed is not None else _random.randint(1, 999999)

    # Output dir
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_dir = Path(args.tmp_dir) if args.tmp_dir else Path("/tmp/avatar_studio")
    tmp_dir = base_dir / "pa-expression-tuner" / ts
    tmp_dir.mkdir(parents=True, exist_ok=True)

    log_file = tmp_dir / "run.log"
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(getattr(logging, args.log_level))
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(file_handler)

    print(f"\n{'=' * 70}", flush=True)
    print("  Programmatic Expression Tuner", flush=True)
    print(f"  styles     : {', '.join(styles)}", flush=True)
    print(f"  expressions: {', '.join(expressions)}", flush=True)
    print(f"  runs       : {args.runs} per (expression × style)", flush=True)
    print(f"  seed       : {base_seed}", flush=True)
    print(
        f"  improve    : {args.improve}"
        + (f" (threshold={args.improve_threshold:.0%})" if args.improve else "")
    )
    print(f"  apply      : {args.apply}", flush=True)
    print(f"  output     : {tmp_dir}", flush=True)
    print(f"{'=' * 70}", flush=True)

    overall_results: dict[str, dict[str, tuple[int, int]]] = {}

    for style in styles:
        print(f"\n{_BOLD}{'─' * 60}{_RESET}", flush=True)
        print(f"{_BOLD}Style: {style}{_RESET}", flush=True)
        print(f"{'─' * 60}", flush=True)

        style_dir = tmp_dir / style
        style_dir.mkdir(parents=True, exist_ok=True)

        baseline = _run_baseline(
            style=style,
            expressions=expressions,
            runs=args.runs,
            seed=base_seed,
            tmp_dir=style_dir,
            gateway_url=args.ollama_url,
            threshold=args.threshold,
        )

        if args.improve:
            _run_improvement(
                style=style,
                expressions=expressions,
                baseline=baseline,
                improve_threshold=args.improve_threshold,
                max_improve_tries=args.max_improve_tries,
                improve_runs=args.improve_runs,
                seed=base_seed,
                tmp_dir=style_dir,
                gateway_url=args.ollama_url,
                threshold=args.threshold,
                apply_changes=args.apply,
            )

        _print_summary(style, baseline)
        overall_results[style] = baseline

    # Overall summary across all styles
    if len(styles) > 1:
        print(f"\n{_BOLD}{'=' * 70}{_RESET}", flush=True)
        print(f"{_BOLD}Overall across all styles:{_RESET}", flush=True)
        for style, res in overall_results.items():
            c = sum(x for x, _ in res.values())
            t = sum(x for _, x in res.values())
            pct = c / t * 100 if t else 0
            col = _GREEN if pct >= 80 else (_YELLOW if pct >= 50 else _RED)
            print(f"  {style:<15} {col}{c}/{t} ({pct:.0f}%){_RESET}", flush=True)

    print(f"\nDone → {tmp_dir}", flush=True)


if __name__ == "__main__":
    main()
