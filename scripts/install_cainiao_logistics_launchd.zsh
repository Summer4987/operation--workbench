#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

LABEL="com.summer.operation.cainiao-logistics"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$ROOT/outputs/cainiao_logistics_launchd"
RUNNER="$ROOT/scripts/run_cainiao_logistics_capture.zsh"
ADB="${ANDROID_ADB_BIN:-$HOME/Library/Android/sdk/platform-tools/adb}"
INLINE_COMMAND="cd \"$ROOT\"; export ANDROID_ADB_BIN=\"$ADB\"; /bin/zsh \"$RUNNER\""

mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR" "$ROOT/outputs/cainiao_logistics"
chmod +x "$RUNNER"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>-lc</string>
    <string>$INLINE_COMMAND</string>
  </array>
  <key>StartCalendarInterval</key>
  <array>
    <dict>
      <key>Hour</key>
      <integer>10</integer>
      <key>Minute</key>
      <integer>0</integer>
    </dict>
    <dict>
      <key>Hour</key>
      <integer>14</integer>
      <key>Minute</key>
      <integer>0</integer>
    </dict>
    <dict>
      <key>Hour</key>
      <integer>17</integer>
      <key>Minute</key>
      <integer>0</integer>
    </dict>
  </array>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/stdout.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/stderr.log</string>
  <key>WorkingDirectory</key>
  <string>$ROOT</string>
</dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl enable "gui/$(id -u)/$LABEL"

echo "已安装：$LABEL"
echo "时间：每天 10:00、14:00、17:00"
echo "日志：$LOG_DIR/stdout.log / $LOG_DIR/stderr.log"
echo "运行目录：$ROOT"
