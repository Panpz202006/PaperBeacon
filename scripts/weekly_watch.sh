#!/usr/bin/env bash
# Compatibility entry point; now checks the daily 07:30 digest.
set -euo pipefail
cd "$(dirname "$0")/.."
ENV_FILE="${SCOUT_ENV_FILE:-$PWD/.env}"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  source "$ENV_FILE"
  set +a
fi
PYTHON="${SCOUT_PYTHON:-$PWD/.venv/bin/python}"
if [[ ! -x "$PYTHON" && -x "$PWD/prcg/bin/python" ]]; then
  PYTHON="$PWD/prcg/bin/python"
fi
exec "$PYTHON" -m literature_scout daily \
  --config "${SCOUT_CONFIG:-config/medqkformer.json}" \
  --out "${SCOUT_OUTPUT:-runs/daily-medqkformer}" "$@"
