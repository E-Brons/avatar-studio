#!/usr/bin/env bash
# Start the Avatar Studio HTTP server, open the browser, and shut everything
# down when the browser window is closed.
#
# Flow:
#   1. Start uvicorn (AVATAR_BROWSER_SHUTDOWN=1 tells the server to self-
#      terminate when all browser sessions disconnect).
#   2. Wait until /health returns 200.
#   3. Open the default browser.
#   4. Block until the server process exits (it exits when the browser closes).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv"
PORT=8080
URL="http://127.0.0.1:$PORT"
SKIP_BUILD=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-build) SKIP_BUILD=true; shift ;;
    *) echo "Unknown argument: $1"; echo "Usage: fullstack_run.sh [--skip-build]"; exit 1 ;;
  esac
done

if [[ ! -d "$VENV" ]]; then
  echo "ERROR: virtualenv not found at $VENV — run scripts/install.sh first" >&2
  exit 1
fi

# ── Build Flutter web ─────────────────────────────────────────────────────────
if [[ "$SKIP_BUILD" == "false" ]]; then
  if command -v flutter &>/dev/null; then
    echo "Building Flutter web app …"
    (cd "$ROOT/frontend" && flutter build web --release)
    echo "  frontend/build/web  ✓"
  else
    echo "  flutter not found — skipping build (install Flutter to serve the UI)"
  fi
fi

# ── Start the server ──────────────────────────────────────────────────────────
echo "Starting Avatar Studio on $URL ..."

AVATAR_BROWSER_SHUTDOWN=1 \
  "$VENV/bin/uvicorn" api.http_server:app \
    --host 127.0.0.1 \
    --port "$PORT" \
    --app-dir "$ROOT/src" &
SERVER_PID=$!

# Make sure we always clean up if the script is interrupted before the server
# shuts itself down.
_cleanup() {
  kill "$SERVER_PID" 2>/dev/null || true
  wait "$SERVER_PID" 2>/dev/null || true
}
trap _cleanup EXIT INT TERM

# ── Wait for the server to be ready ──────────────────────────────────────────
echo -n "Waiting for server"
for i in {1..40}; do
  if curl -sf "$URL/health" > /dev/null 2>&1; then
    echo " ready."
    break
  fi
  echo -n "."
  sleep 0.5
done

if ! curl -sf "$URL/health" > /dev/null 2>&1; then
  echo ""
  echo "ERROR: server did not become ready in time." >&2
  exit 1
fi

# ── Open the default browser ──────────────────────────────────────────────────
echo "Opening $URL in the default browser."
if command -v open &>/dev/null; then       # macOS
  open "$URL"
elif command -v xdg-open &>/dev/null; then # Linux
  xdg-open "$URL"
elif command -v start &>/dev/null; then    # Windows / Git-Bash
  start "$URL"
fi

# ── Block until the server exits (triggered by browser close) ─────────────────
echo "Server running. Close the browser window to stop."
wait "$SERVER_PID"
echo "Server stopped."
