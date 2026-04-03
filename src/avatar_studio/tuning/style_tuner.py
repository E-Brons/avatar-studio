#! python3
"""Style tuning agent — generate → classify → report loop.

Generates avatar portraits with a fixed persona but varying styles, then classifies
each image to verify that the style's system_prompt produces visually distinct output.
Designed for iterative prompt tuning: edit a style's system_prompt in styles.yml,
then re-run (or use --watch) to see whether the generated images are now correctly
classified.

Usage
-----
# Tune a single style, 3 runs, re-run automatically when styles.yml changes:
  python -m avatar_studio.tuning.style_tuner --style pixar_3d --runs 3 --watch

# Generate all styles × all genders × neutral expression, no classification:
  python -m avatar_studio.tuning.style_tuner --gender all --style all --expression neutral --refine none

# Evaluate all styles at once (2 runs each), classify by style:
  python -m avatar_studio.tuning.style_tuner --runs 2 --refine style

# Specify genders and expressions explicitly:
  python -m avatar_studio.tuning.style_tuner --style mobile_icon --gender male female --expression neutral thinking
"""

from __future__ import annotations

import argparse
import logging
import random as _random
import sys
import time
from pathlib import Path

import yaml

from avatar_studio.config.config import SETTINGS
from avatar_studio.pipeline.step_a_randomise_person import pick_demographics
from avatar_studio.pipeline.step_b_generate_cv import generate_advisor_profile
from avatar_studio.pipeline.step_c_select_features import build_avatar_charachter, select_features
from avatar_studio.pipeline.step_ef_generate_image import (
    EXPRESSION_IDS,
    EXPRESSIONS_YML,
    STYLES_YML,
    generate_avatar_image,
)
from avatar_studio.tuning.classify_expression import (
    classify_image_expression,
)
from avatar_studio.tuning.classify_persona import categorize_avatar_image
from avatar_studio.tuning.classify_style import StyleClassificationResult, classify_image_style

logger = logging.getLogger(__name__)

_GENDERS = ["male", "female", "non-binary"]
_GENDER_CHOICES = _GENDERS + ["all", "random"]
_EXPRESSION_CHOICES = EXPRESSION_IDS + ["all", "random"]


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


# ---------------------------------------------------------------------------
# Style loading (bypasses the module cache so --watch picks up edits)
# ---------------------------------------------------------------------------


def _load_styles_fresh() -> list[dict]:
    """Always reload styles.yml from disk (no cache)."""
    with open(STYLES_YML) as f:
        data = yaml.safe_load(f)
    return data["styles"]


# ---------------------------------------------------------------------------
# Image generation helpers
# ---------------------------------------------------------------------------


