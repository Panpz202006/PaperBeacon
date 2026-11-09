#!/usr/bin/env bash
# Shared daily report for Professors Chong Peng and Zhaoru Guo; due at 08:00 Asia/Shanghai.
set -euo pipefail
cd "$(dirname "$0")/.."
PRIVATE_ENV="${SCOUT_CHONG_PENG_ENV_FILE:-.env.chong_peng}"
if [[ -f "$PRIVATE_ENV" ]]; then
  set -a
  source "$PRIVATE_ENV"
  set +a
fi
exec /bin/bash scripts/scout.sh digest \
  --config config/chong_peng/daily_digest.json \
  --out runs/chong-peng-daily "$@"
