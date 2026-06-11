#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

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

CURRENT_HOUR="$(date +%H)"
CURRENT_MINUTE="$(date +%M)"
CURRENT_TOTAL_MINUTES=$((10#$CURRENT_HOUR * 60 + 10#$CURRENT_MINUTE))
ALLOWED_WINDOW_LABEL="$(printf '%02d:%02d-%02d:%02d' \
  $((ALLOWED_START_MINUTES / 60)) $((ALLOWED_START_MINUTES % 60)) \
  $((ALLOWED_END_MINUTES / 60)) $((ALLOWED_END_MINUTES % 60)))"

if [[ "${ALLOW_OUTSIDE_BUDGET_WINDOW:-0}" != "1" ]] \
  && (( CURRENT_TOTAL_MINUTES < ALLOWED_START_MINUTES || CURRENT_TOTAL_MINUTES > ALLOWED_END_MINUTES )); then
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

"$PYTHON" scripts/sync_promo_budget_overrides.py
"$NODE" scripts/build_promo_budget_preview.mjs

echo
echo "执行饿了么${PERIOD}预算真实提交..."
/bin/zsh scripts/run_eleme_automation.zsh --time "$TIME_POINT" --mode commit --limit all

echo
echo "执行美团${PERIOD}预算真实提交..."
"$REPORT_PYTHON" store-inspection/meituan_budget_cdp.py --period "$PERIOD"

echo
echo "刷新并发布运营总看板..."
"$PYTHON" scripts/build_workbench_data.py
/bin/zsh scripts/deploy_workbench_to_cloud.zsh

echo "完成：$(date '+%Y-%m-%d %H:%M:%S')"
echo "日志：$RUN_LOG"
