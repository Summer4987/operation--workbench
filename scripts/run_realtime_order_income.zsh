#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$ROOT/outputs/realtime_order_income/logs"
mkdir -p "$LOG_DIR"

PYTHON="$ROOT/business-report-dashboard/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  PYTHON="/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
fi
if [ ! -x "$PYTHON" ]; then
  PYTHON="python3"
fi

LOG_FILE="$LOG_DIR/$(date +%F).log"
{
  echo
  echo "[$(date '+%F %T')] 实时单量收入采集开始"
  "$PYTHON" "$ROOT/scripts/realtime_order_income.py"
  "$PYTHON" "$ROOT/scripts/build_workbench_data.py"
  /bin/zsh "$ROOT/scripts/deploy_workbench_to_cloud.zsh"
  echo "[$(date '+%F %T')] 实时单量收入采集完成"
} >> "$LOG_FILE" 2>&1
