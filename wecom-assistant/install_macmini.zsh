#!/bin/zsh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
NODE="$HOME/.local/bin/node"
if [[ ! -x "$NODE" ]]; then
  echo '缺少 Node 22，请先安装官方 Node 运行时。' >&2
  exit 1
fi
if [[ ! -f "$ROOT/node_modules/@wecom/aibot-node-sdk/package.json" ]]; then
  echo '请先在此目录安装锁定依赖。' >&2
  exit 1
fi
export WECOM_INSTALL_ROOT="$ROOT"
export WECOM_INSTALL_NODE="$NODE"
"$NODE" "$ROOT/refresh_template.mjs"
/usr/bin/python3 - <<'PY'
import os, plistlib, json
from pathlib import Path
home = Path.home()
root = Path(os.environ['WECOM_INSTALL_ROOT'])
log = home / 'Library/Logs/xiong-wecom-assistant'
log.mkdir(parents=True, exist_ok=True, mode=0o700)
folder = home / 'Library/LaunchAgents'
folder.mkdir(parents=True, exist_ok=True)
payload = {'Label': 'com.summer.wecom-work-assistant',
           'ProgramArguments': [os.environ['WECOM_INSTALL_NODE'], str(root/'app.mjs')],
           'WorkingDirectory': str(root), 'RunAtLoad': True, 'KeepAlive': True,
           'ThrottleInterval': 15,
           'EnvironmentVariables': {'PATH': str(home/'.local/bin')+':/usr/bin:/bin:/usr/sbin:/sbin', 'TZ': 'Asia/Shanghai',
                                    'WECOM_DATA_ROOTS': json.dumps([str(home/'Library/Application Support/xiong-operation/production')]),
                                    'WECOM_INBOUND_RUNTIME_TEMPLATE': str(home/'.local/share/xiong-wecom-assistant/templates/inbound.xlsx')},
           'StandardOutPath': str(log/'stdout.log'), 'StandardErrorPath': str(log/'stderr.log')}
with (folder/'com.summer.wecom-work-assistant.plist').open('wb') as f:
    plistlib.dump(payload, f)
PY
PLIST="$HOME/Library/LaunchAgents/com.summer.wecom-work-assistant.plist"
launchctl bootout "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl enable "gui/$(id -u)/com.summer.wecom-work-assistant"
launchctl kickstart -k "gui/$(id -u)/com.summer.wecom-work-assistant"
echo '企微工作助手已安装；请检查 http://127.0.0.1:18769/health 的 authenticated 状态。'
