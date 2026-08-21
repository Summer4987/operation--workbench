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
STORE_FILTER=""
STORE_FILTERS=""
SHOP_ID_FILTER=""

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
    --store)
      STORE_FILTER="$2"
      shift 2
      ;;
    --stores)
      STORE_FILTERS="$2"
      shift 2
      ;;
    --shop-id)
      SHOP_ID_FILTER="$2"
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

RUN_STARTED_EPOCH="$(date +%s)"

echo "== 饿了么点金自动化 =="
echo "时间点：$TIME_POINT"
echo "模式：$MODE"
echo "数量：$LIMIT"
if [[ -n "$STORE_FILTER" ]]; then
  echo "门店过滤：$STORE_FILTER"
fi
if [[ -n "$STORE_FILTERS" ]]; then
  echo "门店列表：$STORE_FILTERS"
fi
if [[ -n "$SHOP_ID_FILTER" ]]; then
  echo "shopId过滤：$SHOP_ID_FILTER"
fi
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

latest_exec_result() {
  "$PYTHON_FALLBACK" - <<PY
from pathlib import Path

started = int("${EXEC_STARTED_EPOCH}")
mode = "${EXEC_OUTPUT_MODE}"
files = sorted(Path("outputs/dianjin_automation").glob(f"eleme_execution_{mode}_*.json"), key=lambda p: p.stat().st_mtime)
fresh = [p for p in files if p.stat().st_mtime >= started]
print(fresh[-1] if fresh else "")
PY
}

execution_result_ok() {
  local result_file="$1"
  "$PYTHON_FALLBACK" - "$result_file" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(1)
if not payload.get("ok"):
    raise SystemExit(1)
if payload.get("total") == 0 and not payload.get("verifiedNoChanges"):
    raise SystemExit(1)
if any(not item.get("ok") for item in payload.get("results", [])):
    raise SystemExit(1)
PY
}

stores_for_split_retry() {
  local result_file="${1:-}"
  "$PYTHON_FALLBACK" - "$PREVIEW_FILE" "$result_file" <<'PY'
import json
import sys
from pathlib import Path

preview_path = Path(sys.argv[1])
result_path = Path(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] else None
stores = []

if result_path and result_path.exists():
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
        stores = [
            str(item.get("store") or "").strip()
            for item in result.get("results", [])
            if not item.get("ok") and str(item.get("store") or "").strip()
        ]
    except Exception:
        stores = []

if not stores:
    preview = json.loads(preview_path.read_text(encoding="utf-8"))
    for row in preview.get("rows", []):
        action = str(row.get("action") or "")
        store = str(row.get("store") or "").strip()
        if not store or not row.get("canExecute"):
            continue
        if action and action not in {"预算已符合", "出价已符合", "无需调整"}:
            stores.append(store)

seen = set()
for store in stores:
    if store in seen:
        continue
    seen.add(store)
    print(store)
PY
}

run_split_retry() {
  local result_file="${1:-}"
  local failed=0
  local total=0
  local retry_started
  local retry_result

  echo
  echo "整批执行未完全成功，开始按门店拆分重试..."
  while IFS= read -r retry_store; do
    [[ -n "$retry_store" ]] || continue
    total=$((total + 1))
    echo
    echo "== 拆分重试：$retry_store =="
    retry_started="$(date +%s)"
    if ! run_with_timeout "${ELEME_STORE_RETRY_TIMEOUT_SECONDS:-300}" "$NODE" scripts/eleme_dianjin_adapter.mjs execute-preview --file "$PREVIEW_FILE" --store "$retry_store" ${MODE_COMMIT_ARG[@]}; then
      echo "拆分重试失败：$retry_store"
      failed=$((failed + 1))
      continue
    fi
    retry_result="$("$PYTHON_FALLBACK" - "$retry_started" "$EXEC_OUTPUT_MODE" <<'PY'
from pathlib import Path
import sys

started = int(sys.argv[1])
mode = sys.argv[2]
files = sorted(Path("outputs/dianjin_automation").glob(f"eleme_execution_{mode}_*.json"), key=lambda p: p.stat().st_mtime)
fresh = [p for p in files if p.stat().st_mtime >= started]
print(fresh[-1] if fresh else "")
PY
)"
    if [[ -z "$retry_result" ]] || ! execution_result_ok "$retry_result"; then
      echo "拆分重试未确认成功：$retry_store"
      failed=$((failed + 1))
      continue
    fi
    echo "拆分重试成功：$retry_store，结果：$retry_result"
  done < <(stores_for_split_retry "$result_file")

  if [[ "$total" -eq 0 ]]; then
    echo "没有可拆分重试的门店。"
    return 1
  fi
  if [[ "$failed" -ne 0 ]]; then
    echo "拆分重试完成，但失败 ${failed}/${total}。"
    return 1
  fi
  echo "拆分重试全部成功：${total}/${total}。"
  return 0
}

