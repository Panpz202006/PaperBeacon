#!/usr/bin/env bash
# Legacy single-topic daily entry point; retained for compatibility only.
# For the combined daily report, use scripts/daily_watch.sh.
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
