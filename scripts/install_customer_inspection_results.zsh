#!/bin/zsh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if /usr/bin/python3 -c 'import json,sys;sys.exit(0 if json.load(open(sys.argv[1])).get("enabled",True) else 1)' "$ROOT/config/customer-inspection-rotation.json"; then
  :
else
  /bin/zsh "$ROOT/scripts/disable_customer_inspection.zsh"
  exit 0
fi
export CUSTOMER_RESULTS_ROOT="$ROOT"
/usr/bin/python3 - <<'PY'
import os,plistlib
from pathlib import Path
home=Path.home();root=Path(os.environ['CUSTOMER_RESULTS_ROOT'])
log=home/'Library/Logs/customer-inspection-results';log.mkdir(parents=True,exist_ok=True)
payload={'Label':'com.summer.customer-inspection-results','ProgramArguments':['/usr/bin/python3',str(root/'scripts/customer_inspection_results.py'),'--watch'],'WorkingDirectory':str(root),'StartInterval':300,'RunAtLoad':True,'ProcessType':'Background','EnvironmentVariables':{'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','TZ':'Asia/Shanghai'},'StandardOutPath':str(log/'stdout.log'),'StandardErrorPath':str(log/'stderr.log')}
folder=home/'Library/LaunchAgents';folder.mkdir(parents=True,exist_ok=True)
with (folder/'com.summer.customer-inspection-results.plist').open('wb') as f:plistlib.dump(payload,f)
PY
PLIST="$HOME/Library/LaunchAgents/com.summer.customer-inspection-results.plist"
launchctl bootout "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl enable "gui/$(id -u)/com.summer.customer-inspection-results"
echo '已安装结果发布和私聊通知检查（每5分钟）；这不是手机采集定时任务。'
