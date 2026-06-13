#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

STATE_PYTHON="/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
if [ ! -x "$STATE_PYTHON" ]; then
  STATE_PYTHON="python3"
fi
TASK_ID="growth.promo_budget"
TASK_STEP="初始化"

record_task_run() {
  "$STATE_PYTHON" scripts/record_task_run.py "$@" || true
}

failure_tail() {
  if [[ -f "$RUN_LOG" ]]; then
    tail -n 18 "$RUN_LOG" | tr '\n' ' ' | sed 's/[[:space:]][[:space:]]*/ /g'
  fi
}


platform_recovery_action() {
  local platform_key="$1"
  if [[ "$platform_key" == "eleme" ]]; then
    echo "先确认饿了么后台登录和验证码，再打开点金推广页复核目标门店预算。"
  else
    echo "先确认美团点金推广页已在本机 Chrome 打开并登录，再复核门店映射和预算弹窗。"
  fi
}

record_platform_state() {
  local platform_key="$1"
  local platform_name="$2"
  local status="$3"
  local message="$4"
  local rc="${5:-}"
  local recovery
  recovery="$(platform_recovery_action "$platform_key")"
  local args=(
    "$TASK_ID" "$status"
    --message "$message"
    --step "${platform_name}${PERIOD}预算真实提交"
    --log-path "$RUN_LOG"
    --extra "${platform_key}_status=${status}"
    --extra "${platform_key}_message=${message}"
    --extra "${platform_key}_recovery=${recovery}"
  )
  if [[ -n "$rc" ]]; then
    args+=(--returncode "$rc")
  fi
  record_task_run "${args[@]}"
}

run_platform_budget() {
  local platform_key="$1"
  local platform_name="$2"
  shift 2
  TASK_STEP="${platform_name}${PERIOD}预算真实提交"
  record_task_run "$TASK_ID" running --message "$TASK_STEP" --step "$TASK_STEP" --log-path "$RUN_LOG"
  record_platform_state "$platform_key" "$platform_name" running "$TASK_STEP"
  set +e
  "$@"
  local rc="$?"
  set -e
  if [[ "$rc" -ne 0 ]]; then
    local detail
    detail="$(failure_tail)"
    record_platform_state "$platform_key" "$platform_name" failed "${platform_name}${PERIOD}预算失败：${detail}" "$rc"
    return "$rc"
  fi
  record_platform_state "$platform_key" "$platform_name" success "${platform_name}${PERIOD}预算提交完成。" "$rc"
}

PERIOD="auto"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --period)
      PERIOD="$2"
      shift 2
      ;;
    *)
      echo "未知参数：$1"
      exit 1
      ;;
  esac
done

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
    ALLOWED_START_MINUTES=$((10 * 60 + 20))
    ALLOWED_END_MINUTES=$((10 * 60 + 50))
    ;;
  晚餐)
    TIME_POINT="17:30"
    ALLOWED_START_MINUTES=$((17 * 60 + 20))
    ALLOWED_END_MINUTES=$((17 * 60 + 50))
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

finish_task_state() {
  local rc="$?"
  if [[ "$rc" -eq 0 ]]; then
    record_task_run "$TASK_ID" success --message "${PERIOD}预算初始化完成。" --step "$TASK_STEP" --log-path "$RUN_LOG" --returncode "$rc"
  else
    local detail
    detail="$(failure_tail)"
    record_task_run "$TASK_ID" failed --message "${PERIOD}预算初始化失败：${TASK_STEP}。${detail}" --step "$TASK_STEP" --log-path "$RUN_LOG" --returncode "$rc"
  fi
}
trap finish_task_state EXIT

CURRENT_HOUR="$(date +%H)"
CURRENT_MINUTE="$(date +%M)"
CURRENT_TOTAL_MINUTES=$((10#$CURRENT_HOUR * 60 + 10#$CURRENT_MINUTE))
ALLOWED_WINDOW_LABEL="$(printf '%02d:%02d-%02d:%02d' \
  $((ALLOWED_START_MINUTES / 60)) $((ALLOWED_START_MINUTES % 60)) \
  $((ALLOWED_END_MINUTES / 60)) $((ALLOWED_END_MINUTES % 60)))"

record_task_run "$TASK_ID" running --message "${PERIOD}预算初始化开始，允许窗口 ${ALLOWED_WINDOW_LABEL}。" --step "$TASK_STEP" --log-path "$RUN_LOG"

if [[ "${ALLOW_OUTSIDE_BUDGET_WINDOW:-0}" != "1" ]] \
  && (( CURRENT_TOTAL_MINUTES < ALLOWED_START_MINUTES || CURRENT_TOTAL_MINUTES > ALLOWED_END_MINUTES )); then
  TASK_STEP="允许窗口检查"
  record_task_run "$TASK_ID" failed --message "当前时间不在 ${PERIOD}预算允许窗口 ${ALLOWED_WINDOW_LABEL}。" --step "$TASK_STEP" --log-path "$RUN_LOG" --returncode 64 --failure-type outside_allowed_window
  echo "拒绝执行：当前时间 $(date '+%Y-%m-%d %H:%M:%S') 不在 ${PERIOD}预算允许窗口 ${ALLOWED_WINDOW_LABEL}。"
  echo "如需手动补跑，请显式设置 ALLOW_OUTSIDE_BUDGET_WINDOW=1。"
  exit 64
fi

NODE="/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
PYTHON="/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
if [ ! -x "$PYTHON" ]; then
  PYTHON="python3"
fi
REPORT_PYTHON="$ROOT/business-report-dashboard/.venv/bin/python"
if [ ! -x "$REPORT_PYTHON" ]; then
  REPORT_PYTHON="$PYTHON"
fi

echo "== ${TIME_POINT} ${PERIOD}预算初始化 =="
echo "开始：$(date '+%Y-%m-%d %H:%M:%S')"
echo "允许窗口：${ALLOWED_WINDOW_LABEL}"

TASK_STEP="同步云端预算配置"
record_task_run "$TASK_ID" running --message "$TASK_STEP" --step "$TASK_STEP" --log-path "$RUN_LOG"
"$PYTHON" scripts/sync_promo_budget_overrides.py

TASK_STEP="生成推广预算预览"
record_task_run "$TASK_ID" running --message "$TASK_STEP" --step "$TASK_STEP" --log-path "$RUN_LOG"
"$NODE" scripts/build_promo_budget_preview.mjs

echo
echo "执行饿了么${PERIOD}预算真实提交..."
run_platform_budget eleme 饿了么 /bin/zsh scripts/run_eleme_automation.zsh --time "$TIME_POINT" --mode commit --limit all

echo
echo "执行美团${PERIOD}预算真实提交..."
run_platform_budget meituan 美团 "$REPORT_PYTHON" store-inspection/meituan_budget_cdp.py --period "$PERIOD"

echo
echo "刷新并发布运营总看板..."
TASK_STEP="刷新运营总看板数据"
record_task_run "$TASK_ID" running --message "$TASK_STEP" --step "$TASK_STEP" --log-path "$RUN_LOG"
"$PYTHON" scripts/build_workbench_data.py
TASK_STEP="发布运营总看板"
record_task_run "$TASK_ID" running --message "$TASK_STEP" --step "$TASK_STEP" --log-path "$RUN_LOG"
/bin/zsh scripts/deploy_workbench_to_cloud.zsh

echo "完成：$(date '+%Y-%m-%d %H:%M:%S')"
echo "日志：$RUN_LOG"
