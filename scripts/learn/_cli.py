"""Common CLI arguments shared across all learning scripts.

All learning scripts accept the same core flags:

    --range A B              inclusive index range into the sorted example list
    --samples X              random sample count; mutually exclusive with --range
                             (default: 32 — prompts user to confirm if > 100)
    --workers N              parallel render workers (default: 4)
    --stop-on-plateau /
    --no-stop-on-plateau     plateau guard — stop when score delta < 1% for 2 consecutive iters
    --max-iterations N       safety cap (default: 6)
    --optimize OPT           quality | normal | fast   (default: normal)
    --component-threshold N  min acceptable score for each individual score component (default: 75)
    --compound-threshold N   min acceptable score for compound/aggregate scores (default: 90)
    --gateway URL            LLM gateway base URL
    --log-dir DIR            where .ljson logs are written (default: logs/learn/)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATEWAY_URL = "http://127.0.0.1:4096"
LOG_DIR = ROOT / "logs" / "learn"
FULL_SET_CONFIRM_THRESHOLD = 100


def add_common_args(parser: argparse.ArgumentParser) -> None:
    """Add the shared learning flags to *parser* (mutates in-place)."""
    sample_group = parser.add_mutually_exclusive_group()
    sample_group.add_argument(
        "--range",
        type=int,
        nargs=2,
        metavar=("START", "END"),
        help="Inclusive index range of examples (e.g. --range 0 49)",
    )
    sample_group.add_argument(
        "--samples",
        type=int,
        default=32,
        metavar="X",
        help="Random sample count (mutually exclusive with --range; default: 32)",
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Parallel render workers (default: 4)",
    )

    plateau = parser.add_mutually_exclusive_group()
    plateau.add_argument(
        "--stop-on-plateau",
        dest="stop_on_plateau",
        action="store_true",
        default=True,
        help="Stop when score delta < 1%% for 2 consecutive iterations (default: on)",
    )
    plateau.add_argument(
        "--no-stop-on-plateau",
        dest="stop_on_plateau",
        action="store_false",
        help="Disable plateau guard",
    )

    parser.add_argument(
        "--max-iterations",
        type=int,
        default=6,
        help="Maximum number of learn iterations (default: 6)",
    )

    parser.add_argument(
        "--optimize",
        choices=["quality", "normal", "fast"],
        default="normal",
        help="Image generation quality preset (default: normal)",
    )

    parser.add_argument(
        "--component-threshold",
        type=int,
        default=75,
        metavar="N",
        help="Minimum acceptable score (0–100) for each individual score component (default: 75)",
    )

    parser.add_argument(
        "--compound-threshold",
        type=int,
        default=90,
        metavar="N",
        help="Minimum acceptable score (0–100) for compound/aggregate scores (default: 90)",
    )

    parser.add_argument(
        "--gateway",
        default=GATEWAY_URL,
        help=f"LLM gateway URL (default: {GATEWAY_URL})",
    )

    parser.add_argument(
        "--log-dir",
        type=Path,
        default=LOG_DIR,
        help=f"Directory for .ljson experiment logs (default: {LOG_DIR})",
    )


def confirm_full_set(n: int) -> None:
    """Prompt user for confirmation when running the entire example set (> threshold)."""
    if n <= FULL_SET_CONFIRM_THRESHOLD:
        return
    try:
        answer = input(
            f"\nNo --range or --samples given. About to run ALL {n} examples. Continue? [y/N] "
        ).strip()
    except EOFError, KeyboardInterrupt:
        answer = ""
    if answer.lower() not in ("y", "yes"):
        print("Aborted. Use --samples or --range to limit the run.")
        sys.exit(0)
