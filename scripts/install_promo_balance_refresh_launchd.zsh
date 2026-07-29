#!/bin/zsh
set -euo pipefail

SOURCE_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ROOT="${OPERATION_RUNTIME_ROOT:-$HOME/Library/Application Support/xiong-operation/production}"
LABEL="com.summer.operation.promo-balance-refresh"
SCRIPT_DIR="$HOME/Library/Scripts/xiong-operation"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
LOG_DIR="$HOME/Library/Logs/xiong-operation/launchd"
mkdir -p "$SCRIPT_DIR" "${PLIST:h}" "$LOG_DIR"

sed "s|^ROOT=.*|ROOT=\\\"${ROOT}\\\"|" \
  "$SOURCE_ROOT/scripts/run_promo_balance_refresh.zsh" > "$SCRIPT_DIR/run_promo_balance_refresh.zsh"
chmod +x "$SCRIPT_DIR/run_promo_balance_refresh.zsh"

{
  cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>${SCRIPT_DIR}/run_promo_balance_refresh.zsh</string>
  </array>
  <key>StartCalendarInterval</key>
  <array>
EOF
  for hour in {9..20}; do
    printf '    <dict><key>Hour</key><integer>%s</integer><key>Minute</key><integer>15</integer></dict>\n' "$hour"
  done
  cat <<EOF
  </array>
  <key>StandardOutPath</key>
  <string>${LOG_DIR}/${LABEL}.out.log</string>
  <key>StandardErrorPath</key>
  <string>${LOG_DIR}/${LABEL}.err.log</string>
</dict>
</plist>
EOF
} > "$PLIST"

plutil -lint "$PLIST"
uid="$(id -u)"
launchctl bootout "gui/${uid}/${LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/${uid}" "$PLIST"
launchctl enable "gui/${uid}/${LABEL}"
echo "已安装推广余额刷新任务：每天 9:15-20:15 每小时运行。"

