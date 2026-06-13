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
TASK_ID="ops.realtime_order_income"
TASK_STEP="初始化"

record_task_run() {
  "$PYTHON" "$ROOT/scripts/record_task_run.py" "$@" || true
}

LOG_FILE="$LOG_DIR/$(date +%F).log"
finish_task_state() {
  local rc="$?"
  if [[ "$rc" -eq 0 ]]; then
    record_task_run "$TASK_ID" success --message "实时单量收入采集完成。" --step "$TASK_STEP" --log-path "$LOG_FILE" --returncode "$rc"
  else
    record_task_run "$TASK_ID" failed --message "实时单量收入采集失败：${TASK_STEP}。" --step "$TASK_STEP" --log-path "$LOG_FILE" --returncode "$rc"
  fi
}
trap finish_task_state EXIT

{
  echo
  echo "[$(date '+%F %T')] 实时单量收入采集开始"
  record_task_run "$TASK_ID" running --message "实时单量收入采集开始。" --step "$TASK_STEP" --log-path "$LOG_FILE"
  TASK_STEP="采集平台实时单量"
  record_task_run "$TASK_ID" running --message "$TASK_STEP" --step "$TASK_STEP" --log-path "$LOG_FILE"
  "$PYTHON" "$ROOT/scripts/realtime_order_income.py"
  TASK_STEP="生成实时采集状态"
  record_task_run "$TASK_ID" running --message "$TASK_STEP" --step "$TASK_STEP" --log-path "$LOG_FILE"
  "$PYTHON" "$ROOT/scripts/build_realtime_collection_status.py"
  TASK_STEP="生成任务健康状态"
  record_task_run "$TASK_ID" running --message "$TASK_STEP" --step "$TASK_STEP" --log-path "$LOG_FILE"
  "$PYTHON" "$ROOT/scripts/build_task_health.py"
  TASK_STEP="生成工作台数据"
  record_task_run "$TASK_ID" running --message "$TASK_STEP" --step "$TASK_STEP" --log-path "$LOG_FILE"
  "$PYTHON" "$ROOT/scripts/build_workbench_data.py"
  TASK_STEP="发布工作台云端数据"
  record_task_run "$TASK_ID" running --message "$TASK_STEP" --step "$TASK_STEP" --log-path "$LOG_FILE"
  /bin/zsh "$ROOT/scripts/deploy_workbench_to_cloud.zsh"
  echo "[$(date '+%F %T')] 实时单量收入采集完成"
} >> "$LOG_FILE" 2>&1
