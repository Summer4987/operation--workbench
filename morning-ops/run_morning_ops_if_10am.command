#!/bin/zsh
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"

now_hhmm="$(date +%H%M)"
if [ "$now_hhmm" -lt 800 ] || [ "$now_hhmm" -gt 1030 ]; then
  echo "[$(date '+%F %T')] 跳过：当前不在 08:00-10:30 窗口内。" >> "$LOG_DIR/scheduler.log"
  exit 0
fi

echo "[$(date '+%F %T')] 开始上午运营采集。" >> "$LOG_DIR/scheduler.log"
"$ROOT/上午运营一键采集.command" >> "$LOG_DIR/scheduler.log" 2>&1
echo "[$(date '+%F %T')] 上午运营采集结束。" >> "$LOG_DIR/scheduler.log"
