#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$ROOT/outputs/realtime_order_income/logs"
mkdir -p "$LOG_DIR"

PYTHON="/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
if [ ! -x "$PYTHON" ]; then
  PYTHON="$ROOT/business-report-dashboard/.venv/bin/python"
fi
if [ ! -x "$PYTHON" ]; then
  PYTHON="python3"
fi
export PYTHONPATH="$ROOT/business-report-dashboard/.venv/lib/python3.12/site-packages${PYTHONPATH:+:$PYTHONPATH}"
TASK_ID="ops.realtime_order_income"
TASK_STEP="初始化"
TASK_STATE_FINALIZED="false"

LOG_FILE="$LOG_DIR/$(date +%F).log"

run_with_timeout() {
  local seconds="$1"
  shift
  "$@" &
  local child_pid=$!
  (
    sleep "$seconds"
    if kill -0 "$child_pid" 2>/dev/null; then
      echo "步骤超时：${seconds}s，已终止：$*"
      pkill -TERM -P "$child_pid" 2>/dev/null || true
      kill -TERM "$child_pid" 2>/dev/null || true
      sleep 2
      pkill -KILL -P "$child_pid" 2>/dev/null || true
      kill -KILL "$child_pid" 2>/dev/null || true
    fi
  ) &
  local watchdog_pid=$!
  local exit_status=0
  wait "$child_pid" || exit_status=$?
  kill "$watchdog_pid" 2>/dev/null || true
  wait "$watchdog_pid" 2>/dev/null || true
  return "$exit_status"
}

record_task_run() {
  run_with_timeout "${TASK_STATE_WRITE_TIMEOUT_SECONDS:-10}" "$PYTHON" "$ROOT/scripts/record_task_run.py" "$@" || true
}

finish_task_state() {
  local rc="$?"
  if [[ "$rc" -eq 0 && "$TASK_STATE_FINALIZED" != "true" ]]; then
    record_task_run "$TASK_ID" success --message "实时单量收入采集完成。" --step "$TASK_STEP" --log-path "$LOG_FILE" --returncode "$rc"
  elif [[ "$rc" -ne 0 ]]; then
    record_task_run "$TASK_ID" failed --message "实时单量收入采集失败：${TASK_STEP}。" --step "$TASK_STEP" --log-path "$LOG_FILE" --returncode "$rc"
  fi
}
trap finish_task_state EXIT

{
  echo
  echo "[$(date '+%F %T')] 实时单量收入采集开始"
  run_with_timeout "${CHROME_TAB_CLEANUP_TIMEOUT_SECONDS:-20}" "$PYTHON" "$ROOT/scripts/cleanup_chrome_tabs.py"
  record_task_run "$TASK_ID" running --message "实时单量收入采集开始。" --step "$TASK_STEP" --log-path "$LOG_FILE"
  TASK_STEP="采集平台实时单量"
  record_task_run "$TASK_ID" running --message "$TASK_STEP" --step "$TASK_STEP" --log-path "$LOG_FILE"
  run_with_timeout "${REALTIME_COLLECT_TIMEOUT_SECONDS:-300}" "$PYTHON" "$ROOT/scripts/realtime_order_income.py"
  TASK_STEP="清理浏览器标签页"
  run_with_timeout "${CHROME_TAB_CLEANUP_TIMEOUT_SECONDS:-20}" "$PYTHON" "$ROOT/scripts/cleanup_chrome_tabs.py"
  TASK_STEP="生成实时采集状态"
  record_task_run "$TASK_ID" running --message "$TASK_STEP" --step "$TASK_STEP" --log-path "$LOG_FILE"
  run_with_timeout "${REALTIME_BUILD_TIMEOUT_SECONDS:-120}" "$PYTHON" "$ROOT/scripts/build_realtime_collection_status.py"
  TASK_STEP="发布工作台云端数据"
  record_task_run "$TASK_ID" running --message "$TASK_STEP" --step "$TASK_STEP" --log-path "$LOG_FILE"
  run_with_timeout "${REALTIME_DEPLOY_TIMEOUT_SECONDS:-180}" /bin/zsh "$ROOT/scripts/deploy_workbench_to_cloud.zsh"
  record_task_run "$TASK_ID" success --message "实时单量收入采集完成。" --step "$TASK_STEP" --log-path "$LOG_FILE" --returncode 0
  TASK_STEP="生成最终任务健康状态"
  run_with_timeout "${REALTIME_BUILD_TIMEOUT_SECONDS:-120}" "$PYTHON" "$ROOT/scripts/build_task_health.py"
  TASK_STEP="生成最终工作台数据"
  run_with_timeout "${REALTIME_BUILD_TIMEOUT_SECONDS:-120}" "$PYTHON" "$ROOT/scripts/build_workbench_data.py"
  TASK_STEP="发布最终工作台云端数据"
  run_with_timeout "${REALTIME_DEPLOY_TIMEOUT_SECONDS:-180}" /bin/zsh "$ROOT/scripts/deploy_workbench_to_cloud.zsh"
  TASK_STATE_FINALIZED="true"
  echo "[$(date '+%F %T')] 实时单量收入采集完成"
} >> "$LOG_FILE" 2>&1
