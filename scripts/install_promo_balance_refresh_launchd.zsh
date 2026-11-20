#!/bin/zsh
set -euo pipefail

# Compatibility entry point: balance collection belongs to morning operations.
# Retire both standalone labels so old installation commands cannot restore them.
for label in \
  com.summer.operation.promo-balance-refresh \
  com.summer.store-inspection.promo-balance
do
  /bin/launchctl disable "gui/$(id -u)/${label}"
  /bin/launchctl bootout "gui/$(id -u)/${label}" 2>/dev/null || true
  plist="$HOME/Library/LaunchAgents/${label}.plist"
  if [[ -f "$plist" ]]; then
    /bin/rm "$plist"
  fi
done

echo "已停用独立推广余额巡检；仅随每天上午运营执行。"
