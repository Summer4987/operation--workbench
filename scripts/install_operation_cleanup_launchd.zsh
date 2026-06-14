#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/com.summer.operation.cleanup-data.plist"
LOG_DIR="$HOME/Library/Logs/xiong-operation/launchd"
mkdir -p "$LOG_DIR" "$(dirname "$PLIST")"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.summer.operation.cleanup-data</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>-lc</string>
    <string>/bin/zsh '$ROOT/scripts/cleanup_operation_data.zsh'</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>3</integer>
    <key>Minute</key>
    <integer>20</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/com.summer.operation.cleanup-data.out.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/com.summer.operation.cleanup-data.err.log</string>
  <key>WorkingDirectory</key>
  <string>$HOME/Library/Scripts/xiong-operation</string>
</dict>
</plist>
PLIST

launchctl unload "$PLIST" >/dev/null 2>&1 || true
launchctl load "$PLIST"

echo "本地旧运营数据定时清理已安装：每天 03:20 自动执行"
echo "$PLIST"
