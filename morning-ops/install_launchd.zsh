#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.summer.morning-ops"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
LOG_DIR="$ROOT/logs"

mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"
chmod +x "$ROOT/上午运营一键采集.command" "$ROOT/run_morning_ops_if_10am.command"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>${ROOT}/run_morning_ops_if_10am.command</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${ROOT}</string>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>10</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>${LOG_DIR}/${LABEL}.out.log</string>
  <key>StandardErrorPath</key>
  <string>${LOG_DIR}/${LABEL}.err.log</string>
</dict>
</plist>
EOF

/bin/launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.xiong.daily-report.plist" >/dev/null 2>&1 || true
/bin/launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.summer.store-inspection.promo-balance.plist" >/dev/null 2>&1 || true
/bin/launchctl bootout "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 || true
/bin/launchctl bootstrap "gui/$(id -u)" "$PLIST"
/bin/launchctl enable "gui/$(id -u)/${LABEL}" >/dev/null 2>&1 || true

echo "已安装上午运营采集：每天 10:00"
echo "已停用旧的独立日报启动项和旧的独立余额巡检启动项。"
echo "日志目录：$LOG_DIR"
