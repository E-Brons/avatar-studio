#! .venv/bin/python
"""Expression tuning agent — generate → classify → report loop.

Generates avatar portraits with a fixed persona but varying expressions, then
classifies each image to verify that the expression's FACS configuration
produces a visually recognisable result.

The classifier receives only human-readable expression *labels* — it cannot see
the FACS or description used during generation.  A run is considered
a PASS when the classifier's top expression matches the target label AND its
probability score is ≥ 35 %, OR when the sum of synonym-matching scores
reaches the threshold.

Designed for iterative prompt tuning: edit an expression's facs_action_units
or description in expressions.yml, then re-run (or use --watch) to see whether
the generated images are now correctly classified.

Usage
-----
# Tune a single expression, 3 runs, re-run automatically when expressions.yml changes:
  python -m avatar_studio.tuning.expression_tuner --expression thinking --runs 3 --watch

# Generate all expressions with a fixed style, no classification:
  python -m avatar_studio.tuning.expression_tuner --expression all --style cartoon --refine none

# Evaluate all expressions across all styles (2 runs each):
  python -m avatar_studio.tuning.expression_tuner --runs 2 --refine expression

# Specify expressions, styles, and genders explicitly:
  python -m avatar_studio.tuning.expression_tuner --expression thinking happy \\
      --style cartoon pixar_3d --gender male female
"""

from __future__ import annotations

import argparse
import logging
import random as _random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yaml

from config.config import SETTINGS
from pipeline.step_a_randomise_person import pick_demographics
from pipeline.step_b_generate_cv import generate_advisor_profile
from pipeline.step_c_select_features import build_avatar_charachter, select_features
from pipeline.step_ef_generate_image import (
    EXPRESSION_IDS,
    EXPRESSIONS_YML,
    STYLES_YML,
    generate_avatar_image,
)
from tuning.classify_expression import (
    ExpressionClassificationResult,
    classify_image_expression,
    semantic_effective_score,
)

logger = logging.getLogger(__name__)

_GENDERS = ["male", "female", "non-binary"]
_GENDER_CHOICES = _GENDERS + ["all", "random"]

# Pass threshold: the expected expression must reach this probability to count as PASS.
_PASS_THRESHOLD = 0.35


# ---------------------------------------------------------------------------
# litellm connection-pool flush
# (Ollama returns duplicate Transfer-Encoding: chunked headers for some
#  models, which poisons litellm's keep-alive pool.  Recreating the client
#  after each failure clears the corrupted connection.)
# ---------------------------------------------------------------------------


def _flush_litellm_pool() -> None:
    try:
        import httpx
        import litellm
        from litellm.llms.custom_httpx.http_handler import HTTPHandler

        no_keepalive = httpx.Limits(max_connections=10, max_keepalive_connections=0)
        fresh = HTTPHandler(client=httpx.Client(limits=no_keepalive, follow_redirects=True))
        litellm.module_level_client = fresh
        cache = getattr(litellm, "in_memory_llm_clients_cache", None)
        if cache is not None:
            fresh2 = HTTPHandler(client=httpx.Client(limits=no_keepalive, follow_redirects=True))
            try:
                cache.set_cache("httpx_client", fresh2)
                cache.set_cache("httpx_client_ssl_verify_None", fresh2)
            except Exception:
                pass
    except Exception:
        pass


_DEFAULT_SEED = None  # None = fully random seeds per run
_DEFAULT_RUNS = 1
_WATCH_POLL_SECONDS = 2
_GATEWAY_MAX_PARALLEL = 3  # matches llm_gateway/settings.json parallel.ollama
_print_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Expression and style loading (bypasses module cache so --watch picks up edits)
# ---------------------------------------------------------------------------


def _load_expressions_fresh() -> list[dict]:
    """Always reload expressions.yml from disk (no cache). Derives 'id' from 'expression' if absent."""
    with open(EXPRESSIONS_YML) as f:
        data = yaml.safe_load(f)
    return [{**e, "id": e.get("id") or e["expression"].lower()} for e in data["expressions"]]


def _load_styles_fresh() -> list[dict]:
    """Always reload styles.yml from disk (no cache)."""
    with open(STYLES_YML) as f:
        data = yaml.safe_load(f)
    return data["styles"]


def _expression_labels(expressions: list[dict]) -> list[str]:
    """Return the human-readable labels from an expression list."""
    return [e.get("expression", e["id"]) for e in expressions]


