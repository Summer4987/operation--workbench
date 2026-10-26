#!/bin/zsh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export CUSTOMER_DAILY_ROOT="$ROOT"
/usr/bin/python3 - <<'PY'
import json,os,plistlib,subprocess
from pathlib import Path
home=Path.home();root=Path(os.environ['CUSTOMER_DAILY_ROOT'])
assert (home/'Library/Android/sdk/platform-tools/adb').exists(), '只能在连接生产安卓机的Mac mini安装'
assert subprocess.check_output(['git','-C',str(root),'branch','--show-current'],text=True).strip()=='main'
assert not subprocess.check_output(['git','-C',str(root),'status','--porcelain'],text=True).strip(), '生产代码存在未提交改动，停止安装'
config=json.loads((root/'config/customer-inspection-rotation.json').read_text())
hour,minute=map(int,config['time'].split(':'))
assert subprocess.check_output(['/bin/date','+%z'],text=True).strip()=='+0800', 'launchd按系统时区运行，要求北京时间'
log=home/'Library/Logs/customer-inspection-daily';log.mkdir(parents=True,exist_ok=True)
payload={'Label':'com.summer.customer-inspection-daily','ProgramArguments':['/usr/bin/caffeinate','-i','/usr/bin/python3',str(root/'scripts/customer_inspection_daily.py')],'WorkingDirectory':str(root),'StartCalendarInterval':{'Hour':hour,'Minute':minute},'RunAtLoad':False,'ProcessType':'Background','EnvironmentVariables':{'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','TZ':config['timezone']},'StandardOutPath':str(log/'stdout.log'),'StandardErrorPath':str(log/'stderr.log')}
folder=home/'Library/LaunchAgents';folder.mkdir(parents=True,exist_ok=True)
with (folder/'com.summer.customer-inspection-daily.plist').open('wb') as f:plistlib.dump(payload,f)
PY
PLIST="$HOME/Library/LaunchAgents/com.summer.customer-inspection-daily.plist"
launchctl bootout "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl enable "gui/$(id -u)/com.summer.customer-inspection-daily"
echo '已安装每天北京时间10:30采集4店，4天循环；安装不会立即重复采集。'
