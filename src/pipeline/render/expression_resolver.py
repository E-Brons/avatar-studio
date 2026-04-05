"""Expression resolver — load expression entries from expressions.yml.

Always prepends the ``neutral`` expression so downstream steps can depend
on it as the portrait reference.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
EXPRESSIONS_YML = _PROJECT_ROOT / "assets" / "expressions" / "expressions.yml"


def load_all_expressions(expressions_yml: Path = EXPRESSIONS_YML) -> dict[str, dict]:
    """Return a mapping of expression id → entry dict for all expressions."""
    with open(expressions_yml) as f:
        data = yaml.safe_load(f)
    return {(e.get("id") or e["expression"].lower()): e for e in data.get("expressions", [])}


def resolve_expression(
    expr_name: str,
    expressions_yml: Path = EXPRESSIONS_YML,
) -> dict:
    """Return the expression entry for *expr_name* (or a minimal fallback)."""
    all_exprs = load_all_expressions(expressions_yml)
    return all_exprs.get(expr_name, {"expression": expr_name})


def resolve_expression_list(
    expr_ids: list[str],
    expressions_yml: Path = EXPRESSIONS_YML,
) -> list[str]:
    """Ensure ``neutral`` is first and all ids are unique; unknown ids are kept."""
    seen: set[str] = set()
    ordered: list[str] = []
    for e in ["neutral"] + list(expr_ids):
        if e not in seen:
            seen.add(e)
            ordered.append(e)
    return ordered


def load_expression_ids(expressions_yml: Path = EXPRESSIONS_YML) -> list[str]:
    """Return the list of expression IDs from expressions.yml."""
    with open(expressions_yml) as f:
        data = yaml.safe_load(f)
    return [e.get("id") or e["expression"].lower() for e in data["expressions"]]


EXPRESSION_IDS = load_expression_ids()
