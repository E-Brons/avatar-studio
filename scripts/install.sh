#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# ── Args ──────────────────────────────────────────────────────────────
GATEWAY_PORT=4096
while [[ $# -gt 0 ]]; do
  case "$1" in
    --gateway-port) GATEWAY_PORT="$2"; shift 2 ;;
    *)
      echo "Unknown argument: $1"
      echo "Usage: install.sh [--gateway-port PORT]"
      exit 1
      ;;
  esac
done
GATEWAY_URL="http://127.0.0.1:$GATEWAY_PORT"

# ── Prerequisites ─────────────────────────────────────────────────────
echo "Checking prerequisites…"

if command -v python3 &>/dev/null; then
  printf "  %-10s %s\n" "python3" "$(python3 --version 2>&1 | head -1)"
else
  echo "  ✗ python3 not found"
  exit 1
fi

if command -v node &>/dev/null; then
  printf "  %-10s %s\n" "node" "$(node --version)"
else
  echo "  ✗ node not found — Node.js >= 18 is required."
  echo "      Install from https://nodejs.org/ or via your package manager."
  exit 1
fi

node_major=$(node --version | sed 's/v//' | cut -d. -f1)
if [ "$node_major" -lt 18 ]; then
  echo "  ✗ Node.js $(node --version) found, but >= 18 is required."
  exit 1
fi

# ── Version checks ────────────────────────────────────────────────────
py_ver=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
py_major=$(echo "$py_ver" | cut -d. -f1)
py_minor=$(echo "$py_ver" | cut -d. -f2)
if [ "$py_major" -lt 3 ] || { [ "$py_major" -eq 3 ] && [ "$py_minor" -lt 14 ]; }; then
  echo "  ✗ python3 $py_ver found, but >= 3.14 is required."
  exit 1
fi

# ── LLM Gateway ───────────────────────────────────────────────────────
echo ""
echo "Checking LLM Gateway at $GATEWAY_URL …"
if ! curl -sf "$GATEWAY_URL/health" >/dev/null 2>&1; then
  echo "  ✗ LLM Gateway not reachable at $GATEWAY_URL"
  echo ""
  echo "  1. Install and start the LLM Gateway:"
  echo "       git clone git@github.com:E-Brons/llm_gateway.git"
  echo "       cd llm_gateway && scripts/install.sh && scripts/run.sh"
  echo ""
  echo "  2. If your gateway runs on a non-standard port, re-run with:"
  echo "       scripts/install.sh --gateway-port <PORT>"
  exit 1
fi
printf "  %-10s %s\n" "llm_gateway" "$GATEWAY_URL  ✓"

# ── Python virtual environment ────────────────────────────────────────
echo ""
VENV="$ROOT/.venv"
if [ ! -d "$VENV" ]; then
  echo "Creating Python venv at $VENV …"
  python3 -m venv "$VENV"
fi

echo "Installing Python dependencies …"
"$VENV/bin/pip" install --upgrade pip
"$VENV/bin/pip" install -e "$ROOT[dev]"

# ── local/ directory ──────────────────────────────────────────────────
mkdir -p "$ROOT/local"

# ── Node vendor dependencies ──────────────────────────────────────────
echo ""
echo "Installing Node.js vendor dependencies …"
if [ ! -f "$ROOT/vendor/toon-head/package-lock.json" ]; then
  echo "  ✗ vendor/toon-head/package-lock.json not found."
  exit 1
fi
(cd "$ROOT/vendor/toon-head" && npm ci --silent)
echo "  vendor/toon-head  ✓"

# ── Git hooks ─────────────────────────────────────────────────────────
echo ""
echo "Installing git hooks …"
git -C "$ROOT" config core.hooksPath .githooks
echo "  pre-push hook active (ruff check + format)"
