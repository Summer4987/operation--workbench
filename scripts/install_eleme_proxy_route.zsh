#!/bin/zsh
set -euo pipefail

ROOT="${OPERATION_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
UID_VALUE="$(id -u)"
DOMAIN="gui/${UID_VALUE}"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
LOG_DIR="$HOME/Library/Logs/xiong-operation/eleme-proxy"
SSH_KEY="$HOME/.ssh/xiong_operation_cloud_ed25519"
PAC_PORT="${ELEME_PROXY_PAC_PORT:-18889}"
SOCKS_PORT="${ELEME_PROXY_SOCKS_PORT:-18888}"
NETWORK_SERVICE="${ELEME_PROXY_NETWORK_SERVICE:-Ethernet}"
PAC_URL="http://127.0.0.1:${PAC_PORT}/eleme-proxy.pac"

mkdir -p "$LAUNCH_AGENTS" "$LOG_DIR"

if [[ ! -f "$SSH_KEY" ]]; then
  echo "缺少云端 SSH 密钥：$SSH_KEY"
  exit 1
fi

TUNNEL_LABEL="com.summer.operation.eleme-proxy-tunnel"
PAC_LABEL="com.summer.operation.eleme-proxy-pac"
TUNNEL_PLIST="$LAUNCH_AGENTS/${TUNNEL_LABEL}.plist"
PAC_PLIST="$LAUNCH_AGENTS/${PAC_LABEL}.plist"

/usr/bin/python3 - "$TUNNEL_PLIST" "$TUNNEL_LABEL" "$SSH_KEY" "$SOCKS_PORT" "$LOG_DIR" <<'PY'
import plistlib
import sys

target, label, key, port, log_dir = sys.argv[1:]
payload = {
    "Label": label,
    "ProgramArguments": [
        "/usr/bin/ssh", "-N", "-D", f"127.0.0.1:{port}",
        "-i", key, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
        "-o", "ExitOnForwardFailure=yes", "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=3", "ubuntu@139.155.148.169",
    ],
    "RunAtLoad": True,
    "KeepAlive": True,
    "ThrottleInterval": 10,
    "StandardOutPath": f"{log_dir}/tunnel.out.log",
    "StandardErrorPath": f"{log_dir}/tunnel.err.log",
}
with open(target, "wb") as handle:
    plistlib.dump(payload, handle, sort_keys=False)
PY

/usr/bin/python3 - "$PAC_PLIST" "$PAC_LABEL" "$ROOT/config" "$PAC_PORT" "$LOG_DIR" <<'PY'
import plistlib
import sys

target, label, directory, port, log_dir = sys.argv[1:]
payload = {
    "Label": label,
    "ProgramArguments": [
        "/usr/bin/python3", "-m", "http.server", port,
        "--bind", "127.0.0.1", "--directory", directory,
    ],
    "RunAtLoad": True,
    "KeepAlive": True,
    "ThrottleInterval": 10,
    "StandardOutPath": f"{log_dir}/pac.out.log",
    "StandardErrorPath": f"{log_dir}/pac.err.log",
}
with open(target, "wb") as handle:
    plistlib.dump(payload, handle, sort_keys=False)
PY

for label in "$TUNNEL_LABEL" "$PAC_LABEL"; do
  /bin/launchctl bootout "$DOMAIN/$label" >/dev/null 2>&1 || true
done
/bin/launchctl bootstrap "$DOMAIN" "$TUNNEL_PLIST"
/bin/launchctl bootstrap "$DOMAIN" "$PAC_PLIST"
/bin/launchctl kickstart -k "$DOMAIN/$TUNNEL_LABEL"
/bin/launchctl kickstart -k "$DOMAIN/$PAC_LABEL"

for _ in {1..20}; do
  if /usr/bin/curl -fsS --max-time 2 "$PAC_URL" >/dev/null 2>&1 && \
     /usr/sbin/lsof -nP -iTCP:"$SOCKS_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

/usr/bin/curl -fsS --max-time 5 "$PAC_URL" >/dev/null
/usr/sbin/lsof -nP -iTCP:"$SOCKS_PORT" -sTCP:LISTEN >/dev/null
/usr/sbin/networksetup -setautoproxyurl "$NETWORK_SERVICE" "$PAC_URL"
/usr/sbin/networksetup -setautoproxystate "$NETWORK_SERVICE" on

echo "饿了么专用代理已启用：$PAC_URL"
echo "仅 *.ele.me 和 *.elemecdn.com 走 SOCKS5 127.0.0.1:$SOCKS_PORT"