if ! /usr/bin/curl -fsS "http://127.0.0.1:9222/json/version" >/dev/null 2>&1; then
  echo "Chrome 调试端口未连接，尝试启动常用 Chrome..."
  /usr/bin/python3 "$ROOT/business-report-dashboard/chrome_cdp_reports.py" start-chrome || true
fi

"$NODE" scripts/eleme_dianjin_adapter.mjs probe

STATE_FILE="outputs/dianjin_automation/current_state_${SAFE_TIME}_all.json"
PREVIEW_FILE="outputs/dianjin_automation/execution_preview_${SAFE_TIME}.json"

if [[ "$TIME_POINT" == "10:30" || "$TIME_POINT" == "16:30" ]]; then
  echo
  echo "使用单店斗金计划批量处理（原分店资金）页面生成预算任务..."
  "$NODE" scripts/build_promo_budget_preview.mjs
  "$NODE" scripts/build_eleme_budget_execution_preview.mjs --time "$TIME_POINT" --output "$PREVIEW_FILE"
else
  echo
  echo "读取饿了么后台门店状态..."
  "$NODE" scripts/eleme_dianjin_adapter.mjs probe-store --store 金融街店
  "$NODE" scripts/eleme_dianjin_adapter.mjs probe-store --store 金融街店 --page 2

  echo
  echo "分析当前状态并生成执行预览..."
  "$NODE" scripts/eleme_dianjin_adapter.mjs analyze-state-combined --time "$TIME_POINT" --since "$RUN_STARTED_EPOCH" --output "$STATE_FILE"
  "$NODE" scripts/export_current_state_for_ui.mjs "$STATE_FILE"
  "$NODE" scripts/build_execution_preview.mjs "$STATE_FILE" --time "$TIME_POINT"
fi

if [[ "$MODE" == "preview" ]]; then
  echo
  echo "只生成预览，不打开执行弹窗。"
  echo "预览文件：$PREVIEW_FILE"
  echo "结束：$(date '+%Y-%m-%d %H:%M:%S')"
  exit 0
fi

EXEC_ARGS=(execute-preview --file "$PREVIEW_FILE" --limit "$LIMIT")
if [[ -n "$STORE_FILTER" ]]; then
  EXEC_ARGS+=(--store "$STORE_FILTER")
fi
if [[ -n "$STORE_FILTERS" ]]; then
  EXEC_ARGS+=(--stores "$STORE_FILTERS")
fi
if [[ -n "$SHOP_ID_FILTER" ]]; then
  EXEC_ARGS+=(--shopId "$SHOP_ID_FILTER")
fi
if [[ "$MODE" == "commit" ]]; then
  EXEC_ARGS+=(--commit)
fi
MODE_COMMIT_ARG=()
if [[ "$MODE" == "commit" ]]; then
  MODE_COMMIT_ARG=(--commit)
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
set +e
run_with_timeout "${ELEME_EXECUTE_TIMEOUT_SECONDS:-1500}" "$NODE" scripts/eleme_dianjin_adapter.mjs "${EXEC_ARGS[@]}"
EXEC_STATUS=$?
set -e

LATEST_EXEC_RESULT="$(latest_exec_result)"
if [[ "$EXEC_STATUS" -ne 0 ]] || [[ -z "$LATEST_EXEC_RESULT" ]] || ! execution_result_ok "$LATEST_EXEC_RESULT"; then
  if [[ -n "$STORE_FILTER" || -n "$STORE_FILTERS" || -n "$SHOP_ID_FILTER" || "$LIMIT" != "all" ]]; then
    echo "执行失败：饿了么${MODE}未完全成功，且当前使用了过滤条件，拒绝自动扩大重试范围。"
    exit 71
  fi
  if ! run_split_retry "$LATEST_EXEC_RESULT"; then
    echo "执行失败：整批执行和拆分重试均未完全成功。"
    exit 71
  fi
  LATEST_EXEC_RESULT="$(latest_exec_result)"
fi
echo "执行结果：$LATEST_EXEC_RESULT"

echo
echo "完成：$(date '+%Y-%m-%d %H:%M:%S')"
echo "日志：$RUN_LOG"
}

main "$@" >> "$RUN_LOG" 2>&1
