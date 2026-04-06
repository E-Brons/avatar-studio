#!/usr/bin/env bash
# Find any mention of the old pipeline step/stage naming convention.
# Exits 1 if matches are found, 0 if clean.
#
# Catches all forms:
#   step_a / step-a / step a / Step A / STEP_A / [Step A] / Stage A  (A–G)

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

PATTERNS=(
  '[Ss][Tt][Ee][Pp][_\- ][A-Ga-g]\b'   # step_a  step-a  step a  (case-insensitive)
  '\[[Ss]tep [A-G]\]'                    # [Step A] log-message bracket form
  '\b[Ss]tage [A-G]\b'                   # Stage A  stage A
  '\b[Ss][Tt][Ee][Pp][A-Ga-g]\b'        # stepA  StepA  STEPA (no separator)
)

SEARCH_DIRS=("$ROOT/src" "$ROOT/tests" "$ROOT/docs")
EXCLUDE_DIRS=("__pycache__" ".venv" "*.egg-info" "node_modules")

EXCLUDE_ARGS=()
for d in "${EXCLUDE_DIRS[@]}"; do
  EXCLUDE_ARGS+=(--exclude-dir="$d")
done

FOUND=0
for pattern in "${PATTERNS[@]}"; do
  results=$(grep -rn --include="*.py" --include="*.md" --include="*.yml" --include="*.yaml" \
    --include="*.json" --include="*.sh" --include="*.dart" \
    "${EXCLUDE_ARGS[@]}" -E "$pattern" "${SEARCH_DIRS[@]}" 2>/dev/null || true)
  if [ -n "$results" ]; then
    echo "$results"
    FOUND=1
  fi
done

if [ "$FOUND" -eq 1 ]; then
  echo ""
  echo "ERROR: old step/stage terminology found — remove before committing."
  exit 1
fi