# ---------------------------------------------------------------------------
# Image generation helper
# ---------------------------------------------------------------------------


def _generate_for_expression(
    expression_id: str,
    style: dict,
    gender: str,
    seed: int,
    *,
    gateway_url: str,
    width: int,
    height: int,
    optimize: str = "normal",
    out_path: Path,
    session_dir: Path | None = None,
    avatar: dict | None = None,
    hard_type_gender: bool = False,
) -> tuple[bytes, dict]:
    """Generate a portrait for *expression_id* in *style*.

    If *avatar* is provided it is used directly (fixed-persona mode).
    Otherwise a random persona is built from *gender* and *seed*.

    Returns (image_bytes, avatar_used).
    """
    if avatar is None:
        demo = pick_demographics(seed=seed, hard_type_gender=hard_type_gender)
        demo["gender"] = gender
        advisor = {"role": "Financial Advisor"}
        avatar = build_avatar_charachter(advisor, demo)

    artifact_dir = session_dir if session_dir is not None else out_path.parent
    persona_path = artifact_dir / "persona.yml"
    with open(persona_path, "w") as f:
        yaml.dump(
            avatar["avatar_persona"],
            f,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )

    bg_color = avatar["avatar_persona"].get("style", {}).get("bg_color", "#F5F0E8")
    generate_avatar_image(
        persona_path,
        style={"name": style["id"], "bg_color": bg_color, "styles_yml": STYLES_YML},
        expression={"name": expression_id, "expressions_yml": EXPRESSIONS_YML},
        gateway_url=gateway_url,
        width=width,
        height=height,
        optimize=optimize,
        seed=seed,
        out_path=out_path,
        session_dir=artifact_dir,
    )
    return out_path.read_bytes(), avatar


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------

_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_RESET = "\033[0m"
_BOLD = "\033[1m"


def _fmt_pass(ok: bool, semantic: bool = False, visible: bool = False) -> str:
    if ok:
        return f"{_GREEN}✓ PASS{_RESET}"
    if semantic:
        return f"{_GREEN}✓ SEMANTIC{_RESET}"
    if visible:
        return f"{_YELLOW}~ VISIBLE{_RESET}"
    return f"{_RED}✗ FAIL{_RESET}"


def _print_expression_run_result(
    expected_label: str,
    result: ExpressionClassificationResult,
    gender: str,
    style_id: str,
    run_idx: int,
    threshold: float,
    semantic_score: float = 0.0,
) -> bool:
    """Print a single run result line and return True if PASS (exact or semantic)."""
    expected_score = result.score_for(expected_label)
    top_score = result.top_score()
    exact_ok = result.is_correct(expected_label, threshold)
    semantic_ok = (not exact_ok) and semantic_score >= threshold
    visible = result.is_visible(expected_label, threshold)
    passed = exact_ok or semantic_ok

    status = _fmt_pass(exact_ok, semantic=semantic_ok, visible=visible and not passed)

    sem_col = f" | semantic={semantic_score:.2f}" if semantic_score > 0.0 else ""
    line = (
        f"  run {run_idx + 1} | {gender:<10} | style={style_id:<20} | "
        f"expected={expected_label:<14} classified={result.top_expression:<14} ({top_score:.2f}) "
        f"| expected_score={expected_score:.2f}{sem_col} | {status}"
    )
    print(line)
    logger.info("[ExprTuner] %s", line)
    if result.reasoning:
        print(f"           reasoning: {result.reasoning}")
        logger.info("[ExprTuner]    reasoning: %s", result.reasoning)

    return passed


def _print_expression_summary(expr_id: str, correct: int, total: int) -> None:
    pct = correct / total * 100 if total else 0
    bar_len = 20
    filled = round(bar_len * correct / total) if total else 0
    bar = "#" * filled + "-" * (bar_len - filled)
    color = _GREEN if pct >= 80 else (_YELLOW if pct >= 50 else _RED)
    summary = (
        f"\n  {_BOLD}{expr_id}{_RESET}: [{color}{bar}{_RESET}] "
        f"{color}{correct}/{total} ({pct:.0f}%){_RESET}"
    )
    print(summary)
    logger.info("[ExprTuner] SUMMARY %s: %d/%d (%.0f%%)", expr_id, correct, total, pct)


