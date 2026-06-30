#!/bin/zsh
set -euo pipefail

SOURCE_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUNTIME_ROOT="$HOME/dianjin-automation-runtime"
ROOT="$RUNTIME_ROOT"
RUNNER="$ROOT/scripts/run_eleme_automation.zsh"
MODE="${1:-rehearse}"
LIMIT="${2:-all}"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$ROOT/outputs/dianjin_automation/launchd_logs"
mkdir -p "$LAUNCH_DIR" "$LOG_DIR"

if [[ "$MODE" != "rehearse" && "$MODE" != "preview" && "$MODE" != "commit" ]]; then
  echo "模式只能是 rehearse、preview 或 commit。当前：$MODE"
  exit 1
fi

write_plist() {
  local label="$1"
  local hour="$2"
  local minute="$3"
  local time_point="$4"
  local plist="$LAUNCH_DIR/${label}.plist"

  cat > "$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>${RUNNER}</string>
    <string>--time</string>
    <string>${time_point}</string>
    <string>--mode</string>
    <string>${MODE}</string>
    <string>--limit</string>
    <string>${LIMIT}</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${ROOT}</string>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>${hour}</integer>
    <key>Minute</key>
    <integer>${minute}</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>${LOG_DIR}/${label}.out.log</string>
  <key>StandardErrorPath</key>
  <string>${LOG_DIR}/${label}.err.log</string>
</dict>
</plist>
EOF

  /bin/launchctl bootout "gui/$(id -u)" "$plist" >/dev/null 2>&1 || true
  /bin/launchctl bootstrap "gui/$(id -u)" "$plist"
  /bin/launchctl enable "gui/$(id -u)/${label}" >/dev/null 2>&1 || true
  echo "已安装：${label} -> ${time_point}（${hour}:${minute}，${MODE}）"
}

write_custom_plist() {
  local label="$1"
  local hour="$2"
  local minute="$3"
  local runner="$4"
  local plist="$LAUNCH_DIR/${label}.plist"

  cat > "$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>${runner}</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${ROOT}</string>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>${hour}</integer>
    <key>Minute</key>
    <integer>${minute}</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>${LOG_DIR}/${label}.out.log</string>
  <key>StandardErrorPath</key>
  <string>${LOG_DIR}/${label}.err.log</string>
</dict>
</plist>
EOF

  /bin/launchctl bootout "gui/$(id -u)" "$plist" >/dev/null 2>&1 || true
  /bin/launchctl bootstrap "gui/$(id -u)" "$plist"
  /bin/launchctl enable "gui/$(id -u)/${label}" >/dev/null 2>&1 || true
  echo "已安装：${label} -> ${hour}:${minute}"
}

rm -rf "$RUNTIME_ROOT"
mkdir -p "$RUNTIME_ROOT"
cp -R "$SOURCE_ROOT/scripts" "$RUNTIME_ROOT/scripts"
cp -R "$SOURCE_ROOT/dianjin-prototype" "$RUNTIME_ROOT/dianjin-prototype"
mkdir -p "$RUNTIME_ROOT/store-inspection" "$RUNTIME_ROOT/config"
cp "$SOURCE_ROOT/store-inspection/meituan_budget_automation.py" "$RUNTIME_ROOT/store-inspection/meituan_budget_automation.py"
cp "$SOURCE_ROOT/store-inspection/one_click_meituan_balance.py" "$RUNTIME_ROOT/store-inspection/one_click_meituan_balance.py"
cp "$SOURCE_ROOT/store-inspection/parse_balance_ocr.py" "$RUNTIME_ROOT/store-inspection/parse_balance_ocr.py"
cp "$SOURCE_ROOT/store-inspection/screen_tool.swift" "$RUNTIME_ROOT/store-inspection/screen_tool.swift"
cp "$SOURCE_ROOT/store-inspection/ocr_image.swift" "$RUNTIME_ROOT/store-inspection/ocr_image.swift"
cp "$SOURCE_ROOT/config/promo_budget_overrides.json" "$RUNTIME_ROOT/config/promo_budget_overrides.json"
mkdir -p "$RUNTIME_ROOT/business-report-dashboard"
cp "$SOURCE_ROOT/business-report-dashboard/chrome_cdp_reports.py" "$RUNTIME_ROOT/business-report-dashboard/chrome_cdp_reports.py"
cp "$SOURCE_ROOT/business-report-dashboard/chrome_cdp_config.json" "$RUNTIME_ROOT/business-report-dashboard/chrome_cdp_config.json"
mkdir -p "$RUNTIME_ROOT/outputs"
if [[ -d "$SOURCE_ROOT/outputs/dianjin_automation" ]]; then
  mkdir -p "$RUNTIME_ROOT/outputs/dianjin_automation"
  cp -R "$SOURCE_ROOT/outputs/dianjin_automation/." "$RUNTIME_ROOT/outputs/dianjin_automation/" 2>/dev/null || true
fi
chmod +x "$RUNNER"
chmod +x "$RUNTIME_ROOT/scripts/run_evening_budget.zsh"
chmod +x "$RUNTIME_ROOT/scripts/run_current_budget.zsh"

write_plist "com.summer.dianjin.eleme.1040" 10 40 "10:40"
write_plist "com.summer.dianjin.eleme.1050" 10 50 "10:50"
write_plist "com.summer.dianjin.eleme.1100" 11 0 "11:00"
write_custom_plist "com.summer.dianjin.eleme.1630" 16 30 "$SOURCE_ROOT/scripts/run_evening_budget.zsh"

echo
echo "饿了么点金自动化定时任务已安装。当前模式：${MODE}"
echo "日志目录：${LOG_DIR}"
