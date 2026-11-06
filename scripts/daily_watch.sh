#!/usr/bin/env bash
# Daily combined report: collect locally, then send once when due at 07:30.
set -euo pipefail
cd "$(dirname "$0")/.."
exec /bin/bash scripts/scout.sh digest "$@"