def _print_overall_summary(results: dict[str, tuple[int, int]]) -> None:
    total_correct = sum(c for c, _ in results.values())
    total_runs = sum(t for _, t in results.values())
    if not total_runs:
        return
    pct = total_correct / total_runs * 100
    color = _GREEN if pct >= 80 else (_YELLOW if pct >= 50 else _RED)
    overall = (
        f"\n{_BOLD}Overall: {color}{total_correct}/{total_runs} "
        f"({pct:.0f}%) correctly classified{_RESET}\n"
    )
    print(overall)
    logger.info("[ExprTuner] OVERALL: %d/%d (%.0f%%)", total_correct, total_runs, pct)


# ---------------------------------------------------------------------------
# Resolve lists from CLI args
# ---------------------------------------------------------------------------


def _resolve_options(
    raw: list[str] | None,
    all_options: list,
    *,
    key: str | None = None,
    predicate=None,
) -> tuple[list, bool]:
    """Resolve a CLI option list to (resolved_list, use_random).

    Three modes:
      - None / 'all'   → all_options (filtered by predicate), use_random=False
      - 'random'       → all_options (filtered by predicate), use_random=True
      - [id, id, ...]  → matching subset of all_options,      use_random=False
    """
    get_id = (lambda x: x[key]) if key else (lambda x: x)
    base = [o for o in all_options if predicate(o)] if predicate else list(all_options)

    if not raw or "all" in raw:
        return base, False
    if "random" in raw:
        return base, True
    requested = set(raw)
    matched = [o for o in all_options if get_id(o) in requested]
    if not matched:
        logger.warning("No options matched: %s", raw)
    return matched, False


# ---------------------------------------------------------------------------
# Diverse persona generation (A→C pipeline, one persona per gender)
# ---------------------------------------------------------------------------


def _generate_diverse_personas(
    genders: list[str],
    base_seed: int | None,
    gateway_url: str,
    tmp_dir: Path,
    *,
    advisor_role: str = "Financial Advisor",
    hard_type_gender: bool = False,
) -> dict[str, dict]:
    """Run the full A→C pipeline once per gender and return a gender→avatar map."""
    personas: dict[str, dict] = {}

    for i, gender in enumerate(genders):
        seed = (base_seed + i) if base_seed is not None else _random.randint(1, 999999)
        print(f"  generating persona [{gender}] (seed={seed})…", end=" ", flush=True)
        try:
            demographics = pick_demographics(seed=seed, hard_type_gender=hard_type_gender)
            demographics["gender"] = gender

            advisor = {"role": advisor_role}
            features = None
            try:
                cv = generate_advisor_profile(
                    advisor_role,
                    demographics,
                    gateway_url=gateway_url,
                )
                advisor = {**advisor, **cv}
                features = select_features(
                    demographics,
                    advisor,
                    gateway_url=gateway_url,
                    hard_type_gender=hard_type_gender,
                )
            except Exception as exc:
                print(f"WARNING: A→C features failed for [{gender}]: {exc}", file=sys.stderr)
                logger.warning("[Personas] A→C failed for gender=%s: %s", gender, exc)

            avatar = build_avatar_charachter(advisor, demographics, features)

            persona_path = tmp_dir / f"persona_{gender}.yml"
            with open(persona_path, "w") as f:
                yaml.dump(
                    avatar["avatar_persona"],
                    f,
                    default_flow_style=False,
                    sort_keys=False,
                    allow_unicode=True,
                )

            personas[gender] = avatar
            print(f"done → {persona_path.name}")
        except Exception as exc:
            print(f"FAILED — {exc}", file=sys.stderr)
            logger.warning("[Personas] persona generation failed for gender=%s: %s", gender, exc)

    return personas


# ---------------------------------------------------------------------------
# Single tuning pass
# ---------------------------------------------------------------------------


