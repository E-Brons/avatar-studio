#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$ROOT/.venv"
PID_FILE="$ROOT/local/server.pid"

if [ ! -d "$VENV" ]; then
  echo "No .venv found — run scripts/install.sh first."
  exit 1
fi

# Defaults
PORT=8000
HOST="127.0.0.1"

# Optional: point at a non-default LLM Gateway
OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:4096}"

# Parse args
while [[ $# -gt 0 ]]; do
  case "$1" in
    --port)   PORT="$2";  shift 2 ;;
    --host)   HOST="$2";  shift 2 ;;
    *)
      echo "Unknown argument: $1"
      echo "Usage: run.sh [--port PORT] [--host HOST]"
      echo "  OLLAMA_URL env var controls the LLM Gateway (default: http://127.0.0.1:4096)"
      exit 1
      ;;
  esac
done

if [ -f "$PID_FILE" ]; then
  PID=$(cat "$PID_FILE")
  if kill -0 "$PID" 2>/dev/null; then
    echo "Avatar Studio already running (PID $PID). Run stop.sh first."
    exit 1
  fi
  rm -f "$PID_FILE"
fi

echo "Starting Avatar Studio at http://$HOST:$PORT …"
echo "  LLM Gateway: $OLLAMA_URL"

OLLAMA_URL="$OLLAMA_URL" \
  "$VENV/bin/uvicorn" avatar_studio.api.server:app \
  --host "$HOST" \
  --port "$PORT" \
  --app-dir "$ROOT/src" &

echo $! > "$PID_FILE"

# Wait for the server to be ready
echo -n "Waiting for server"
for i in $(seq 1 60); do
  if curl -sf "http://$HOST:$PORT/health" >/dev/null 2>&1; then
    echo " ready."
    echo "Avatar Studio running at http://$HOST:$PORT"
    exit 0
  fi
  sleep 1
  [ $((i % 10)) -eq 0 ] && echo -n " ${i}s" || echo -n "."
done

echo " timed out."
exit 1
