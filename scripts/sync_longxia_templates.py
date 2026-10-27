"""Production-only template transport. Never opens or changes a platform page."""
import json
import os
import socket
import shlex
import sys
import time
from datetime import datetime
import subprocess
from pathlib import Path
import sync_promo_budget_overrides as transport
import longxia_verification_notify as verification_notify


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
    if c.get('schema') not in (1,2) or c.get('budgetMode')!='split' or len(c.get('stores',[]))!=8 or len(c.get('revision',''))!=64:
        raise RuntimeError('云端龙虾统一配置无效，保留本地配置')
    home=Path.home()
    for runtime in ('production','node-runtime'):
        atomic(home/'Library/Application Support/xiong-operation'/runtime/'config/promo_budget_overrides.json',data)
    publish_status()
    print(datetime.now().isoformat(timespec='seconds'), '龙虾云端模板已同步至生产配置；平台预算由午晚任务处理', flush=True)


def publish_status():
    home=Path.home()
    runtime=home/'Library/Application Support/xiong-dianjin-fleet-test'
    files={}
    for local,remote in [('fleet-sync-status.json','longxia_sync_status.json'),('fleet-public-status.json','longxia_fleet_status.json')]:
        source=runtime/local
        if source.is_file() and source.stat().st_size<=524288:
            files[remote]=json.loads(source.read_text())
    if not files:return
    program="""import json,sys,pathlib,os
root=pathlib.Path('/opt/inventory-board/data')
for name,data in json.load(sys.stdin).items():
 if name not in ('longxia_sync_status.json','longxia_fleet_status.json'):raise ValueError('Invalid status file')
 path=root/name;temporary=path.with_name(name+'.'+str(os.getpid())+'.tmp')
 temporary.write_text(json.dumps(data,ensure_ascii=False));temporary.replace(path)
"""
    command=['ssh','-o','BatchMode=yes','-o','ConnectTimeout=8','-i',str(transport.SSH_IDENTITY),'ubuntu@139.155.148.169','sudo -n python3 -c '+shlex.quote(program)]
    subprocess.run(command,input=json.dumps(files),text=True,check=True,timeout=15,capture_output=True)

if __name__=='__main__':
    if '--daemon' not in sys.argv:
        verification_notify.check()
        main()
    else:
        next_templates=0
        # Status upload is read-only and does not touch the merchant browser.
        while True:
            started=time.monotonic()
            # Alert directly from local status before any cloud transport, including during an SSH outage.
            try:
                verification_notify.check()
            except Exception as exc:
                print(datetime.now().isoformat(timespec='seconds'), '验证码提醒检查失败：'+type(exc).__name__, file=sys.stderr, flush=True)
            try:
                if started>=next_templates:
                    next_templates=started+60
                    main()
                else:
                    publish_status()
            except Exception as exc:
                print(datetime.now().isoformat(timespec='seconds'), '同步失败，保留配置：'+type(exc).__name__, file=sys.stderr, flush=True)
            time.sleep(max(1,15-(time.monotonic()-started)))
