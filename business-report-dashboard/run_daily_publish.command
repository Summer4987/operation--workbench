#!/bin/zsh
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKSPACE_DIR="$(cd "$PROJECT_DIR/.." && pwd)"
SERVER="${OPERATION_CLOUD_SERVER:-ubuntu@139.155.148.169}"
REMOTE_DIR="${REPORT_CLOUD_REMOTE_DIR:-/var/www/html/business-report-dashboard}"
REMOTE_URL="${REPORT_CLOUD_PUBLIC_URL:-http://139.155.148.169/business-report-dashboard/}"
SCHEDULER_LOG_DIR="/Users/summer/Library/Logs/xiong-daily-report"
SSH_OPTS=(-o StrictHostKeyChecking=accept-new)
IDENTITY_FILE="${OPERATION_CLOUD_IDENTITY_FILE:-$HOME/.ssh/xiong_operation_cloud_ed25519}"
if [[ -f "$IDENTITY_FILE" ]]; then
  SSH_OPTS+=(-i "$IDENTITY_FILE")
fi

cd "$PROJECT_DIR"

PUBLISH_ONLY="false"
if [[ "${1:-}" == "--publish-only" ]]; then
  PUBLISH_ONLY="true"
fi

PYTHON="$PROJECT_DIR/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  PYTHON="/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
fi
if [ ! -x "$PYTHON" ]; then
  PYTHON="python3"
fi
TASK_ID="ops.daily_report"
TASK_STEP="初始化"
RUN_LOG="$SCHEDULER_LOG_DIR/daily-publish-$(date +%F).log"
mkdir -p "$SCHEDULER_LOG_DIR"

record_task_run() {
  "$PYTHON" "$WORKSPACE_DIR/scripts/record_task_run.py" "$@" || true
}

finish_task_state() {
  local rc="$?"
  if [[ "$rc" -eq 0 ]]; then
    record_task_run "$TASK_ID" success --message "日报采集并发布完成。" --step "$TASK_STEP" --log-path "$RUN_LOG" --returncode "$rc"
  else
    record_task_run "$TASK_ID" failed --message "日报采集发布失败：${TASK_STEP}。" --step "$TASK_STEP" --log-path "$RUN_LOG" --returncode "$rc"
  fi
}
trap finish_task_state EXIT
record_task_run "$TASK_ID" running --message "日报采集发布开始。" --step "$TASK_STEP" --log-path "$RUN_LOG"

if [[ "$PUBLISH_ONLY" != "true" ]]; then
  echo "正在采集饿了么 / 美团日报数据..."
  TASK_STEP="采集平台日报数据"
  record_task_run "$TASK_ID" running --message "$TASK_STEP" --step "$TASK_STEP" --log-path "$RUN_LOG"
  "$PYTHON" chrome_cdp_reports.py daily
else
  echo "只发布已有本地日报文件，不重新采集平台数据。"
fi

echo ""
echo "正在确认本地看板文件..."
TASK_STEP="确认本地看板文件"
record_task_run "$TASK_ID" running --message "$TASK_STEP" --step "$TASK_STEP" --log-path "$RUN_LOG"
test -f "$PROJECT_DIR/dashboard/index.html"
test -f "$PROJECT_DIR/data/latest.json"
test -f "$PROJECT_DIR/data/unified_daily.csv"
test -f "$PROJECT_DIR/data/unified_reviews.csv"

echo ""
echo "正在准备云服务器目录..."
TASK_STEP="准备云服务器目录"
record_task_run "$TASK_ID" running --message "$TASK_STEP" --step "$TASK_STEP" --log-path "$RUN_LOG"
ssh "${SSH_OPTS[@]}" "$SERVER" "sudo mkdir -p '$REMOTE_DIR/data' && sudo chown -R \$(whoami):\$(whoami) '$REMOTE_DIR' && chmod -R u+rwX '$REMOTE_DIR'"

echo "正在上传最新看板到云服务器..."
TASK_STEP="上传日报看板到云服务器"
record_task_run "$TASK_ID" running --message "$TASK_STEP" --step "$TASK_STEP" --log-path "$RUN_LOG"
rsync -az --delete -e "ssh ${SSH_OPTS[*]}" "$PROJECT_DIR/dashboard/" "$SERVER:$REMOTE_DIR/"
rsync -az -e "ssh ${SSH_OPTS[*]}" "$PROJECT_DIR/data/latest.json" "$PROJECT_DIR/data/unified_daily.csv" "$PROJECT_DIR/data/unified_reviews.csv" "$SERVER:$REMOTE_DIR/data/"
ssh "${SSH_OPTS[@]}" "$SERVER" "find '$REMOTE_DIR' -type d -exec chmod 755 {} + && find '$REMOTE_DIR' -type f -exec chmod 644 {} +"

echo ""
echo "云端日报地址：$REMOTE_URL"
date '+%F %T' > "$SCHEDULER_LOG_DIR/daily-success-$(date +%F).marker"
echo "日报采集并发布完成。"
