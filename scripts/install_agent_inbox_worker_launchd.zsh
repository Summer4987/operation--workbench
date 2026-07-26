#!/bin/zsh
set -euo pipefail

ROOT="${OPERATION_CENTER_ROOT:-/Users/summer/Library/Application Support/xiong-operation/production}"
LABEL="com.summer.operation.agent-inbox-worker"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
SCRIPT_DIR="$HOME/Library/Scripts/xiong-operation"
LOG_DIR="$HOME/Library/Logs/xiong-operation/agent-inbox-worker"
RUNNER="$SCRIPT_DIR/run_agent_inbox_worker.zsh"
PLIST="$LAUNCH_DIR/${LABEL}.plist"
PYTHON="${PYTHON:-/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3}"

mkdir -p "$LAUNCH_DIR" "$SCRIPT_DIR" "$LOG_DIR"

if [[ ! -x "$PYTHON" ]]; then
  PYTHON="/usr/bin/python3"
fi

cat > "$RUNNER" <<EOF
#!/bin/zsh
set -euo pipefail

ROOT="${ROOT}"
PYTHON="${PYTHON}"
LOG_DIR="${LOG_DIR}"
ENV_FILE="\$HOME/.xiong-agent-env"
mkdir -p "\$LOG_DIR"
cd "\$ROOT"

if [[ -f "\$ENV_FILE" ]]; then
  set -a
  source "\$ENV_FILE"
  set +a
fi

OPERATION_CENTER_ROOT="\$ROOT" "\$PYTHON" scripts/agent_inbox_worker.py >> "\$LOG_DIR/\$(date +%F).log" 2>&1
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
  <string>${ROOT}</string>
  <key>StartInterval</key>
  <integer>60</integer>
  <key>RunAtLoad</key>
  <true/>
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
/bin/launchctl kickstart -k "gui/$(id -u)/${LABEL}" >/dev/null 2>&1 || true

echo "Agent 企微收件箱 worker 已安装。"
echo "标签：${LABEL}"
echo "频率：每 60 秒"
echo "根目录：${ROOT}"
echo "日志目录：${LOG_DIR}"
