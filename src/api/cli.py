#! .venv/bin/python
"""Avatar studio — CLI entry point.

Run avatar generation pipelines from the command line.

Usage
-----
  avatar-studio generate --advisor path/to/advisor.yml --out-dir out/
  avatar-studio stage-b --role "Financial Advisor" ...
"""

import argparse
import logging
import sys
from pathlib import Path

import yaml

from api.server import (
    _GENDERS,
    _PROJECT_ROOT,
    DEFAULT_SIZE,
    _build_demographics_for_gender,
    process_advisor,
)
from pipeline.persona.aggregator_llm import select_features
from pipeline.persona.generator import build_avatar_charachter, pick_demographics
from pipeline.persona.marshal import marshal_avatar_persona
from pipeline.render.expression_resolver import EXPRESSIONS_YML
from pipeline.render.style_resolver import STYLES_YML

logger = logging.getLogger(__name__)


def _load_styles() -> list[dict]:
    """Load style definitions from styles.yml."""
    import yaml as _yaml
    with open(STYLES_YML) as f:
        data = _yaml.safe_load(f)
    return data.get("styles", [])


def _run_stage_b(args) -> None:
    """Run Stage B only: demographics + LLM feature selection → YAML output."""
    demographics = pick_demographics(seed=args.seed)
    advisor = {
        "role": args.role,
        "traits": args.traits or [],
        "education": args.education or [],
        "experience": args.experience or [],
    }

    print("Demographics:")
    print(yaml.dump(demographics, default_flow_style=False, sort_keys=False))

    print("Calling LLM for feature selection…")
    features = select_features(
        demographics,
        advisor,
        gateway_url=args.gateway_url,
    )

    if features is None:
        print("ERROR: select_features returned None", file=sys.stderr)
        sys.exit(1)

    print("Raw features:")
    print(yaml.dump(features, default_flow_style=False, sort_keys=False))

    persona = marshal_avatar_persona(demographics, advisor, features)
    print("Marshalled avatar_persona:")
    print(yaml.dump(persona, default_flow_style=False, sort_keys=False))

    name = persona.get("personal", {}).get("name")
    appearance = persona.get("appearance", {})
    print("--- Validation ---")
    print(f"Name:       {name or 'MISSING'}")
    print(f"Appearance: {len(appearance)} keys {'OK' if appearance else 'EMPTY — Stage B FAILED'}")
    if not name or not appearance:
        sys.exit(1)
    print("Stage B OK")


def _run_generate(args) -> None:
    """Full avatar generation pipeline."""
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.advisor:
        paths = [Path(args.advisor)]
    else:
        d = Path(args.advisors_dir)
        paths = sorted(d.glob("*.yml"))
        if not paths:
            print(f"Error: no .yml files found in {d}", file=sys.stderr)
            sys.exit(1)

    for advisor_path in paths:
        print(f"\n{advisor_path.stem}:")
        process_advisor(
            advisor_path,
            out_dir,
            size=args.size,
            expressions=args.expressions,
            gateway_url=args.gateway_url,
            width=args.width,
            height=args.height,
        )

    print(f"\nDone — {len(paths)} advisor(s) processed.")


