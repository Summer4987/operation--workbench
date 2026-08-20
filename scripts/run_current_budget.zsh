#!/bin/zsh
set -euo pipefail

ROOT="${OPERATION_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$ROOT"
ELEME_RUNNER="${ELEME_AUTOMATION_RUNNER:-scripts/run_eleme_automation.zsh}"
DEPLOY_RUNNER="${WORKBENCH_DEPLOY_RUNNER:-scripts/deploy_workbench_to_cloud.zsh}"
CHROME_CLEANUP_RUNNER="$ROOT/scripts/cleanup_chrome_tabs.py"
LOGIN_PREFLIGHT_RUNNER="$ROOT/scripts/check_platform_login_preflight.py"

PERIOD="auto"
MODE="commit"
LIMIT="all"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --period)
      PERIOD="$2"
      shift 2
      ;;
    --mode)
      MODE="$2"
      shift 2
      ;;
    --limit)
      LIMIT="$2"
      shift 2
      ;;
    *)
      echo "未知参数：$1"
      exit 1
      ;;
  esac
done

if [[ "$MODE" != "commit" && "$MODE" != "preview" ]]; then
  echo "未知执行模式：$MODE。只能是 commit 或 preview。"
  exit 1
fi

if [[ "$PERIOD" == "auto" ]]; then
  HOUR="$(date +%H)"
  if (( 10#$HOUR < 15 )); then
    PERIOD="午餐"
  else
    PERIOD="晚餐"
  fi
fi

case "$PERIOD" in
  午餐)
    TIME_POINT="10:30"
    ALLOWED_START_MINUTES=$((9 * 60 + 30))
    ALLOWED_END_MINUTES=$((10 * 60 + 50))
    ;;
  晚餐)
    TIME_POINT="16:30"
    ALLOWED_START_MINUTES=$((16 * 60 + 20))
    ALLOWED_END_MINUTES=$((16 * 60 + 50))
    ;;
  *)
    echo "未知预算时段：$PERIOD"
    exit 1
    ;;
esac

LOG_DIR="$ROOT/outputs/current_budget/logs"
mkdir -p "$LOG_DIR"
RUN_LOG="$LOG_DIR/current_budget_${PERIOD}_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$RUN_LOG") 2>&1

NODE="/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
NODE_RUNTIME_ROOT="${BUDGET_NODE_RUNTIME_ROOT:-$HOME/Library/Application Support/xiong-operation/node-runtime}"
PYTHON="/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
if [ ! -x "$PYTHON" ]; then
  PYTHON="python3"
fi
REPORT_PYTHON="$ROOT/business-report-dashboard/.venv/bin/python"
if [ ! -x "$REPORT_PYTHON" ]; then
  REPORT_PYTHON="$PYTHON"
fi

cleanup_chrome_sessions() {
  local label="$1"
  if [ ! -f "$CHROME_CLEANUP_RUNNER" ]; then
    return 0
  fi
  echo "$label"
  "$PYTHON" "$CHROME_CLEANUP_RUNNER" || true
}

trap 'cleanup_chrome_sessions "== 预算任务退出时 Chrome 会话清理 ==" ' EXIT

TASK_ID="growth.promo_budget"
record_task_run() {
  "$PYTHON" "$ROOT/scripts/record_task_run.py" "$@" || true
}

