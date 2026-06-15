#!/bin/zsh
set -euo pipefail

ROOT="${OPERATION_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$ROOT"
ELEME_RUNNER="${ELEME_AUTOMATION_RUNNER:-scripts/run_eleme_automation.zsh}"
DEPLOY_RUNNER="${WORKBENCH_DEPLOY_RUNNER:-scripts/deploy_workbench_to_cloud.zsh}"

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
PYTHON="/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
if [ ! -x "$PYTHON" ]; then
  PYTHON="python3"
fi
REPORT_PYTHON="$ROOT/business-report-dashboard/.venv/bin/python"
if [ ! -x "$REPORT_PYTHON" ]; then
  REPORT_PYTHON="$PYTHON"
fi

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
record_task_run "$TASK_ID" running --message "${PERIOD}预算执行开始。" --step "${PERIOD}预算初始化" --log-path "$RUN_LOG"

run_with_timeout() {
  local seconds="$1"
  shift
  "$@" &
  local child_pid=$!
  (
    sleep "$seconds"
    if kill -0 "$child_pid" 2>/dev/null; then
      echo "步骤超时：${seconds}s，已终止：$*"
      kill -TERM "$child_pid" 2>/dev/null || true
      sleep 2
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
    if run_with_timeout "$seconds" "$@"; then
      return 0
    fi
    exit_status=$?
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
  if run_with_retry "$step" "$seconds" "$attempts" "$@"; then
    record_task_run "$TASK_ID" success --message "${step}完成。" --step "$step" --log-path "$RUN_LOG" --returncode 0
    return 0
  fi
  local rc=$?
  record_task_run "$TASK_ID" failed --message "${step}失败，查看日志：$RUN_LOG" --step "$step" --log-path "$RUN_LOG" --returncode "$rc"
  FAILED_STEPS+=("$step")
  return "$rc"
}

run_required_step() {
  local step="$1"
  local seconds="$2"
  shift 2
  record_task_run "$TASK_ID" running --message "${step}开始。" --step "$step" --log-path "$RUN_LOG"
  if run_with_timeout "$seconds" "$@"; then
    record_task_run "$TASK_ID" success --message "${step}完成。" --step "$step" --log-path "$RUN_LOG" --returncode 0
    return 0
  fi
  local rc=$?
  record_task_run "$TASK_ID" failed --message "${step}失败，查看日志：$RUN_LOG" --step "$step" --log-path "$RUN_LOG" --returncode "$rc"
  return "$rc"
}

run_node_from_safe_cwd() {
  local script_path="$1"
  shift
  cd "$HOME/Library/Scripts/xiong-operation"
  "$NODE" "$script_path" "$@"
}

if run_required_step "${PERIOD}预算配置同步" "${BUDGET_CONFIG_SYNC_TIMEOUT_SECONDS:-120}" "$PYTHON" "$ROOT/scripts/sync_promo_budget_overrides.py"; then
  :
else
  rc=$?
  exit "$rc"
fi
if run_required_step "${PERIOD}预算预览生成" "${BUDGET_PREVIEW_BUILD_TIMEOUT_SECONDS:-120}" run_node_from_safe_cwd "$ROOT/scripts/build_promo_budget_preview.mjs"; then
  :
else
  rc=$?
  exit "$rc"
fi

FAILED_STEPS=()

echo
if [[ "$MODE" == "commit" ]]; then
  echo "执行饿了么${PERIOD}预算真实提交..."
else
  echo "执行饿了么${PERIOD}预算页面预演..."
fi
run_budget_step "饿了么${PERIOD}预算" "${ELEME_BUDGET_TIMEOUT_SECONDS:-540}" "${BUDGET_STEP_RETRIES:-2}" /bin/zsh "$ELEME_RUNNER" --time "$TIME_POINT" --mode "$MODE" --limit "$LIMIT" || true

echo
if [[ "$MODE" == "commit" ]]; then
  echo "执行美团${PERIOD}预算真实提交..."
  run_budget_step "美团${PERIOD}预算" "${MEITUAN_BUDGET_TIMEOUT_SECONDS:-900}" "${BUDGET_STEP_RETRIES:-2}" "$REPORT_PYTHON" store-inspection/meituan_budget_cdp.py --period "$PERIOD" --mode commit --limit "$LIMIT" || true
else
  echo "执行美团${PERIOD}预算页面预演..."
  run_budget_step "美团${PERIOD}预算" "${MEITUAN_BUDGET_TIMEOUT_SECONDS:-900}" "${BUDGET_STEP_RETRIES:-2}" "$REPORT_PYTHON" store-inspection/meituan_budget_cdp.py --period "$PERIOD" --mode "$MODE" --limit "$LIMIT" || true
fi

echo
echo "刷新运营总看板数据..."
run_budget_step "推广预算重试策略刷新" "${BUDGET_REFRESH_TIMEOUT_SECONDS:-120}" 1 "$PYTHON" scripts/build_promo_budget_retry_plan.py || true
run_budget_step "运营总看板数据刷新" "${BUDGET_REFRESH_TIMEOUT_SECONDS:-120}" 1 "$PYTHON" scripts/build_workbench_data.py || true
if [[ "$MODE" == "commit" ]]; then
  echo "发布运营总看板..."
  run_budget_step "运营总看板发布" "${WORKBENCH_DEPLOY_TIMEOUT_SECONDS:-240}" "${DEPLOY_STEP_RETRIES:-2}" /bin/zsh "$DEPLOY_RUNNER" || true
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
record_task_run "$TASK_ID" success --message "${PERIOD}预算全部步骤完成。" --step "${PERIOD}预算汇总" --log-path "$RUN_LOG" --returncode 0
