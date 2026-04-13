#!/usr/bin/env python3
"""Check that YAML asset files are formatted correctly for round-trip preservation.

Analogous to `ruff format --check` for Python. Exits non-zero if any file
would be reformatted by a ruamel.yaml round-trip, meaning it was edited by
hand in a way that does not match the project's canonical YAML style.

Usage:
    python scripts/check_yaml_format.py              # check all tracked files
    python scripts/check_yaml_format.py path/a.yml   # check specific files
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

from ruamel.yaml import YAML

ROOT = Path(__file__).resolve().parents[1]

_CHECKED_FILES = [
    ROOT / "assets" / "styles" / "styles.yml",
    ROOT / "assets" / "expressions" / "expressions.yml",
]


def _yaml_rt() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.indent(mapping=2, sequence=4, offset=2)
    y.width = 2**16
    y.Representer.add_representer(
        type(None), lambda self, _: self.represent_scalar("tag:yaml.org,2002:null", "null")
    )
    return y


def check_file(path: Path, yaml_rt: YAML) -> list[str]:
    """Return list of diff lines if file would be reformatted, else empty list."""
    original = path.read_text()
    data = yaml_rt.load(original)
    buf = io.StringIO()
    yaml_rt.dump(data, buf)
    roundtripped = buf.getvalue()
    if original == roundtripped:
        return []
    diffs = []
    orig_lines = original.splitlines()
    rt_lines = roundtripped.splitlines()
    for i, (a, b) in enumerate(zip(orig_lines, rt_lines)):
        if a != b:
            diffs.append(f"  line {i + 1}: {a!r} -> {b!r}")
    if len(orig_lines) != len(rt_lines):
        diffs.append(f"  line count: {len(orig_lines)} -> {len(rt_lines)}")
    return diffs


def main(argv: list[str] | None = None) -> int:
    paths = [Path(p) for p in argv] if argv else _CHECKED_FILES
    yaml_rt = _yaml_rt()
    failed: list[str] = []
    for path in paths:
        diffs = check_file(path, yaml_rt)
        if diffs:
            failed.append(str(path.relative_to(ROOT)))
            print(f"FAIL {path.relative_to(ROOT)}")
            for d in diffs[:5]:
                print(d)
        else:
            print(f"ok   {path.relative_to(ROOT)}")
    if failed:
        print(f"\n{len(failed)} file(s) would be reformatted. Edit to match canonical style.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or None))
