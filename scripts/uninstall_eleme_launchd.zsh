#!/bin/zsh
set -euo pipefail

LABELS=(
  com.summer.dianjin.eleme.1030
  com.summer.dianjin.eleme.1040
  com.summer.dianjin.eleme.1050
  com.summer.dianjin.eleme.1100
  com.summer.dianjin.eleme.1130
  com.summer.dianjin.eleme.1730
  com.summer.dianjin.eleme.1630
)

for label in "${LABELS[@]}"; do
  plist="$HOME/Library/LaunchAgents/${label}.plist"
  /bin/launchctl bootout "gui/$(id -u)" "$plist" >/dev/null 2>&1 || true
  rm -f "$plist"
  echo "已卸载：${label}"
done

echo
echo "饿了么点金自动化定时任务已全部卸载。"
