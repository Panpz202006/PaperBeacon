#!/usr/bin/env bash
# One entry point for the documented laptop workflow.
set -euo pipefail
cd "$(dirname "$0")/.."
ENV_FILE="${SCOUT_ENV_FILE:-$PWD/.env}"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  source "$ENV_FILE"
  set +a
fi
if [[ -n "${SCOUT_PYTHON:-}" ]]; then
  PYTHON="$SCOUT_PYTHON"
elif [[ -x "$PWD/.venv/bin/python" ]]; then
  PYTHON="$PWD/.venv/bin/python"
elif [[ -x "$PWD/prcg/bin/python" ]]; then
  PYTHON="$PWD/prcg/bin/python"
else
  PYTHON=python3
fi
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$PYTHON" -m literature_scout.interface "$@"
