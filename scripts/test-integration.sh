#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$ROOT/.venv"

if [ ! -d "$VENV" ]; then
  echo "No .venv found — run scripts/install.sh first."
  exit 1
fi

OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:4096}"

# Verify gateway is reachable before running tests
if ! curl -sf "$OLLAMA_URL/health" >/dev/null 2>&1; then
  echo "LLM Gateway not reachable at $OLLAMA_URL"
  echo "Start it first, or set OLLAMA_URL to point to a running gateway."
  exit 1
fi

echo "── integration tests ───────────────────────"
echo "  Gateway: $OLLAMA_URL"
OLLAMA_URL="$OLLAMA_URL" \
  "$VENV/bin/python" -m pytest "$ROOT/tests/" -m "integration" "$@"
