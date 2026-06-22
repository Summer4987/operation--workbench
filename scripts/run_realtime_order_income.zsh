#!/bin/zsh
set -uo pipefail

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
FINAL_RC=0

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

latest_failure_message() {
  REALTIME_ROOT="$ROOT" "$PYTHON" - <<'PY'
import json
import os
from pathlib import Path

path = Path(os.environ["REALTIME_ROOT"]) / "outputs" / "realtime_order_income" / "last_failed.json"
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    print("实时单量收入采集失败，已保留上一份成功数据。")
    raise SystemExit

summary = payload.get("summary") or {}
parts = [
    f"实时单量收入采集失败：已采集 {summary.get('platform_store_count', 0)} 个平台门店",
    f"缺失 {summary.get('missing_count', 0)} 个",
]
errors = [str(item) for item in payload.get("errors") or [] if item]
if errors:
    parts.append("；".join(errors[:2]))
parts.append("已拒绝覆盖 latest.json，保留上一份成功数据。")
print("，".join(parts))
PY
}

run_followup_step() {
  local step="$1"
  local seconds="$2"
  shift 2
  TASK_STEP="$step"
  record_task_run "$TASK_ID" running --message "$TASK_STEP" --step "$TASK_STEP" --log-path "$LOG_FILE"
  if run_with_timeout "$seconds" "$@"; then
    return 0
  fi
  local rc=$?
  FINAL_RC="$rc"
  record_task_run "$TASK_ID" failed --message "实时单量收入采集后续步骤失败：${TASK_STEP}。" --step "$TASK_STEP" --log-path "$LOG_FILE" --returncode "$rc"
  return "$rc"
}

finish_task_state() {
  local rc="$?"
  if [[ "$TASK_STATE_FINALIZED" == "true" ]]; then
    return
  fi
  if [[ "$rc" -eq 0 && "$FINAL_RC" -eq 0 ]]; then
    record_task_run "$TASK_ID" success --message "实时单量收入采集完成。" --step "$TASK_STEP" --log-path "$LOG_FILE" --returncode 0
  else
    local final_rc="$rc"
    if [[ "$FINAL_RC" -ne 0 ]]; then
      final_rc="$FINAL_RC"
    fi
    record_task_run "$TASK_ID" failed --message "$(latest_failure_message)" --step "$TASK_STEP" --log-path "$LOG_FILE" --returncode "$final_rc"
  fi
}
trap finish_task_state EXIT

{
  echo
  echo "[$(date '+%F %T')] 实时单量收入采集开始"
  run_with_timeout "${CHROME_TAB_CLEANUP_TIMEOUT_SECONDS:-20}" "$PYTHON" "$ROOT/scripts/cleanup_chrome_tabs.py" || true
  record_task_run "$TASK_ID" running --message "实时单量收入采集开始。" --step "$TASK_STEP" --log-path "$LOG_FILE"
  TASK_STEP="采集平台实时单量"
  record_task_run "$TASK_ID" running --message "$TASK_STEP" --step "$TASK_STEP" --log-path "$LOG_FILE"
  if run_with_timeout "${REALTIME_COLLECT_TIMEOUT_SECONDS:-300}" "$PYTHON" "$ROOT/scripts/realtime_order_income.py"; then
    COLLECT_RC=0
  else
    COLLECT_RC=$?
    FINAL_RC="$COLLECT_RC"
    record_task_run "$TASK_ID" failed --message "$(latest_failure_message)" --step "$TASK_STEP" --log-path "$LOG_FILE" --returncode "$COLLECT_RC"
  fi
  TASK_STEP="清理浏览器标签页"
  run_with_timeout "${CHROME_TAB_CLEANUP_TIMEOUT_SECONDS:-20}" "$PYTHON" "$ROOT/scripts/cleanup_chrome_tabs.py" || true
  run_followup_step "生成实时采集状态" "${REALTIME_BUILD_TIMEOUT_SECONDS:-120}" "$PYTHON" "$ROOT/scripts/build_realtime_collection_status.py" || true
  run_followup_step "生成任务健康状态" "${REALTIME_BUILD_TIMEOUT_SECONDS:-120}" "$PYTHON" "$ROOT/scripts/build_task_health.py" || true
  run_followup_step "生成工作台数据" "${REALTIME_BUILD_TIMEOUT_SECONDS:-120}" "$PYTHON" "$ROOT/scripts/build_workbench_data.py" || true
  run_followup_step "发布工作台云端数据" "${REALTIME_DEPLOY_TIMEOUT_SECONDS:-180}" /bin/zsh "$ROOT/scripts/deploy_workbench_to_cloud.zsh" || true
  if [[ "$COLLECT_RC" -eq 0 && "$FINAL_RC" -eq 0 ]]; then
    record_task_run "$TASK_ID" success --message "实时单量收入采集完成。" --step "$TASK_STEP" --log-path "$LOG_FILE" --returncode 0
  else
    record_task_run "$TASK_ID" failed --message "$(latest_failure_message)" --step "$TASK_STEP" --log-path "$LOG_FILE" --returncode "$FINAL_RC"
  fi
  run_with_timeout "${REALTIME_BUILD_TIMEOUT_SECONDS:-120}" "$PYTHON" "$ROOT/scripts/build_task_health.py" || true
  run_with_timeout "${REALTIME_BUILD_TIMEOUT_SECONDS:-120}" "$PYTHON" "$ROOT/scripts/build_workbench_data.py" || true
  TASK_STATE_FINALIZED="true"
  if [[ "$FINAL_RC" -eq 0 ]]; then
    echo "[$(date '+%F %T')] 实时单量收入采集完成"
  else
    echo "[$(date '+%F %T')] 实时单量收入采集失败，已生成失败状态并保留上一份成功数据"
  fi
} >> "$LOG_FILE" 2>&1

exit "$FINAL_RC"
