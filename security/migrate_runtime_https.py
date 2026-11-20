"""Migrate only this host's URL scheme; retain local credentials and unrelated edits."""
from pathlib import Path
import hashlib
import os
import re
import socket
import subprocess
import time

ROOT=Path(__file__).resolve().parents[1]
FILES=['scripts/send_inventory_warning_daily.py','scripts/agent_inbox_worker.py','scripts/sync_promo_budget_overrides.py','scripts/customer_inspection_results.py','scripts/check_inventory_cloud_health.py','scripts/build_inventory_order_suggestions.py','scripts/kuailv_order_dry_run.py','scripts/build_task_health.py','scripts/build_workbench_data.py','scripts/agent_system_check.py','scripts/morning_result_report.py','scripts/longxia_verification_notify.py','inventory-board/scripts/watch_inventory_folder.py','inventory-board/scripts/sync_order_outputs.py','inventory-board/scripts/deliver_order_outputs_with_hermes.py']

def upgraded(data):
    return re.sub(rb'http://139\.155\.148\.169(?=[/\s\'"?#]|$)',b'https://139.155.148.169',data)

def main():
    if 'mini' not in socket.gethostname().lower():raise RuntimeError('Mac mini only')
    home=Path.home();backups=home/'Library/Application Support/xiong-operation/security-url-backups'/str(time.time_ns())
    planned=[]
    for rel in ['Library/Application Support/xiong-operation/production','Library/Application Support/xiong-operation/node-runtime','Library/Application Support/xiong-operation/roi-release','Documents/operation-workbench-clean']:
        root=home/rel
        for name in FILES:
            target=root/name
            if not target.is_file():continue
            old=target.read_bytes();new=upgraded(old)
            if new==old:continue
            base=subprocess.run(['git','-C',str(root),'show','HEAD:'+name],capture_output=True)
            # A runtime may intentionally contain a newer GitHub-main file than its metadata checkout.
            if (base.returncode or base.stdout!=old) and new!=(ROOT/name).read_bytes():
                raise RuntimeError('Unreviewed local code; refusing to replace '+str(target))
            compile(new,str(target),'exec')
            planned.append((target,old,new))
        for name in ['config/ops_notify.json','config/agent_monitor.json','config/agent_llm.json']:
            p=root/name
            if p.is_file() and upgraded(p.read_bytes())!=p.read_bytes():planned.append((p,p.read_bytes(),upgraded(p.read_bytes())))
    env=home/'.xiong-agent-env'
    if env.is_file() and upgraded(env.read_bytes())!=env.read_bytes():planned.append((env,env.read_bytes(),upgraded(env.read_bytes())))
    for p,old,new in planned:
        if p.read_bytes()!=old:raise RuntimeError('Concurrent change detected: '+str(p))
        backup=backups/p.relative_to(home);backup.parent.mkdir(parents=True,exist_ok=True,mode=0o700);backup.write_bytes(old);backup.chmod(0o600)
        metadata=p.stat();tmp=p.with_name(p.name+'.https-tmp');tmp.write_bytes(new);tmp.chmod(metadata.st_mode & 0o777);os.chown(tmp,metadata.st_uid,metadata.st_gid);tmp.replace(p)
    print('Production HTTPS client migration:',len(planned),'files; local credentials and unrelated content preserved')

if __name__=='__main__':main()