def _generate_for_style(
    style: dict,
    gender: str,
    seed: int,
    *,
    expression: str = "neutral",
    ollama_url: str,
    image_model: str,
    width: int,
    height: int,
    out_path: Path,
    session_dir: Path | None = None,
    avatar: dict | None = None,
    hard_type_gender: bool = False,
) -> tuple[bytes, dict]:
    """Generate a portrait for *style*.

    If *avatar* is provided it is used directly (fixed-persona mode).
    Otherwise a random persona is built from *gender* and *seed*.

    *session_dir* is where artifacts (persona.yml, prompt.txt, …) are written.
    Defaults to out_path.parent when not given.

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
        expression={"name": expression, "expressions_yml": EXPRESSIONS_YML},
        ollama_url=ollama_url,
        model=image_model,
        width=width,
        height=height,
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


def _fmt_pass(ok: bool) -> str:
    if ok:
        return f"{_GREEN}✓ PASS{_RESET}"
    return f"{_RED}✗ FAIL{_RESET}"


def _print_style_run_result(
    expected: str,
    result: StyleClassificationResult,
    gender: str,
    expression: str,
    run_idx: int,
) -> bool:
    correct = result.is_correct(expected)
    top3 = result.top_n(3)
    in_top2 = expected in top3[:2]

    top_score = result.scores.get(result.top_style_id, 0.0)
    expected_score = result.scores.get(expected, 0.0)

    status = _fmt_pass(correct)
    if not correct and in_top2:
        status = f"{_YELLOW}~ TOP-2{_RESET}"

    line = (
        f"  run {run_idx + 1} | {gender:<10} | expr={expression:<12} | "
        f"expected={expected:<20} classified={result.top_style_id:<20} ({top_score:.2f}) "
        f"| expected_score={expected_score:.2f} | {status}"
    )
    print(line)
    logger.info("[StyleTuner] %s", line)
    if result.reasoning:
        print(f"           reasoning: {result.reasoning}")
        logger.info("[StyleTuner]    reasoning: %s", result.reasoning)

    return correct


def _print_style_summary(style_id: str, correct: int, total: int) -> None:
    pct = correct / total * 100 if total else 0
    bar_len = 20
    filled = round(bar_len * correct / total) if total else 0
    bar = "#" * filled + "-" * (bar_len - filled)
    color = _GREEN if pct >= 80 else (_YELLOW if pct >= 50 else _RED)
    summary = (
        f"\n  {_BOLD}{style_id}{_RESET}: [{color}{bar}{_RESET}] "
        f"{color}{correct}/{total} ({pct:.0f}%){_RESET}"
    )
    print(summary)
    logger.info("[StyleTuner] SUMMARY %s: %d/%d (%.0f%%)", style_id, correct, total, pct)


# ---------------------------------------------------------------------------
# Persona file loading
# ---------------------------------------------------------------------------


def _load_personas_file(path: Path) -> list[dict]:
    """Load fixed personas from a YAML file.

    Returns a list of avatar dicts ready for _build_avatar_prompt.
    Each entry must have demographics, advisor, and features keys.
    """
    with open(path) as f:
        data = yaml.safe_load(f)
    personas = []
    for p in data["personas"]:
        avatar = build_avatar_charachter(p["advisor"], p["demographics"], p["features"])
        avatar["_id"] = p["id"]
        personas.append(avatar)
    return personas


# ---------------------------------------------------------------------------
# Resolve gender / expression / style lists from CLI args
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

    all_options: list of strings, or list of dicts when *key* is given.
    key:         dict key to match CLI values against (e.g. ``"id"`` for style dicts).
    predicate:   optional callable to filter all_options for the 'all'/'random' cases.
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
# Single tuning pass
# ---------------------------------------------------------------------------


def _run_tuning_pass(
    target_styles: list[dict],
    all_styles: list[dict],
    *,
    ollama_url: str,
    image_model: str,
    visual_model: str,
    genders: list[str],
    random_gender: bool = False,
    expressions: list[str],
    random_expression: bool = False,
    random_style: bool = False,
    refine: str = "none",
    runs: int,
    seed: int | None,
    width: int,
    height: int,
    tmp_dir: Path,
    fixed_personas: list[dict] | None = None,
    gender_personas: dict[str, dict] | None = None,
    hard_type_gender: bool = False,
) -> dict[str, tuple[int, int]]:
    """Run generate → (optionally) classify for each target style.

    When *fixed_personas* is provided each (style × expression) is generated
    once per persona (ignoring *runs* and *genders*).  Otherwise *runs* random
    personas are used, cycling through *genders* (or picking randomly when
    *random_gender* is True).

    *gender_personas* is an optional gender→avatar map produced by
    ``_generate_diverse_personas``.  When present, the pre-generated persona
    for each gender is used instead of building one on-the-fly from just
    demographics, giving richer and more diverse results.

    *refine* controls the classification step:
      - ``"none"``       — generate only, no classification
      - ``"style"``      — classify by visual style (existing behaviour)
      - ``"expression"`` — classify by expression (stub — not yet implemented)
      - ``"gender"``     — verify persona properties are visible in the image

    Returns {style_id: (correct_count, total_count)}.
    """
    results: dict[str, tuple[int, int]] = {}

    for style in target_styles:
        if random_style:
            style = _random.choice(target_styles)
        style_id = style["id"]
        print(f"\n{_BOLD}[style: {style_id}]{_RESET}")

        correct = 0
        total = 0

        for expression in expressions:
            if random_expression:
                expression = _random.choice(EXPRESSION_IDS)

            if len(expressions) > 1 or random_expression:
                print(f"  {_BOLD}expression: {expression}{_RESET}")

            # Build iterations as (label, seed, avatar).
            # Fixed-personas mode: one entry per persona (ignores runs/genders).
            # random_gender mode:  `runs` entries, each with a randomly-picked gender.
            # explicit genders:    one entry per gender × per run, so every gender
            #                      is always covered regardless of --runs.
            # gender_personas:     when present, use the pre-generated A→C persona for
            #                      each gender instead of a bare-demographics one.
            iterations: list[tuple[str, int, dict | None]]
            if fixed_personas:
                iterations = [
                    (p.get("_id", f"persona_{i}"), i, p) for i, p in enumerate(fixed_personas)
                ]
            elif random_gender:
                iterations = [
                    (
                        _random.choice(genders),
                        (seed + i) if seed is not None else _random.randint(1, 999999),
                        None,
                    )
                    for i in range(runs)
                ]
            else:
                # Each gender gets `runs` repetitions with independent seeds.
                iterations = [
                    (
                        gender,
                        (seed + run_idx) if seed is not None else _random.randint(1, 999999),
                        gender_personas.get(gender) if gender_personas else None,
                    )
                    for gender in genders
                    for run_idx in range(runs)
                ]

            for iter_idx, (label, run_seed, avatar) in enumerate(iterations):
                run_idx = iter_idx
                session_subdir = tmp_dir / f"{style_id}_{expression}_{label}"
                session_subdir.mkdir(parents=True, exist_ok=True)
                out_path = tmp_dir / f"{style_id}_{expression}_{label}.png"

                gender_label = label if not fixed_personas else label

                try:
                    logger.info(
                        "[StyleTuner] START — style=%s, expr=%s, persona=%s (seed=%s)",
                        style["id"],
                        expression,
                        label,
                        run_seed,
                    )
                    print(f"  generating {label} / {expression}…", end=" ", flush=True)
                    img_bytes, avatar_used = _generate_for_style(
                        style,
                        label,
                        seed=run_seed,
                        expression=expression,
                        ollama_url=ollama_url,
                        image_model=image_model,
                        width=width,
                        height=height,
                        out_path=out_path,
                        session_dir=session_subdir,
                        avatar=avatar,
                        hard_type_gender=hard_type_gender,
                    )
                    print("done")
                    logger.info("[StyleTuner] DONE  — %s", out_path)
                except Exception as exc:
                    print(f"FAILED — {exc}", file=sys.stderr)
                    total += 1
                    continue

                if refine == "none":
                    total += 1
                    continue

                if refine == "style":
                    try:
                        classification = classify_image_style(
                            img_bytes,
                            all_styles,
                            model=visual_model,
                            ollama_url=ollama_url,
                        )
                    except Exception as exc:
                        print(f"  classification FAILED — {exc}", file=sys.stderr)
                        logger.error("[StyleTuner] classification FAILED: %s", exc)
                        _flush_litellm_pool()
                        total += 1
                        continue

                    ok = _print_style_run_result(
                        style_id, classification, gender_label, expression, run_idx
                    )
                    if ok:
                        correct += 1
                    total += 1

                elif refine == "expression":
                    try:
                        classification = classify_image_expression(
                            img_bytes,
                            model=visual_model,
                            ollama_url=ollama_url,
                        )
                    except Exception as exc:
                        print(f"  expression classification FAILED — {exc}", file=sys.stderr)
                        logger.error("[StyleTuner] expression classification FAILED: %s", exc)
                        _flush_litellm_pool()
                        total += 1
                        continue

                    # Resolve the expected label for the current expression.
                    import yaml as _yaml  # noqa: PLC0415

                    with open(EXPRESSIONS_YML) as _f:
                        _exprs = {
                            e.get("id") or e["expression"].lower(): e
                            for e in _yaml.safe_load(_f)["expressions"]
                        }
                    expected_label = _exprs.get(expression, {}).get("expression", expression)

                    expected_score = classification.score_for(expected_label)
                    top_score = classification.top_score()
                    ok = classification.is_correct(expected_label, threshold=0.35)

                    sem_score = 0.0
                    if not ok:
                        _expr_data = _exprs.get(expression, {})
                        _valid = {expected_label.lower()} | {
                            s.lower() for s in _expr_data.get("synonyms", [])
                        }
                        sem_score = sum(
                            score
                            for name, score in classification.scores.items()
                            if name.lower() in _valid
                        )
                        # Semantic fallback: LLM per-phrase check, only when synonyms don't pass.
                        if sem_score < 0.35:
                            try:
                                from avatar_studio.tuning.classify_expression import (
                                    semantic_effective_score,  # noqa: PLC0415
                                )

                                lm_score = semantic_effective_score(
                                    classification.scores,
                                    expected_label,
                                    model=visual_model,
                                    ollama_url=ollama_url,
                                )
                                sem_score = max(sem_score, lm_score)
                            except Exception as exc:
                                logger.warning("[StyleTuner] semantic score failed: %s", exc)

                    semantic_ok = (not ok) and sem_score >= 0.35
                    visible = classification.is_visible(expected_label, threshold=0.35)
                    passed = ok or semantic_ok
                    if ok:
                        status = f"{_GREEN}✓ PASS{_RESET}"
                    elif semantic_ok:
                        status = f"{_GREEN}✓ SEMANTIC{_RESET}"
                    elif visible:
                        status = f"{_YELLOW}~ VISIBLE{_RESET}"
                    else:
                        status = f"{_RED}✗ FAIL{_RESET}"
                    sem_col = f" | semantic={sem_score:.2f}" if sem_score > 0.0 else ""
                    print(
                        f"  run {run_idx + 1} | {gender_label:<10} | expr={expression:<12} | "
                        f"expected={expected_label:<14} classified={classification.top_expression:<14} "
                        f"({top_score:.2f}) | expected_score={expected_score:.2f}{sem_col} | {status}"
                    )
                    if classification.reasoning:
                        print(f"           reasoning: {classification.reasoning}")
                    if passed:
                        correct += 1
                    total += 1

                elif refine == "gender":
                    persona = avatar_used.get("avatar_persona", avatar_used)
                    try:
                        report = categorize_avatar_image(
                            img_bytes,
                            persona,
                            model=visual_model,
                            ollama_url=ollama_url,
                        )
                    except Exception as exc:
                        print(f"  persona classification FAILED — {exc}", file=sys.stderr)
                        _flush_litellm_pool()
                        total += 1
                        continue

                    ok = report.score >= 0.6
                    status = _fmt_pass(ok)
                    print(
                        f"  run {run_idx + 1} | {gender_label:<10} | expr={expression:<12} | "
                        f"persona score={report.score:.0%} | {status}"
                    )
                    if report.failures():
                        print(f"           missing: {', '.join(report.failures())}")
                    if ok:
                        correct += 1
                    total += 1

        if refine != "none":
            _print_style_summary(style_id, correct, total)
        results[style_id] = (correct, total)

    return results


def _print_overall_summary(results: dict[str, tuple[int, int]]) -> None:
    total_correct = sum(c for c, _ in results.values())
    total_runs = sum(t for _, t in results.values())
    if not total_runs:
        return
    pct = total_correct / total_runs * 100
    color = _GREEN if pct >= 80 else (_YELLOW if pct >= 50 else _RED)
    overall = f"\n{_BOLD}Overall: {color}{total_correct}/{total_runs} ({pct:.0f}%) correctly classified{_RESET}\n"
    print(overall)
    logger.info("[StyleTuner] OVERALL: %d/%d (%.0f%%)", total_correct, total_runs, pct)


# ---------------------------------------------------------------------------
# Diverse persona generation (A→C pipeline, one persona per gender)
# ---------------------------------------------------------------------------


def _generate_diverse_personas(
    genders: list[str],
    base_seed: int | None,
    text_model: str,
    tmp_dir: Path,
    *,
    advisor_role: str = "Financial Advisor",
    hard_type_gender: bool = False,
) -> dict[str, dict]:
    """Run the full A→C pipeline once per gender and return a gender→avatar map.

    Each gender gets a different seed (base_seed + index) so the resulting
    personas are visually diverse.  The persona YAML for each gender is written
    to *tmp_dir/persona_{gender}.yml* and the avatar dict is returned keyed by
    gender string.

    Parameters
    ----------
    genders:
        Gender strings to generate personas for (e.g. ["male", "female", "non-binary"]).
    base_seed:
        Starting seed; persona i uses base_seed + i. None = random per persona.
    text_model:
        Ollama text model name in ``ollama/<model>`` format, routed via litellm.
    tmp_dir:
        Directory where ``persona_{gender}.yml`` files are written.
    advisor_role:
        Role string passed to Step B for CV generation.
    """
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
                    ollama_text_model=text_model,
                )
                advisor = {**advisor, **cv}
                features = select_features(
                    demographics,
                    advisor,
                    ollama_text_model=text_model,
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
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Style tuning agent: generate → classify → report loop.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--style",
        nargs="*",
        metavar="STYLE_ID",
        help=(
            "Style ID(s) to generate/tune. Special values: 'all' (default, all styles "
            "with a system_prompt), 'random' (use the random/no-system-prompt style)."
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
            f"'random' picks a random gender per run. Choices: {_GENDER_CHOICES}"
        ),
    )
    parser.add_argument(
        "--expression",
        nargs="*",
        choices=_EXPRESSION_CHOICES,
        metavar="EXPRESSION",
        default=None,
        help=(
            f"Expression(s) to generate. 'all' generates every expression. "
            f"'random' picks a random expression per image. "
            f"Default: neutral. Choices: {_EXPRESSION_CHOICES}"
        ),
    )
    parser.add_argument(
        "--refine",
        choices=["none", "gender", "style", "expression"],
        default="none",
        help=(
            "Run a classifier after each generated image and report accuracy. "
            "'none' (default) skips classification. "
            "'style' verifies the visual style. "
            "'gender' verifies persona properties are visible. "
            "'expression' verifies the expression (not yet implemented)."
        ),
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=_DEFAULT_RUNS,
        help=(
            f"Number of generate→refine→test iterations per (style × expression) "
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
        help="Re-run automatically whenever styles.yml is saved",
    )
    parser.add_argument(
        "--ollama-url",
        default="http://127.0.0.1:4096",
        help="Ollama server URL (default: http://127.0.0.1:4096)",
    )
    parser.add_argument(
        "--ollama-image-model",
        default=None,
        help=f"Ollama image model (default: {SETTINGS['default_image_gen_model']})",
    )
    parser.add_argument(
        "--ollama-text-model",
        default=None,
        help=f"Ollama text model for A→C persona generation (default: {SETTINGS['default_text_gen_model']})",
    )
    parser.add_argument(
        "--ollama-visual-desc-model",
        default=None,
        help=f"Ollama visual description model (default: {SETTINGS['default_visual_desc_model']})",
    )
    parser.add_argument(
        "--width", type=int, default=256, help="Image width in pixels (default: 256)"
    )
    parser.add_argument(
        "--height", type=int, default=256, help="Image height in pixels (default: 256)"
    )
    parser.add_argument(
        "--tmp-dir",
        default=None,
        metavar="DIR",
        help=(
            "Directory for generated images. "
            "Default: /tmp/avatar_studio/style-tuner/<timestamp>/ (from config session layout)"
        ),
    )
    parser.add_argument(
        "--personas-file",
        default=None,
        metavar="YAML",
        help=(
            "YAML file with fixed personas (skips random demographics). "
            "Each style × expression is generated once per persona."
        ),
    )
    parser.add_argument(
        "--hard-type-gender",
        action="store_true",
        default=False,
        help=(
            "Restrict gender-bucketed pools to the strict gender bucket only "
            "(no neutral crossover). male→male only, female→female only, "
            "non-binary→neutral only. Default: False."
        ),
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
    # Ensure the ollama/ prefix is present — litellm uses it for routing.
    if not text_model.startswith("ollama/"):
        text_model = f"ollama/{text_model}"
    visual_model = args.ollama_visual_desc_model or SETTINGS["default_visual_desc_model"]
    if not visual_model.startswith(("ollama/", "cli/")) and "ollama" not in visual_model.lower():
        visual_model = f"ollama/{visual_model}"

    # Fixed personas from file (optional).
    fixed_personas: list[dict] | None = None
    if args.personas_file:
        fixed_personas = _load_personas_file(Path(args.personas_file))
        print(f"  personas: {len(fixed_personas)} loaded from {args.personas_file}")

    # Output dir — always create a timestamped session subfolder so runs are
    # isolated and inspectable.  --tmp-dir is the *base* path; the actual
    # output lives in <base>/style-tuner/<timestamp>/.
    from datetime import datetime

    from avatar_studio.config.config import _name_to_filename

    base_dir = Path(args.tmp_dir) if args.tmp_dir else Path("/tmp/avatar_studio")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    tmp_dir = base_dir / _name_to_filename("style-tuner") / ts
    tmp_dir.mkdir(parents=True, exist_ok=True)
    print(f"  output dir: {tmp_dir}")

    # Tee logs to run.log inside the session dir so every run is self-contained.
    log_file = tmp_dir / "run.log"
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(getattr(logging, args.log_level))
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(file_handler)
    print(f"  log file  : {log_file}")

    # Generate one diverse persona per gender (A→C pipeline) before the loop.
    # This ensures all runs use phenotypically varied personas rather than simple
    # demographic picks with no CV/features context.
    _all_genders, _ = _resolve_options(args.gender, _GENDERS)
    print(f"\nGenerating diverse personas ({len(_all_genders)} gender(s))…")
    gender_personas = _generate_diverse_personas(
        _all_genders,
        args.seed,
        text_model,
        tmp_dir,
        hard_type_gender=args.hard_type_gender,
    )

    def _run_once() -> None:
        all_styles = _load_styles_fresh()
        target_styles, random_style = _resolve_options(
            args.style,
            all_styles,
            key="id",
            predicate=lambda s: s["id"] != "random" and s.get("system_prompt"),
        )
        genders, random_gender = _resolve_options(args.gender, _GENDERS)
        expressions, random_expression = _resolve_options(args.expression, EXPRESSION_IDS)

        if not target_styles:
            print("No matching styles found.", file=sys.stderr)
            return

        gender_count = 1 if random_gender else len(genders)
        expr_count = 1 if random_expression else len(expressions)
        total_images = (
            len(target_styles)
            * (len(fixed_personas) if fixed_personas else (gender_count * args.runs))
            * expr_count
        )
        styles_list = ", ".join(s["id"] for s in target_styles)
        gender_list = ", ".join(genders)
        expr_list = ", ".join(expressions)
        print(
            f"\n{'=' * 70}\n"
            f"  Style tuner\n"
            f"  styles      : {len(target_styles)} ({styles_list})\n"
            f"  genders     : {len(genders)} ({gender_list})\n"
            f"  expressions : {len(expressions)} ({expr_list})\n"
            f"  runs        : {args.runs} per (style × gender × expression)\n"
            f"  refine      : {args.refine}\n"
            f"  total images: ~{total_images}\n"
            f"  image_model : {image_model}\n"
            f"  visual_model: {visual_model}\n"
            f"{'=' * 70}"
        )

        results = _run_tuning_pass(
            target_styles,
            all_styles,
            ollama_url=args.ollama_url,
            image_model=image_model,
            visual_model=visual_model,
            genders=genders,
            random_gender=random_gender,
            expressions=expressions,
            random_expression=random_expression,
            random_style=random_style,
            refine=args.refine,
            runs=args.runs,
            seed=args.seed,
            width=args.width,
            height=args.height,
            fixed_personas=fixed_personas,
            gender_personas=gender_personas,
            tmp_dir=tmp_dir,
            hard_type_gender=args.hard_type_gender,
        )

        if args.refine != "none":
            _print_overall_summary(results)

        total_generated = sum(t for _, t in results.values())
        print(f"\nDone — {total_generated} image(s) generated → {tmp_dir}")

    if not args.watch:
        _run_once()
        return

    # --watch mode: poll styles.yml for changes
    print(f"Watching {STYLES_YML} for changes (Ctrl-C to stop)…\n")
    last_mtime = STYLES_YML.stat().st_mtime
    _run_once()

    try:
        while True:
            time.sleep(_WATCH_POLL_SECONDS)
            current_mtime = STYLES_YML.stat().st_mtime
            if current_mtime != last_mtime:
                last_mtime = current_mtime
                print(f"\n{'~' * 70}")
                print("  styles.yml changed — re-running…")
                print(f"{'~' * 70}")
                _run_once()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
