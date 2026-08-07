#!/bin/zsh
set -euo pipefail

CLOUD_HOST="${MACMINI_TUNNEL_CLOUD_HOST:-139.155.148.169}"
CLOUD_USER="${MACMINI_TUNNEL_CLOUD_USER:-ubuntu}"
CLOUD_KEY="${MACMINI_TUNNEL_CLOUD_KEY:-$HOME/.ssh/xiong_operation_cloud_ed25519}"
REMOTE_PORT="${MACMINI_TUNNEL_REMOTE_PORT:-22022}"
LABEL="${MACMINI_TUNNEL_LABEL:-com.summer.macmini.reverse-ssh-tunnel}"
SCRIPT_PATH="$HOME/bin/macmini_reverse_ssh_tunnel.zsh"
PLIST_PATH="$HOME/Library/LaunchAgents/${LABEL}.plist"

mkdir -p "$HOME/bin" "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"

if [[ ! -f "$CLOUD_KEY" ]]; then
  echo "缺少云服务器 SSH key：$CLOUD_KEY" >&2
  exit 66
fi

cat > "$SCRIPT_PATH" <<EOF
#!/usr/bin/env zsh
set -euo pipefail
exec /usr/bin/ssh -N \\
  -R 127.0.0.1:${REMOTE_PORT}:localhost:22 \\
  -i "${CLOUD_KEY}" \\
  -o IdentitiesOnly=yes \\
  -o ExitOnForwardFailure=yes \\
  -o ServerAliveInterval=30 \\
  -o ServerAliveCountMax=3 \\
  -o TCPKeepAlive=yes \\
  ${CLOUD_USER}@${CLOUD_HOST}
EOF
chmod 700 "$SCRIPT_PATH"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${SCRIPT_PATH}</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${HOME}/Library/Logs/macmini_reverse_ssh_tunnel.log</string>
  <key>StandardErrorPath</key>
  <string>${HOME}/Library/Logs/macmini_reverse_ssh_tunnel.err.log</string>
  <key>ThrottleInterval</key>
  <integer>20</integer>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)" "$PLIST_PATH" 2>/dev/null || true
pkill -f "127.0.0.1:${REMOTE_PORT}:localhost:22" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
launchctl enable "gui/$(id -u)/${LABEL}"

sleep 2
launchctl print "gui/$(id -u)/${LABEL}" >/dev/null
pgrep -af "127.0.0.1:${REMOTE_PORT}:localhost:22" >/dev/null

echo "Mac mini 反向 SSH 隧道已安装并运行：${CLOUD_USER}@${CLOUD_HOST} 127.0.0.1:${REMOTE_PORT} -> Mac mini localhost:22"
