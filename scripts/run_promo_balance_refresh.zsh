#!/bin/zsh
set -uo pipefail

ROOT="${OPERATION_ROOT:-$HOME/Library/Application Support/xiong-operation/production}"
LOG_DIR="$HOME/Library/Logs/xiong-operation/promo_balance_refresh"
LOCK_DIR="$HOME/Library/Caches/xiong-operation/promo_balance_refresh.lock"
mkdir -p "$LOG_DIR" "${LOCK_DIR:h}"

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "推广余额刷新仍在运行，本轮跳过。"
  exit 0
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT

cd "$ROOT"
PYTHON="$ROOT/business-report-dashboard/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
fi
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="python3"
fi

LOG_FILE="$LOG_DIR/$(date +%F).log"
{
  echo
  echo "[$(date '+%F %T')] 推广余额刷新开始"
  "$PYTHON" store-inspection/run_all_balances.py
  "$PYTHON" scripts/build_promo_balance_status.py
  "$PYTHON" scripts/build_task_health.py
  "$PYTHON" scripts/build_workbench_data.py
  OPERATION_ROOT="$ROOT" OPERATION_CLOUD_DEPLOY_MODE=data-only \
    /bin/zsh "$HOME/Library/Scripts/xiong-operation/deploy_workbench_to_cloud.zsh"
  echo "[$(date '+%F %T')] 推广余额刷新完成"
} >> "$LOG_FILE" 2>&1

