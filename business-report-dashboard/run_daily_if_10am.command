#!/bin/zsh
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
DESKTOP_RUNNER="$PROJECT_DIR/run_daily_publish.command"
LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"

now_hhmm="$(date +%H%M)"
today="$(date +%F)"

if [ "$now_hhmm" -lt 1000 ] || [ "$now_hhmm" -gt 1030 ]; then
  echo "[$(date '+%F %T')] 跳过自动采集：当前不在 10:00-10:30 窗口内。" >> "$LOG_DIR/daily-scheduler.log"
  exit 0
fi

echo "[$(date '+%F %T')] 开始自动采集日报。" >> "$LOG_DIR/daily-scheduler.log"

if "$DESKTOP_RUNNER" >> "$LOG_DIR/daily-$today.log" 2>&1; then
  echo "[$(date '+%F %T')] 自动采集完成。" >> "$LOG_DIR/daily-scheduler.log"
else
  status=$?
  echo "[$(date '+%F %T')] 自动采集失败，退出码：$status。" >> "$LOG_DIR/daily-scheduler.log"
  exit "$status"
fi
