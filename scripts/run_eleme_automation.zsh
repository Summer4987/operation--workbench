#!/bin/zsh
set -euo pipefail

ROOT="${OPERATION_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$ROOT"

NODE="/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
PYTHON_FALLBACK="/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
if [ ! -x "$PYTHON_FALLBACK" ]; then
  PYTHON_FALLBACK="python3"
fi
TIME_POINT=""
MODE="rehearse"
LIMIT="all"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --time)
      TIME_POINT="$2"
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

if [[ -z "$TIME_POINT" ]]; then
  echo "缺少执行时间，请使用 --time 10:40 这样的格式。"
  exit 1
fi

SAFE_TIME="${TIME_POINT/:/}"
LOG_DIR="$ROOT/outputs/dianjin_automation/logs"
mkdir -p "$LOG_DIR"
RUN_LOG="$LOG_DIR/eleme_${SAFE_TIME}_$(date +%Y%m%d_%H%M%S).log"

main() {

echo "== 饿了么点金自动化 =="
echo "时间点：$TIME_POINT"
echo "模式：$MODE"
echo "数量：$LIMIT"
echo "开始：$(date '+%Y-%m-%d %H:%M:%S')"
echo

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

if ! /usr/bin/curl -fsS "http://127.0.0.1:9222/json/version" >/dev/null 2>&1; then
  echo "Chrome 调试端口未连接，尝试启动常用 Chrome..."
  /usr/bin/python3 "$ROOT/business-report-dashboard/chrome_cdp_reports.py" start-chrome || true
fi

"$NODE" scripts/eleme_dianjin_adapter.mjs probe

echo
echo "读取饿了么后台门店状态..."
"$NODE" scripts/eleme_dianjin_adapter.mjs probe-store --store 金融街店
"$NODE" scripts/eleme_dianjin_adapter.mjs probe-store --store 金融街店 --page 2

STATE_FILE="outputs/dianjin_automation/current_state_${SAFE_TIME}_all.json"
PREVIEW_FILE="outputs/dianjin_automation/execution_preview_${SAFE_TIME}.json"

echo
echo "分析当前状态并生成执行预览..."
"$NODE" scripts/eleme_dianjin_adapter.mjs analyze-state-combined --time "$TIME_POINT" --output "$STATE_FILE"
"$NODE" scripts/export_current_state_for_ui.mjs "$STATE_FILE"
"$NODE" scripts/build_execution_preview.mjs "$STATE_FILE" --time "$TIME_POINT"

if [[ "$MODE" == "preview" ]]; then
  echo
  echo "只生成预览，不打开执行弹窗。"
  echo "预览文件：$PREVIEW_FILE"
  echo "结束：$(date '+%Y-%m-%d %H:%M:%S')"
  exit 0
fi

EXEC_ARGS=(execute-preview --file "$PREVIEW_FILE" --limit "$LIMIT")
if [[ "$MODE" == "commit" ]]; then
  EXEC_ARGS+=(--commit)
fi
EXEC_OUTPUT_MODE="rehearse"
if [[ "$MODE" == "commit" ]]; then
  EXEC_OUTPUT_MODE="commit"
fi
EXEC_STARTED_EPOCH="$(date +%s)"

echo
if [[ "$MODE" == "commit" ]]; then
  echo "开始正式执行..."
else
  echo "开始执行演练..."
fi
run_with_timeout "${ELEME_EXECUTE_TIMEOUT_SECONDS:-420}" "$NODE" scripts/eleme_dianjin_adapter.mjs "${EXEC_ARGS[@]}"

LATEST_EXEC_RESULT="$("$PYTHON_FALLBACK" - <<PY
from pathlib import Path
import os

started = int("${EXEC_STARTED_EPOCH}")
mode = "${EXEC_OUTPUT_MODE}"
files = sorted(Path("outputs/dianjin_automation").glob(f"eleme_execution_{mode}_*.json"), key=lambda p: p.stat().st_mtime)
fresh = [p for p in files if p.stat().st_mtime >= started]
print(fresh[-1] if fresh else "")
PY
)"
if [[ -z "$LATEST_EXEC_RESULT" ]]; then
  echo "执行失败：没有生成新的饿了么${MODE}结果文件，拒绝判定为成功。"
  exit 71
fi
echo "执行结果：$LATEST_EXEC_RESULT"

echo
echo "完成：$(date '+%Y-%m-%d %H:%M:%S')"
echo "日志：$RUN_LOG"
}

main "$@" >> "$RUN_LOG" 2>&1
