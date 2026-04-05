#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$ROOT/.venv"

if [ ! -d "$VENV" ]; then
  echo "No .venv found — run scripts/install.sh first."
  exit 1
fi

echo "── lint ────────────────────────────────────"
"$VENV/bin/ruff" check src/ tests/
"$VENV/bin/ruff" format --check src/ tests/

echo "── backend tests ───────────────────────────"
"$VENV/bin/python" -m pytest "$ROOT/tests/" -m "not integration" "$@"

echo "── frontend tests ──────────────────────────"
if command -v flutter &>/dev/null; then
  (cd "$ROOT/frontend" && flutter test)
else
  echo "  flutter not found — skipping (install Flutter to run frontend tests)"
fi