CURRENT_HOUR="$(date +%H)"
CURRENT_MINUTE="$(date +%M)"
CURRENT_TOTAL_MINUTES=$((10#$CURRENT_HOUR * 60 + 10#$CURRENT_MINUTE))
ALLOWED_WINDOW_LABEL="$(printf '%02d:%02d-%02d:%02d' \
  $((ALLOWED_START_MINUTES / 60)) $((ALLOWED_START_MINUTES % 60)) \
  $((ALLOWED_END_MINUTES / 60)) $((ALLOWED_END_MINUTES % 60)))"

if [[ "$MODE" == "commit" && "${ALLOW_OUTSIDE_BUDGET_WINDOW:-0}" != "1" ]] \
  && (( CURRENT_TOTAL_MINUTES < ALLOWED_START_MINUTES || CURRENT_TOTAL_MINUTES > ALLOWED_END_MINUTES )); then
  echo "拒绝执行：当前时间 $(date '+%Y-%m-%d %H:%M:%S') 不在 ${PERIOD}预算允许窗口 ${ALLOWED_WINDOW_LABEL}。"
  echo "如需手动补跑，请显式设置 ALLOW_OUTSIDE_BUDGET_WINDOW=1。"
  record_task_run "$TASK_ID" failed --message "${PERIOD}预算拒绝执行：不在允许窗口 ${ALLOWED_WINDOW_LABEL}。" --step "${PERIOD}预算窗口检查" --log-path "$RUN_LOG" --returncode 64
  exit 64
fi

echo "== ${TIME_POINT} ${PERIOD}预算初始化 =="
echo "开始：$(date '+%Y-%m-%d %H:%M:%S')"
echo "模式：$MODE"
echo "数量：$LIMIT"
echo "允许窗口：${ALLOWED_WINDOW_LABEL}"
cleanup_chrome_sessions "== 预算任务开始前 Chrome 会话清理 =="
record_task_run "$TASK_ID" running --message "${PERIOD}预算执行开始。" --step "${PERIOD}预算初始化" --log-path "$RUN_LOG"
FAILED_STEPS=()
SUPPORT_FAILED_STEPS=()
ELEME_LOGIN_OK=1
MEITUAN_LOGIN_OK=1

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

run_with_retry() {
  local label="$1"
  local seconds="$2"
  local attempts="$3"
  shift 3
  local attempt=1
  local exit_status=0
  while (( attempt <= attempts )); do
    echo "${label}：第 ${attempt}/${attempts} 次执行..."
    set +e
    run_with_timeout "$seconds" "$@"
    exit_status=$?
    set -e
    if (( exit_status == 0 )); then
      return 0
    fi
    if (( attempt < attempts )); then
      echo "${label}：本次失败，5 秒后自动重试。"
      sleep 5
    fi
    attempt=$((attempt + 1))
  done
  return "$exit_status"
}

run_budget_step() {
  local step="$1"
  local seconds="$2"
  local attempts="$3"
  shift 3
  record_task_run "$TASK_ID" running --message "${step}开始。" --step "$step" --log-path "$RUN_LOG"
  local rc=0
  set +e
  run_with_retry "$step" "$seconds" "$attempts" "$@"
  rc=$?
  set -e
  if (( rc == 0 )); then
    record_task_run "$TASK_ID" success --message "${step}完成。" --step "$step" --log-path "$RUN_LOG" --returncode 0
    return 0
  fi
  record_task_run "$TASK_ID" failed --message "${step}失败，查看日志：$RUN_LOG" --step "$step" --log-path "$RUN_LOG" --returncode "$rc"
  FAILED_STEPS+=("$step")
  return "$rc"
}

run_support_step() {
  local step="$1"
  local seconds="$2"
  local attempts="$3"
  shift 3
  record_task_run "$TASK_ID" running --message "${step}开始。" --step "$step" --log-path "$RUN_LOG"
  local rc=0
  set +e
  run_with_retry "$step" "$seconds" "$attempts" "$@"
  rc=$?
  set -e
  if (( rc == 0 )); then
    return 0
  fi
  echo "附属步骤失败（不代表预算设置失败）：${step}"
  SUPPORT_FAILED_STEPS+=("$step")
  record_task_run "$TASK_ID" running \
    --message "${PERIOD}预算设置已完成；附属步骤失败：${step}。" \
    --step "$step" --log-path "$RUN_LOG" --returncode "$rc"
  return "$rc"
}

run_required_step() {
  local step="$1"
  local seconds="$2"
  shift 2
  record_task_run "$TASK_ID" running --message "${step}开始。" --step "$step" --log-path "$RUN_LOG"
  local rc=0
  set +e
  run_with_timeout "$seconds" "$@"
  rc=$?
  set -e
  if (( rc == 0 )); then
    record_task_run "$TASK_ID" success --message "${step}完成。" --step "$step" --log-path "$RUN_LOG" --returncode 0
    return 0
  fi
  record_task_run "$TASK_ID" failed --message "${step}失败，查看日志：$RUN_LOG" --step "$step" --log-path "$RUN_LOG" --returncode "$rc"
  return "$rc"
}

prepare_budget_node_runtime() {
  local missing=()
  for relative in \
    "scripts/build_promo_budget_preview.mjs" \
    "scripts/promo_budget_resolver.mjs" \
    "dianjin-prototype/rules.js" \
    "dianjin-prototype/logic.js" \
    "config/promo_budget_overrides.json" \
    "config/direct_meituan_accounts.json"; do
    if [ ! -r "$NODE_RUNTIME_ROOT/$relative" ]; then
      missing+=("$relative")
    fi
  done
  if (( ${#missing[@]} > 0 )); then
    echo "预算 Node runtime 缺少文件：${(j:、:)missing}"
    echo "请重新运行 scripts/install_macmini_operation_launchd.zsh 从 GitHub 工作树安装 runtime。"
    return 78
  fi
}

run_node_runtime_script() {
  local runtime_root="$1"
  local script_path="$2"
  shift
  shift
  cd "$runtime_root"
  exec "$NODE" "$script_path" "$@"
}

sync_budget_config() {
  PROMO_BUDGET_OVERRIDES_COPY_PATH="$NODE_RUNTIME_ROOT/config/promo_budget_overrides.json" "$PYTHON" "$ROOT/scripts/sync_promo_budget_overrides.py"
  local direct_accounts_source="$ROOT/config/direct_meituan_accounts.json"
  local direct_accounts_target="$NODE_RUNTIME_ROOT/config/direct_meituan_accounts.json"
  local direct_accounts_tmp="${direct_accounts_target}.tmp.$$"
  if /usr/bin/cmp -s "$direct_accounts_source" "$direct_accounts_target"; then
    echo "美团直营账号配置已是最新，跳过重复复制：$direct_accounts_target"
    return 0
  fi
  /bin/mkdir -p "$NODE_RUNTIME_ROOT/config"
  /bin/cp "$direct_accounts_source" "$direct_accounts_tmp"
  /bin/mv "$direct_accounts_tmp" "$direct_accounts_target"
  echo "已同步美团直营账号配置：$direct_accounts_target"
}

if run_required_step "${PERIOD}预算配置同步" "${BUDGET_CONFIG_SYNC_TIMEOUT_SECONDS:-120}" sync_budget_config; then
  :
else
  rc=$?
  exit "$rc"
fi

if [[ "$MODE" == "commit" ]]; then
  if ! run_required_step "饿了么开跑前登录态预检" "${BUDGET_LOGIN_PREFLIGHT_TIMEOUT_SECONDS:-300}" "$REPORT_PYTHON" "$LOGIN_PREFLIGHT_RUNNER" --scope budget --platform eleme --notify; then
    ELEME_LOGIN_OK=0
    FAILED_STEPS+=("饿了么登录态预检")
    echo "饿了么预检失败，已隔离跳过；继续执行美团。"
  fi
  if ! run_required_step "美团开跑前登录态预检" "${BUDGET_LOGIN_PREFLIGHT_TIMEOUT_SECONDS:-300}" "$REPORT_PYTHON" "$LOGIN_PREFLIGHT_RUNNER" --scope budget --platform meituan --notify; then
    MEITUAN_LOGIN_OK=0
    FAILED_STEPS+=("美团登录态预检")
    echo "美团预检失败，已隔离跳过；不影响饿了么。"
  fi
fi

prepare_budget_node_runtime
if run_required_step "${PERIOD}预算预览生成" "${BUDGET_PREVIEW_BUILD_TIMEOUT_SECONDS:-120}" run_node_runtime_script "$NODE_RUNTIME_ROOT" "$NODE_RUNTIME_ROOT/scripts/build_promo_budget_preview.mjs"; then
  BUDGET_ROOT="$ROOT" BUDGET_NODE_RUNTIME_ROOT="$NODE_RUNTIME_ROOT" "$PYTHON" - <<'PY'
import os
import shutil
from pathlib import Path

root = Path(os.environ["BUDGET_ROOT"])
runtime = Path(os.environ["BUDGET_NODE_RUNTIME_ROOT"])
(root / "outputs/promo_budget_preview").mkdir(parents=True, exist_ok=True)
for name in ("latest.json", "latest-data.js"):
    shutil.copy2(runtime / "outputs/promo_budget_preview" / name, root / "outputs/promo_budget_preview" / name)
PY
else
  rc=$?
  exit "$rc"
fi

echo
if [[ "$MODE" == "commit" && "$ELEME_LOGIN_OK" -eq 0 ]]; then
  echo "饿了么登录态预检未通过，本轮跳过饿了么${PERIOD}预算。"
elif [[ "$MODE" == "commit" ]]; then
  echo "执行饿了么${PERIOD}预算真实提交..."
else
  echo "执行饿了么${PERIOD}预算页面预演..."
fi
if [[ "$MODE" != "commit" || "$ELEME_LOGIN_OK" -eq 1 ]]; then
  run_budget_step "饿了么${PERIOD}预算" "${ELEME_BUDGET_TIMEOUT_SECONDS:-1800}" "${ELEME_BUDGET_RETRIES:-1}" /bin/zsh "$ELEME_RUNNER" --time "$TIME_POINT" --mode "$MODE" --limit "$LIMIT" || true
fi

echo
if [[ "$MODE" == "commit" && "$MEITUAN_LOGIN_OK" -eq 0 ]]; then
  echo "美团登录态预检未通过，本轮跳过美团${PERIOD}预算。"
elif [[ "$MODE" == "commit" ]]; then
  echo "执行美团${PERIOD}预算提交前预检..."
  MEITUAN_PREFLIGHT_RESULT="$ROOT/outputs/current_budget/meituan_preflight_${PERIOD}.json"
  /bin/rm -f "$MEITUAN_PREFLIGHT_RESULT"
  set +e
  run_with_retry "美团${PERIOD}预算提交前预检" "${MEITUAN_BUDGET_PREFLIGHT_TIMEOUT_SECONDS:-1800}" "${MEITUAN_BUDGET_PREFLIGHT_RETRIES:-3}" \
    "$REPORT_PYTHON" store-inspection/meituan_budget_cdp.py --period "$PERIOD" --mode preview --limit "$LIMIT" --preflight \
    --preflight-result-output "$MEITUAN_PREFLIGHT_RESULT"
  MEITUAN_PREFLIGHT_RC=$?
  set -e
  MEITUAN_PASSED_STORES=""
  if [[ -f "$MEITUAN_PREFLIGHT_RESULT" ]]; then
    MEITUAN_PASSED_STORES="$($PYTHON - "$MEITUAN_PREFLIGHT_RESULT" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(",".join(str(item) for item in payload.get("successfulKeywords", []) if item))
for item in payload.get("failed", []):
    print(
        f"单店预检失败，已隔离跳过：{item.get('keyword') or item.get('store')}："
        f"{item.get('failure_type')}：{item.get('error')}",
        file=sys.stderr,
    )
PY
)"
  fi
  if [[ -n "$MEITUAN_PASSED_STORES" ]]; then
    if (( MEITUAN_PREFLIGHT_RC == 0 )); then
      record_task_run "$TASK_ID" success --message "美团${PERIOD}预算提交前预检全部通过。" --step "美团${PERIOD}预算提交前预检" --log-path "$RUN_LOG" --returncode 0
    else
      record_task_run "$TASK_ID" success --message "美团${PERIOD}预算提交前预检部分通过；失败门店已隔离，其余继续。" --step "美团${PERIOD}预算提交前预检" --log-path "$RUN_LOG" --returncode 0
    fi
    echo
    echo "执行美团${PERIOD}预算真实提交（仅预检通过门店）..."
    run_budget_step "美团${PERIOD}预算" "${MEITUAN_BUDGET_TIMEOUT_SECONDS:-1800}" "${BUDGET_STEP_RETRIES:-2}" \
      "$REPORT_PYTHON" store-inspection/meituan_budget_cdp.py --period "$PERIOD" --mode commit --stores "$MEITUAN_PASSED_STORES" || true
  else
    echo "美团${PERIOD}预算没有任何门店通过预检，已跳过真实提交。"
    record_task_run "$TASK_ID" failed --message "美团${PERIOD}预算没有任何门店通过预检。" --step "美团${PERIOD}预算提交前预检" --log-path "$RUN_LOG" --returncode "${MEITUAN_PREFLIGHT_RC:-1}"
    FAILED_STEPS+=("美团${PERIOD}预算提交前预检")
  fi
else
  echo "执行美团${PERIOD}预算页面预演..."
  run_budget_step "美团${PERIOD}预算" "${MEITUAN_BUDGET_TIMEOUT_SECONDS:-1800}" "${BUDGET_STEP_RETRIES:-2}" "$REPORT_PYTHON" store-inspection/meituan_budget_cdp.py --period "$PERIOD" --mode "$MODE" --limit "$LIMIT" || true
fi

echo
if [[ "$MODE" == "commit" ]]; then
  if [[ "$PERIOD" == "午餐" ]]; then
    BALANCE_NOTIFY_PERIOD="上午"
  else
    BALANCE_NOTIFY_PERIOD="下午"
  fi
  run_support_step "${BALANCE_NOTIFY_PERIOD}推广低余额通知" "${PROMO_BALANCE_NOTIFY_TIMEOUT_SECONDS:-60}" 1 \
    "$PYTHON" scripts/agent_task_notifier.py --promo-balance-period "$BALANCE_NOTIFY_PERIOD" || true
fi

echo
echo "刷新运营总看板数据..."
run_support_step "推广预算重试策略刷新" "${BUDGET_REFRESH_TIMEOUT_SECONDS:-120}" 1 "$PYTHON" scripts/build_promo_budget_retry_plan.py || true
run_support_step "运营总看板数据刷新" "${BUDGET_REFRESH_TIMEOUT_SECONDS:-120}" 1 "$PYTHON" scripts/build_workbench_data.py || true
if [[ "$MODE" == "commit" ]]; then
  echo "发布运营总看板..."
  run_support_step "运营总看板发布" "${WORKBENCH_DEPLOY_TIMEOUT_SECONDS:-240}" "${DEPLOY_STEP_RETRIES:-2}" env OPERATION_ROOT="$ROOT" /bin/zsh "$DEPLOY_RUNNER" || true
else
  echo "预演模式：不发布云端看板。"
fi

echo "完成：$(date '+%Y-%m-%d %H:%M:%S')"
echo "日志：$RUN_LOG"
if (( ${#FAILED_STEPS[@]} > 0 )); then
  echo "失败步骤：${(j:、:)FAILED_STEPS}"
  record_task_run "$TASK_ID" failed --message "${PERIOD}预算失败步骤：${(j:、:)FAILED_STEPS}" --step "${PERIOD}预算汇总" --log-path "$RUN_LOG" --returncode 70
  exit 70
fi
if (( ${#SUPPORT_FAILED_STEPS[@]} > 0 )); then
  echo "预算设置成功，附属步骤失败：${(j:、:)SUPPORT_FAILED_STEPS}"
  record_task_run "$TASK_ID" success \
    --message "${PERIOD}预算设置成功；附属步骤失败：${(j:、:)SUPPORT_FAILED_STEPS}。" \
    --step "${PERIOD}预算汇总" --log-path "$RUN_LOG" --returncode 0 \
    --extra "support_failures=${(j:、:)SUPPORT_FAILED_STEPS}"
else
  record_task_run "$TASK_ID" success --message "${PERIOD}预算全部步骤完成。" --step "${PERIOD}预算汇总" --log-path "$RUN_LOG" --returncode 0
fi
