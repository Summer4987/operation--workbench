#!/bin/zsh
set -euo pipefail

UID_VALUE="$(id -u)"
DOMAIN="gui/${UID_VALUE}"
NETWORK_SERVICE="${ELEME_PROXY_NETWORK_SERVICE:-Ethernet}"

/usr/sbin/networksetup -setautoproxystate "$NETWORK_SERVICE" off
for label in com.summer.operation.eleme-proxy-tunnel com.summer.operation.eleme-proxy-pac; do
  /bin/launchctl bootout "$DOMAIN/$label" >/dev/null 2>&1 || true
  rm -f "$HOME/Library/LaunchAgents/${label}.plist"
done

echo "饿了么专用代理已关闭。"