def _run_tuning_pass(
    target_expressions: list[dict],
    all_expression_labels: list[str],
    *,
    styles: list[dict],
    random_style: bool = False,
    gateway_url: str,
    genders: list[str],
    random_gender: bool = False,
    random_expression: bool = False,
    refine: bool,
    runs: int,
    seed: int | None,
    width: int,
    height: int,
    optimize: str = "normal",
    tmp_dir: Path,
    gender_personas: dict[str, dict] | None = None,
    hard_type_gender: bool = False,
    threshold: float = _PASS_THRESHOLD,
) -> dict[str, tuple[int, int]]:
    """Run generate → (optionally) classify for each target expression.

    The outer loop is expressions; inner loops are styles × genders × runs.

    Returns {expression_id: (correct_count, total_count)}.
    """
    results: dict[str, tuple[int, int]] = {}

    for expr in target_expressions:
        if random_expression:
            expr = _random.choice(target_expressions)

        expr_id = expr["id"]
        expr_label = expr.get("expression", expr_id)
        expr_synonyms = {s.lower() for s in expr.get("synonyms", [])}
        print(f"\n{_BOLD}[expression: {expr_id}]{_RESET}")

        correct = 0
        total = 0

        for style in styles:
            if random_style:
                style = _random.choice(styles)
            style_id = style["id"]

            if len(styles) > 1 or random_style:
                print(f"  {_BOLD}style: {style_id}{_RESET}")

            # Build iterations as (gender_label, seed, avatar).
            iterations: list[tuple[str, int, dict | None]]
            if random_gender:
                iterations = [
                    (
                        _random.choice(genders),
                        (seed + i) if seed is not None else _random.randint(1, 999999),
                        None,
                    )
                    for i in range(runs)
                ]
            else:
                iterations = [
                    (
                        gender,
                        (seed + run_idx) if seed is not None else _random.randint(1, 999999),
                        gender_personas.get(gender) if gender_personas else None,
                    )
                    for gender in genders
                    for run_idx in range(runs)
                ]

            # ── Parallel image generation ────────────────────────────────
            # Submit all iterations to the pool (capped at gateway parallel limit).
            # Results are collected ordered by iter_idx so classification below
            # is unaffected.
            def _gen_one(args):
                _iter_idx, _gender, _run_seed, _avatar = args
                _style_id = style["id"]
                _session_subdir = tmp_dir / f"{expr_id}_{_style_id}_{_gender}_{_run_seed}"
                _session_subdir.mkdir(parents=True, exist_ok=True)
                _out_path = tmp_dir / f"{expr_id}_{_style_id}_{_gender}_{_run_seed}.png"
                logger.info(
                    "[ExprTuner] START — expr=%s, style=%s, gender=%s (seed=%s)",
                    expr_id,
                    _style_id,
                    _gender,
                    _run_seed,
                )
                with _print_lock:
                    print(f"  generating {_gender} / {_style_id}…", end=" ", flush=True)
                _img_bytes, _ = _generate_for_expression(
                    expr_id,
                    style,
                    _gender,
                    seed=_run_seed,
                    gateway_url=gateway_url,
                    width=width,
                    height=height,
                    optimize=optimize,
                    out_path=_out_path,
                    session_dir=_session_subdir,
                    avatar=_avatar,
                    hard_type_gender=hard_type_gender,
                )
                logger.info("[ExprTuner] DONE  — %s", _out_path)
                with _print_lock:
                    print("done")
                return _iter_idx, _gender, _run_seed, _out_path, _img_bytes

            gen_results: list[tuple | Exception] = [None] * len(iterations)
            with ThreadPoolExecutor(max_workers=_GATEWAY_MAX_PARALLEL) as pool:
                future_to_idx = {
                    pool.submit(_gen_one, (i, g, s, a)): i for i, (g, s, a) in enumerate(iterations)
                }
                for fut in as_completed(future_to_idx):
                    i = future_to_idx[fut]
                    try:
                        gen_results[i] = fut.result()
                    except Exception as exc:
                        gen_results[i] = exc

            # ── Process results (classification stays sequential) ─────────
            for iter_idx, result in enumerate(gen_results):
                if isinstance(result, Exception):
                    print(f"FAILED — {result}", file=sys.stderr)
                    total += 1
                    continue

                _, gender, run_seed, out_path, img_bytes = result

                if not refine:
                    total += 1
                    continue

                try:
                    classification = classify_image_expression(
                        img_bytes,
                        gateway_url=gateway_url,
                    )
                except Exception as exc:
                    print(f"  classification FAILED — {exc}", file=sys.stderr)
                    logger.error("[ExprTuner] classification FAILED: %s", exc)
                    _flush_litellm_pool()
                    total += 1
                    continue

                # Synonym score: fast set lookup against known synonyms.
                synonym_score = 0.0
                if not classification.is_correct(expr_label, threshold):
                    valid_names = {expr_label.lower()} | expr_synonyms
                    synonym_score = sum(
                        score
                        for name, score in classification.scores.items()
                        if name.lower() in valid_names
                    )

                # Semantic fallback: LLM per-phrase check, only when synonyms don't pass.
                sem_score = 0.0
                if (
                    not classification.is_correct(expr_label, threshold)
                    and synonym_score < threshold
                ):
                    try:
                        sem_score = semantic_effective_score(
                            classification.scores,
                            expr_label,
                            gateway_url=gateway_url,
                        )
                    except Exception as exc:
                        logger.warning("[ExprTuner] semantic score failed: %s", exc)

                ok = _print_expression_run_result(
                    expr_label,
                    classification,
                    gender,
                    style_id,
                    iter_idx,
                    threshold,
                    semantic_score=max(synonym_score, sem_score),
                )
                if ok:
                    correct += 1
                total += 1

        if refine:
            _print_expression_summary(expr_id, correct, total)
        results[expr_id] = (correct, total)

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Expression tuning agent: generate → classify → report loop.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--expression",
        nargs="*",
        metavar="EXPR_ID",
        help=(
            "Expression ID(s) to tune. Special values: 'all' (default, all expressions), "
            "'random' (pick randomly per image). "
            f"Choices: {EXPRESSION_IDS + ['all', 'random']}"
        ),
    )
    parser.add_argument(
        "--style",
        nargs="*",
        metavar="STYLE_ID",
        help=(
            "Style ID(s) to use during generation. 'all' uses all styles with a "
            "system_prompt. 'random' picks randomly. Default: first available style."
        ),
    )
    parser.add_argument(
        "--gender",
        nargs="*",
        choices=_GENDER_CHOICES,
        metavar="GENDER",
        default=None,
        help=(
            f"Gender(s) to generate. 'all' (default) cycles through all genders. "
            f"'random' picks randomly per run. Choices: {_GENDER_CHOICES}"
        ),
    )
    parser.add_argument(
        "--refine",
        choices=["none", "expression"],
        default="expression",
        help=(
            "Run the expression classifier after each image and report accuracy. "
            "'expression' (default) classifies and reports pass/fail. "
            "'none' skips classification (generate only)."
        ),
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=_PASS_THRESHOLD,
        help=(
            f"Minimum probability for the expected expression to count as PASS "
            f"(default: {_PASS_THRESHOLD})"
        ),
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=_DEFAULT_RUNS,
        help=(
            f"Number of generate→classify iterations per (expression × style × gender) "
            f"combination (default: {_DEFAULT_RUNS})"
        ),
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=_DEFAULT_SEED,
        help=f"Base demographics seed for reproducibility (default: {_DEFAULT_SEED})",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Re-run automatically whenever expressions.yml is saved",
    )
    parser.add_argument(
        "--ollama-url",
        default="http://127.0.0.1:4096",
        help="Ollama server URL (default: http://127.0.0.1:4096)",
    )
    parser.add_argument(
        "--ollama-image-model",
        default=None,
        help=f"Image generation model (default: {SETTINGS['default_image_gen_model']})",
    )
    parser.add_argument(
        "--ollama-text-model",
        default=None,
        help=f"Text model for A→C persona generation (default: {SETTINGS['default_text_gen_model']})",
    )
    parser.add_argument(
        "--ollama-visual-desc-model",
        default=None,
        help=f"Vision model for expression classification (default: {SETTINGS['default_visual_desc_model']})",
    )
    parser.add_argument(
        "--width", type=int, default=256, help="Image width in pixels (default: 256)"
    )
    parser.add_argument(
        "--height", type=int, default=256, help="Image height in pixels (default: 256)"
    )
    parser.add_argument(
        "--optimize",
        choices=["quality", "normal", "fast"],
        default="normal",
        help="Generation quality/speed trade-off (default: normal)",
    )
    parser.add_argument(
        "--tmp-dir",
        default=None,
        metavar="DIR",
        help=(
            "Base directory for generated images. "
            "Default: /tmp/avatar_studio/expression-tuner/<timestamp>/"
        ),
    )
    parser.add_argument(
        "--hard-type-gender",
        action="store_true",
        default=False,
        help=("Restrict gender-bucketed pools to the strict gender bucket only. Default: False."),
    )
    parser.add_argument(
        "--log-level",
        default="DEBUG",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: DEBUG)",
    )

    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s %(message)s")

    # Resolve model defaults
    image_model = args.ollama_image_model or SETTINGS["default_image_gen_model"].removeprefix(
        "ollama/"
    )
    text_model = args.ollama_text_model or SETTINGS["default_text_gen_model"]
    if not text_model.startswith("ollama/"):
        text_model = f"ollama/{text_model}"
    visual_model = args.ollama_visual_desc_model or SETTINGS["default_visual_desc_model"]
    if not visual_model.startswith(("ollama/", "cli/")) and "ollama" not in visual_model.lower():
        visual_model = f"ollama/{visual_model}"

    # Output dir — timestamped session subfolder.
    from datetime import datetime

    from config.config import _name_to_filename

    base_dir = Path(args.tmp_dir) if args.tmp_dir else Path("/tmp/avatar_studio")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    tmp_dir = base_dir / _name_to_filename("expression-tuner") / ts
    tmp_dir.mkdir(parents=True, exist_ok=True)
    print(f"  output dir: {tmp_dir}")

    # Tee logs to run.log inside the session dir.
    log_file = tmp_dir / "run.log"
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(getattr(logging, args.log_level))
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(file_handler)
    print(f"  log file  : {log_file}")

    # Generate one diverse persona per gender (A→C pipeline) before the loop.
    _all_genders, _ = _resolve_options(args.gender, _GENDERS)
    print(f"\nGenerating diverse personas ({len(_all_genders)} gender(s))…")
    gender_personas = _generate_diverse_personas(
        _all_genders,
        args.seed,
        args.ollama_url,
        tmp_dir,
        hard_type_gender=args.hard_type_gender,
    )

    def _run_once() -> None:
        all_expressions = _load_expressions_fresh()
        all_expression_labels = _expression_labels(all_expressions)
        all_styles = _load_styles_fresh()

        target_expressions, random_expression = _resolve_options(
            args.expression, all_expressions, key="id"
        )
        genders, random_gender = _resolve_options(args.gender, _GENDERS)
        target_styles, random_style = _resolve_options(
            args.style,
            all_styles,
            key="id",
            predicate=lambda s: s["id"] != "random" and s.get("system_prompt"),
        )
        # Default to the first available style if none specified and none resolved.
        if not target_styles:
            target_styles = [s for s in all_styles if s.get("system_prompt")][:1]
            if not target_styles:
                target_styles = all_styles[:1]

        if not target_expressions:
            print("No matching expressions found.", file=sys.stderr)
            return

        do_refine = args.refine == "expression"
        gender_count = 1 if random_gender else len(genders)
        style_count = 1 if random_style else len(target_styles)
        total_images = len(target_expressions) * style_count * gender_count * args.runs

        expr_list = ", ".join(e["id"] for e in target_expressions)
        style_list = ", ".join(s["id"] for s in target_styles)
        gender_list = ", ".join(genders)
        print(
            f"\n{'=' * 70}\n"
            f"  Expression tuner\n"
            f"  expressions : {len(target_expressions)} ({expr_list})\n"
            f"  styles      : {len(target_styles)} ({style_list})\n"
            f"  genders     : {len(genders)} ({gender_list})\n"
            f"  runs        : {args.runs} per (expression × style × gender)\n"
            f"  refine      : {args.refine}\n"
            f"  threshold   : {args.threshold:.0%}\n"
            f"  total images: ~{total_images}\n"
            f"  image_model : {image_model}\n"
            f"  visual_model: {visual_model}\n"
            f"  text_model  : {text_model}\n"
            f"{'=' * 70}"
        )

        results = _run_tuning_pass(
            target_expressions,
            all_expression_labels,
            styles=target_styles,
            random_style=random_style,
            gateway_url=args.ollama_url,
            genders=genders,
            random_gender=random_gender,
            random_expression=random_expression,
            refine=do_refine,
            runs=args.runs,
            seed=args.seed,
            width=args.width,
            height=args.height,
            optimize=args.optimize,
            gender_personas=gender_personas,
            tmp_dir=tmp_dir,
            hard_type_gender=args.hard_type_gender,
            threshold=args.threshold,
        )

        if do_refine:
            _print_overall_summary(results)

        total_generated = sum(t for _, t in results.values())
        print(f"\nDone — {total_generated} image(s) generated → {tmp_dir}")

    if not args.watch:
        _run_once()
        return

    # --watch mode: poll expressions.yml for changes
    print(f"Watching {EXPRESSIONS_YML} for changes (Ctrl-C to stop)…\n")
    last_mtime = EXPRESSIONS_YML.stat().st_mtime
    _run_once()

    try:
        while True:
            time.sleep(_WATCH_POLL_SECONDS)
            current_mtime = EXPRESSIONS_YML.stat().st_mtime
            if current_mtime != last_mtime:
                last_mtime = current_mtime
                print(f"\n{'~' * 70}")
                print("  expressions.yml changed — re-running…")
                print(f"{'~' * 70}")
                _run_once()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