def _run_gen_examples(args) -> None:
    """Generate style example portraits: one per (style, gender) combination."""
    import tempfile

    from pipeline.render.llm.orchestrator import generate_avatar_image

    styles = _load_styles()

    if args.style:
        requested = set(args.style)
        styles = [s for s in styles if s["id"] in requested]
    else:
        styles = [s for s in styles if s["id"] != "random" and s.get("system_prompt")]

    if not styles:
        print("No matching styles found.", file=sys.stderr)
        sys.exit(1)

    genders = args.gender or _GENDERS
    examples_dir = _PROJECT_ROOT / "tmp"
    examples_dir.mkdir(parents=True, exist_ok=True)

    advisor = {"role": "Professional Advisor"}
    total = len(styles) * len(genders)
    done = 0

    for style in styles:
        style_id = style["id"]
        for gender in genders:
            gender_slug = gender.replace("-", "_")
            out_path = examples_dir / f"avatar_style_{style_id}_{gender_slug}.png"

            if out_path.exists() and not args.overwrite:
                print(f"  [{done + 1}/{total}] skip {out_path.name} (exists)")
                done += 1
                continue

            print(f"  [{done + 1}/{total}] {style_id} / {gender} → {out_path.name}")

            demo = _build_demographics_for_gender(gender)
            demo["style"] = style_id
            avatar_char = build_avatar_charachter(advisor, demo)

            import yaml as _yaml
            with tempfile.NamedTemporaryFile(suffix=".yml", delete=False, mode="w") as tf:
                _yaml.dump(
                    avatar_char["avatar_persona"],
                    tf,
                    default_flow_style=False,
                    sort_keys=False,
                    allow_unicode=True,
                )
                persona_tmp = Path(tf.name)

            try:
                generate_avatar_image(
                    persona_tmp,
                    style={
                        "name": style_id,
                        "bg_color": demo.get("bg_color", "#F5F0E8"),
                        "styles_yml": STYLES_YML,
                    },
                    expression={"name": "neutral", "expressions_yml": EXPRESSIONS_YML},
                    gateway_url=args.gateway_url,
                    width=args.width,
                    height=args.height,
                    out_path=out_path,
                )
                print("    ✓ saved")
            except Exception as exc:
                print(f"    ✗ failed: {exc}", file=sys.stderr)
            finally:
                persona_tmp.unlink(missing_ok=True)

            done += 1

    print(f"\nDone — {done} image(s) processed.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate advisor avatars (abbreviation + face expressions)"
    )
    subparsers = parser.add_subparsers(dest="command")

    _GATEWAY_DEFAULT = "http://127.0.0.1:4096"

    # --- stage-b: run just the LLM feature selection ---
    sb = subparsers.add_parser(
        "stage-b",
        help="Run Stage B (LLM feature selection) only — prints features as YAML",
    )
    sb.add_argument("--role", default="Financial Advisor", help="Advisor role")
    sb.add_argument("--traits", nargs="*", default=["analytical", "patient"])
    sb.add_argument("--education", nargs="*", default=["MBA Finance"])
    sb.add_argument("--experience", nargs="*", default=["10 years wealth management"])
    sb.add_argument("--seed", type=int, default=None, help="Demographics seed")
    sb.add_argument(
        "--gateway-url",
        default=_GATEWAY_DEFAULT,
        help=f"LLM Gateway URL (default: {_GATEWAY_DEFAULT})",
    )

    # --- generate: full avatar pipeline ---
    gen = subparsers.add_parser("generate", help="Full avatar generation pipeline")
    group = gen.add_mutually_exclusive_group(required=True)
    group.add_argument("--advisor", help="Path to a single advisor YAML file")
    group.add_argument("--advisors-dir", help="Directory containing advisor YAML files")
    gen.add_argument("--out-dir", required=True, help="Output directory for generated PNGs")
    gen.add_argument("--size", type=int, default=DEFAULT_SIZE, help="Avatar size in pixels")
    gen.add_argument(
        "--expressions",
        nargs="*",
        help="Expression IDs to generate (default: all).",
    )
    gen.add_argument(
        "--gateway-url",
        default=_GATEWAY_DEFAULT,
        help=f"LLM Gateway URL (default: {_GATEWAY_DEFAULT})",
    )
    gen.add_argument("--width", type=int, default=128, help="Generated image width (default: 128)")
    gen.add_argument("--height", type=int, default=128, help="Generated image height (default: 128)")

    # ── gen-examples ──────────────────────────────────────────────────────────
    gex = subparsers.add_parser(
        "gen-examples",
        help="Generate style example portraits (one per style × gender)",
    )
    gex.add_argument(
        "--style",
        nargs="*",
        metavar="STYLE_ID",
        help="Style ID(s) to generate (default: all non-random styles)",
    )
    gex.add_argument(
        "--gender",
        nargs="*",
        choices=_GENDERS,
        metavar="GENDER",
        help=f"Gender(s) to generate (default: all). Choices: {_GENDERS}",
    )
    gex.add_argument(
        "--gateway-url",
        default=_GATEWAY_DEFAULT,
        help=f"LLM Gateway URL (default: {_GATEWAY_DEFAULT})",
    )
    gex.add_argument("--width", type=int, default=512, help="Image width in pixels (default: 512)")
    gex.add_argument("--height", type=int, default=512, help="Image height in pixels (default: 512)")
    gex.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-generate even if the output file already exists",
    )

    args = parser.parse_args()

    if args.command == "stage-b":
        _run_stage_b(args)
    elif args.command == "generate":
        _run_generate(args)
    elif args.command == "gen-examples":
        _run_gen_examples(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
