#!/bin/zsh
# Production Mac mini only; preserve all historical screenshots and manifests.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export CUSTOMER_DISABLE_ROOT="$ROOT"
/usr/bin/python3 - <<'PYCODE'
import json,os,subprocess
from pathlib import Path
root=Path(os.environ['CUSTOMER_DISABLE_ROOT']);home=Path.home()
assert not json.loads((root/'config/customer-inspection-rotation.json').read_text()).get('enabled',True), '先在GitHub main配置停用后部署'
assert (home/'Library/Android/sdk/platform-tools/adb').exists(), '仅在生产Mac mini运行'
assert subprocess.check_output(['git','-C',str(root),'branch','--show-current'],text=True).strip()=='main'
assert not subprocess.check_output(['git','-C',str(root),'status','--porcelain'],text=True).strip(), '生产仓库有未提交改动，停止'
archive=home/'Library/Application Support/customer-inspection/disabled-launchagents';archive.mkdir(parents=True,exist_ok=True)
for label in ['com.summer.customer-inspection-daily','com.summer.customer-inspection-results']:
    service=f'gui/{os.getuid()}/{label}'
    subprocess.run(['/bin/launchctl','disable',service],check=True)
    subprocess.run(['/bin/launchctl','bootout',service],capture_output=True)
    f=home/'Library/LaunchAgents'/f'{label}.plist'
    if f.exists(): f.replace(archive/f.name)
    assert subprocess.run(['/bin/launchctl','print',service],capture_output=True).returncode!=0, f'{label}仍在运行'
    print(label+': disabled and unloaded')
print('每日客户端采集、5分钟自动发布与提醒已停用；历史原图保留。')
PYCODE
