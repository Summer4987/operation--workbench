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
LOGIN_PREFLIGHT_RUNNER="$ROOT/scripts/check_platform_login_preflight.py"

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

python_has_playwright() {
  "$PYTHON" - <<'PY' >/dev/null 2>&1
import playwright  # noqa: F401
PY
}

ensure_browser_env() {
  local ensure_script="$ROOT/scripts/ensure_browser_automation_env.zsh"
  if [[ ! -f "$ensure_script" || ! -x "$ensure_script" ]]; then
    return 0
  fi
  run_with_timeout "${REALTIME_DEPENDENCY_CHECK_TIMEOUT_SECONDS:-240}" env OPERATION_ROOT="$ROOT" /bin/zsh "$ensure_script"
  local rc=$?
  if [[ "$rc" -eq 0 ]]; then
    PYTHON="$ROOT/business-report-dashboard/.venv/bin/python"
    export PYTHONPATH="$ROOT/business-report-dashboard/.venv/lib/python3.12/site-packages${PYTHONPATH:+:$PYTHONPATH}"
    return 0
  fi
  if python_has_playwright; then
    echo "浏览器自动化依赖检查脚本失败，已用当前 Python 直接确认 Playwright 可用，继续采集。"
    return 0
  fi
  FINAL_RC="$rc"
  TASK_STEP="浏览器自动化依赖检查"
  record_task_run "$TASK_ID" failed --message "实时单量收入采集未执行：浏览器自动化环境不可用，Playwright 安装或导入失败。" --step "$TASK_STEP" --log-path "$LOG_FILE" --returncode "$rc" --failure-type "dependency_missing"
  TASK_STATE_FINALIZED="true"
  return "$rc"
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
else:
    missing = payload.get("missing") or []
    if missing:
        stores = []
        for item in missing[:4]:
            if isinstance(item, dict):
                stores.append(f"{item.get('platform') or '未知平台'}{item.get('store') or ''}")
        if stores:
            parts.append("缺失门店：" + "、".join(stores))
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
  run_with_timeout "$seconds" "$@"
  local rc=$?
  if [[ "$rc" -eq 0 ]]; then
    return 0
  fi
  if [[ "$FINAL_RC" -eq 0 ]]; then
    FINAL_RC="$rc"
  fi
  record_task_run "$TASK_ID" failed --message "实时单量收入采集后续步骤失败：${TASK_STEP}。" --step "$TASK_STEP" --log-path "$LOG_FILE" --returncode "$rc"
  return "$rc"
}

refresh_final_workbench_state() {
  TASK_STEP="刷新最终工作台状态"
  run_with_timeout "${REALTIME_BUILD_TIMEOUT_SECONDS:-120}" "$PYTHON" "$ROOT/scripts/build_realtime_collection_status.py" || true
  run_with_timeout "${REALTIME_BUILD_TIMEOUT_SECONDS:-120}" "$PYTHON" "$ROOT/scripts/build_task_health.py" || true
  run_with_timeout "${REALTIME_BUILD_TIMEOUT_SECONDS:-120}" "$PYTHON" "$ROOT/scripts/build_workbench_data.py" || true
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
  ensure_browser_env || exit "$FINAL_RC"
  run_with_timeout "${CHROME_TAB_CLEANUP_TIMEOUT_SECONDS:-20}" "$PYTHON" "$ROOT/scripts/cleanup_chrome_tabs.py" || true
  TASK_STEP="开跑前登录态预检"
  record_task_run "$TASK_ID" running --message "$TASK_STEP" --step "$TASK_STEP" --log-path "$LOG_FILE"
  run_with_timeout "${REALTIME_LOGIN_PREFLIGHT_TIMEOUT_SECONDS:-240}" "$PYTHON" "$LOGIN_PREFLIGHT_RUNNER" --scope realtime --notify
  PREFLIGHT_RC=$?
  if [[ "$PREFLIGHT_RC" -ne 0 ]]; then
    FINAL_RC="$PREFLIGHT_RC"
    record_task_run "$TASK_ID" failed --message "实时单量收入采集未执行：开跑前登录态预检失败，已通知人工处理。" --step "$TASK_STEP" --log-path "$LOG_FILE" --returncode "$PREFLIGHT_RC" --failure-type "auth_block"
    exit "$FINAL_RC"
  fi
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
  refresh_final_workbench_state
  run_with_timeout "${REALTIME_DEPLOY_TIMEOUT_SECONDS:-180}" env OPERATION_ROOT="$ROOT" OPERATION_CLOUD_DEPLOY_MODE=data-only /bin/zsh "$ROOT/scripts/deploy_workbench_to_cloud.zsh" || true
  TASK_STATE_FINALIZED="true"
  if [[ "$FINAL_RC" -eq 0 ]]; then
    echo "[$(date '+%F %T')] 实时单量收入采集完成"
  else
    echo "[$(date '+%F %T')] 实时单量收入采集失败，已生成失败状态并保留上一份成功数据"
  fi
} >> "$LOG_FILE" 2>&1

exit "$FINAL_RC"
