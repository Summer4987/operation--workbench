"""Production-only template transport. Never opens or changes a platform page."""
import json
import os
import socket
import subprocess
from pathlib import Path
import sync_promo_budget_overrides as transport


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary=path.with_name(path.name+f'.{os.getpid()}.tmp')
    temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    temporary.replace(path)


def main():
    if 'mini' not in socket.gethostname().lower():
        raise RuntimeError('模板同步仅允许在 Mac mini 生产主机执行')
    data=transport.read_remote_ssh()
    c=data.get('longxia',{})
    if c.get('schema')!=1 or c.get('budgetMode')!='split' or len(c.get('stores',[]))!=8 or len(c.get('revision',''))!=64:
        raise RuntimeError('云端龙虾统一配置无效，保留本地配置')
    home=Path.home()
    for runtime in ('production','node-runtime'):
        atomic(home/'Library/Application Support/xiong-operation'/runtime/'config/promo_budget_overrides.json',data)
    ack=home/'Library/Application Support/xiong-dianjin-fleet-test/fleet-sync-status.json'
    if ack.exists():
        status=json.loads(ack.read_text())
        command=['ssh','-n','-o','BatchMode=yes','-o','ConnectTimeout=8','-i',str(transport.SSH_IDENTITY),'ubuntu@139.155.148.169',
                 "cat > /opt/inventory-board/data/longxia_sync_status.json.tmp && mv /opt/inventory-board/data/longxia_sync_status.json.tmp /opt/inventory-board/data/longxia_sync_status.json"]
        command.remove('-n')
        subprocess.run(command,input=json.dumps(status),text=True,check=True,timeout=15,capture_output=True)
    print('龙虾云端模板已同步至生产配置；平台预算由午晚任务处理')

if __name__=='__main__':
    main()
