#!/bin/zsh
set -euo pipefail
LABEL="com.summer.operation.cainiao-logistics"
DOMAIN="gui/$(id -u)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
launchctl disable "$DOMAIN/$LABEL"
launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
if [[ -f "$PLIST" ]]; then
  ARCHIVE="$HOME/Library/Application Support/XiongCainiao/retired-schedules"
  mkdir -p "$ARCHIVE"
  mv "$PLIST" "$ARCHIVE/$LABEL.$(date +%Y%m%d%H%M%S).plist"
fi
if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
  echo "菜鸟任务仍然加载，停用失败。" >&2
  exit 1
fi
echo "菜鸟定时任务已禁用、卸载，原配置已归档。"
