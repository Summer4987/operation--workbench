#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
MODE="${KUAILV_ORDER_DRY_RUN_MODE:-adb-dry-run}"

if [[ $# -gt 0 ]]; then
  exec "$PYTHON" scripts/kuailv_order_dry_run.py "$@"
fi

args=(--mode "$MODE" --date "${KUAILV_ORDER_DRY_RUN_DATE:-$(date +%F)}")
if [[ -n "${ANDROID_ADB_SERIAL:-}" ]]; then
  args+=(--adb-serial "$ANDROID_ADB_SERIAL")
fi

exec "$PYTHON" scripts/kuailv_order_dry_run.py "${args[@]}"
