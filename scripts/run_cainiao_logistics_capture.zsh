#!/bin/zsh
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYTHON="${CAINIAO_CAPTURE_PYTHON:-python3}"
ADB="${ANDROID_ADB_BIN:-$HOME/Library/Android/sdk/platform-tools/adb}"
DETAILS="${CAINIAO_MAX_DETAILS:-12}"
SCROLL_PAGES="${CAINIAO_SCROLL_PAGES:-1}"
STAMP="$(date +%Y%m%d-%H%M%S)"
EVIDENCE_DIR="$ROOT/outputs/cainiao_logistics/scheduled-$STAMP"
TASK_ID="ops.cainiao_logistics"
LOG_DIR="$ROOT/outputs/cainiao_logistics_launchd"
LOG_FILE="$LOG_DIR/stdout.log"
TASK_STATE_FINALIZED="false"

export ANDROID_ADB_BIN="$ADB"

mkdir -p "$ROOT/outputs/cainiao_logistics" "$LOG_DIR"

record_task_run() {
  "$PYTHON" "$ROOT/scripts/record_task_run.py" "$@" >/dev/null 2>&1 || true
}

finish_task_state() {
  local rc="$?"
  if [[ "$TASK_STATE_FINALIZED" == "true" ]]; then
    return
  fi
  if [[ "$rc" -eq 0 ]]; then
    record_task_run "$TASK_ID" success --message "菜鸟物流采集完成。" --step "采集并写入物流看板" --log-path "$LOG_FILE" --returncode 0
  else
    local message="菜鸟物流采集失败。"
    if [[ -f "$ROOT/outputs/cainiao_logistics/latest.json" ]]; then
      message="$("$PYTHON" - <<'PY' 2>/dev/null || echo "菜鸟物流采集失败。"
import json
from pathlib import Path

path = Path("outputs/cainiao_logistics/latest.json")
payload = json.loads(path.read_text(encoding="utf-8"))
print(payload.get("error") or payload.get("message") or "菜鸟物流采集失败。")
PY
)"
    fi
    record_task_run "$TASK_ID" failed --message "$message" --step "采集并写入物流看板" --log-path "$LOG_FILE" --returncode "$rc"
  fi
}
trap finish_task_state EXIT

{
  echo
  echo "[$(date '+%F %T')] 菜鸟物流采集开始"
  record_task_run "$TASK_ID" running --message "菜鸟物流采集开始。" --step "采集并写入物流看板" --log-path "$LOG_FILE"

  "$PYTHON" scripts/cainiao_logistics_capture.py \
    --scan-details \
    --max-details "$DETAILS" \
    --scroll-pages "$SCROLL_PAGES" \
    --evidence-dir "$EVIDENCE_DIR" \
    --commit
  rc="$?"

  if [[ "$rc" -eq 0 ]]; then
    record_task_run "$TASK_ID" success --message "菜鸟物流采集完成。" --step "采集并写入物流看板" --log-path "$LOG_FILE" --returncode 0
    echo "[$(date '+%F %T')] 菜鸟物流采集完成"
  else
    record_task_run "$TASK_ID" failed --message "菜鸟物流采集失败，查看证据包：$EVIDENCE_DIR" --step "采集并写入物流看板" --log-path "$LOG_FILE" --returncode "$rc"
    echo "[$(date '+%F %T')] 菜鸟物流采集失败，退出码：$rc"
  fi
  TASK_STATE_FINALIZED="true"
  exit "$rc"
} >> "$LOG_FILE" 2>&1
