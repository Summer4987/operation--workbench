#!/bin/zsh
set -euo pipefail

CLEAN_ROOT="${OPERATION_CLEAN_ROOT:-/Users/summer/Documents/operation-workbench-clean}"
PRODUCTION_ROOT="${OPERATION_CENTER_ROOT:-$CLEAN_ROOT}"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$HOME/Library/Logs/xiong-operation/ai-center-guardian"
SCRIPT_DIR="$HOME/Library/Scripts/xiong-operation"
LABEL="com.summer.operation.ai-center-guardian"
RUNNER="$SCRIPT_DIR/run_ai_center_guardian.zsh"
PLIST="$LAUNCH_DIR/${LABEL}.plist"

mkdir -p "$LAUNCH_DIR" "$LOG_DIR" "$SCRIPT_DIR"

cat > "$RUNNER" <<EOF
#!/bin/zsh
set -euo pipefail

CLEAN_ROOT="${CLEAN_ROOT}"
PRODUCTION_ROOT="${PRODUCTION_ROOT}"
LOG_DIR="${LOG_DIR}"
mkdir -p "\$LOG_DIR"

PYTHON="\${CLEAN_ROOT}/business-report-dashboard/.venv/bin/python"
if [ ! -x "\$PYTHON" ]; then
  PYTHON="/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
fi
if [ ! -x "\$PYTHON" ]; then
  PYTHON="python3"
fi

LOG_FILE="\$LOG_DIR/\$(date +%F).log"
{
  echo
  echo "[\$(date '+%F %T')] AI 业务中心守护报告开始"
  cd "\$CLEAN_ROOT"
  OPERATION_CENTER_ROOT="\$PRODUCTION_ROOT" "\$PYTHON" ai-business-center/guardian.py
  echo "[\$(date '+%F %T')] AI 业务中心守护报告完成"
} >> "\$LOG_FILE" 2>&1
EOF
chmod +x "$RUNNER"

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
    <string>${RUNNER}</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${CLEAN_ROOT}</string>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>10</integer>
    <key>Minute</key>
    <integer>25</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>${LOG_DIR}/${LABEL}.out.log</string>
  <key>StandardErrorPath</key>
  <string>${LOG_DIR}/${LABEL}.err.log</string>
</dict>
</plist>
EOF

/bin/launchctl bootout "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 || true
/bin/launchctl bootstrap "gui/$(id -u)" "$PLIST"
/bin/launchctl enable "gui/$(id -u)/${LABEL}" >/dev/null 2>&1 || true

echo "AI 业务中心守护器已安装。"
echo "时间：每天 10:25"
echo "标签：${LABEL}"
echo "clean 仓库：${CLEAN_ROOT}"
echo "生产目录：${PRODUCTION_ROOT}"
echo "日志目录：${LOG_DIR}"
