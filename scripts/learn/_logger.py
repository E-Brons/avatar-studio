"""LJSON logger — writes one JSON object per line to a .ljson experiment log.

Log files land in logs/learn/ by default, are never deleted, and are untracked
by git (logs/ is in .gitignore).

Typical record types:
    config      — script args + example count, written at startup
    render      — one record per generated image
    score       — one record per scored image
    fix         — one record per applied fix
    summary     — per-iteration aggregate stats
    plateau     — plateau detection event
    done        — final record when the loop exits
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


class LJSONLogger:
    """Thread-safe append-only logger that writes one JSON object per line."""

    def __init__(self, log_path: Path) -> None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._path = log_path

    def write(self, record: dict) -> None:
        """Append *record* to the log, adding a timestamp if not present."""
        if "ts" not in record:
            record = {"ts": datetime.now().isoformat(), **record}
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def config(self, **kwargs: object) -> None:
        self.write({"type": "config", **kwargs})

    def render(self, **kwargs: object) -> None:
        self.write({"type": "render", **kwargs})

    def score(self, **kwargs: object) -> None:
        self.write({"type": "score", **kwargs})

    def fix(self, **kwargs: object) -> None:
        self.write({"type": "fix", **kwargs})

    def summary(self, **kwargs: object) -> None:
        self.write({"type": "summary", **kwargs})

    def plateau(self, **kwargs: object) -> None:
        self.write({"type": "plateau", **kwargs})

    def done(self, **kwargs: object) -> None:
        self.write({"type": "done", **kwargs})


def make_logger(script_name: str, log_dir: Path) -> LJSONLogger:
    """Create a new LJSONLogger with a timestamped filename."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"{script_name}_{ts}.ljson"
    return LJSONLogger(log_path)
