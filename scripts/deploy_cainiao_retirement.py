#!/usr/bin/env python3
"""Retire phone logistics and publish only the reviewed store-entry HTML."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import socket
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
SSH = ['ssh', '-o', 'BatchMode=yes', '-i', str(Path.home()/'.ssh/xiong_operation_cloud_ed25519'), 'ubuntu@139.155.148.169']
BASE_HTML_SHA = 'c774f2423ed725922b2b153e28e1f5fa393a050e52d9a9828039c07a0f7c49c0'

def main():
    if 'mini' not in socket.gethostname().lower():
        raise RuntimeError('只能由 Mac mini 发布')
    git = lambda *a: subprocess.check_output(['git', '-C', str(ROOT), *a], text=True).strip()
    if git('branch', '--show-current') != 'main' or git('status', '--porcelain') or git('rev-parse', 'HEAD') != git('rev-parse', 'origin/main'):
        raise RuntimeError('需要从 GitHub 拉取的干净 main')
    subprocess.run(['/bin/zsh', str(ROOT/'scripts/uninstall_cainiao_logistics_launchd.zsh')], check=True)
    # Runtime reports and platform configuration are intentionally preserved. Only
    # clean, tracked code files may be refreshed from the pulled GitHub checkout.
    files = ['scripts/agent_task_notifier.py', 'scripts/hermes_schedule_status.py', 'scripts/cainiao_logistics_capture.py', 'scripts/run_cainiao_logistics_capture.zsh', 'scripts/install_cainiao_logistics_launchd.zsh', 'scripts/uninstall_cainiao_logistics_launchd.zsh']
    for rel in ['Library/Application Support/xiong-operation/production', 'Documents/operation-workbench-clean']:
        dest = Path.home()/rel
        if not dest.is_dir():
            continue
        if subprocess.check_output(['git', '-C', str(dest), 'branch', '--show-current'], text=True).strip() != 'main':
            raise RuntimeError('生产代码目录不是 main')
        for name in files:
            target = dest/name
            content = (ROOT/name).read_bytes()
            if target.exists() and target.read_bytes() == content:
                continue
            tracked = subprocess.run(['git', '-C', str(dest), 'show', 'HEAD:'+name], capture_output=True)
            if target.exists() and (tracked.returncode or tracked.stdout != target.read_bytes()):
                raise RuntimeError('目标代码有本地修改，拒绝覆盖: '+str(target))
            if target.exists():
                backup = Path.home()/'Library/Application Support/XiongCainiao/retired-code'/str(int(time.time()))/rel/name
                backup.parent.mkdir(parents=True, exist_ok=True)
                backup.write_bytes(target.read_bytes())
            target.write_bytes(content)
        print('已从 GitHub main 更新退役规则:', dest)
    active = subprocess.check_output(SSH+['systemctl show daily-order -p WorkingDirectory --value'], text=True).strip()
    if active != '/opt/daily-order' and not (active.startswith('/opt/operation-workbench-releases/') and active.endswith('/daily-order')):
        raise RuntimeError('未知正式订货目录')
    html = (ROOT/'daily-order/static/store-ops.html').read_text()
    if 'logisticsPanel' in html or '/api/logistics' in html or html.count('data-target=') != 2:
        raise RuntimeError('门店订货页面验证失败')
    payload = json.dumps({'path':active+'/static/store-ops.html', 'html':html, 'base':BASE_HTML_SHA, 'commit':git('rev-parse', 'HEAD')})
    remote = '''import sys,json,pathlib,hashlib,time
p=json.load(sys.stdin);f=pathlib.Path(p['path']);old=f.read_bytes();new=p['html'].encode()
if old!=new:
 if hashlib.sha256(old).hexdigest()!=p['base']:raise RuntimeError('正式页面与已审阅基线不同，拒绝覆盖')
 f.with_name(f.name+'.before-cainiao-retirement-'+str(int(time.time()))).write_bytes(old)
 tmp=f.with_name(f.name+'.retirement-tmp');tmp.write_bytes(new);tmp.replace(f)
print('正式订货页面已移除物流模块，来源 GitHub main '+p['commit'])
'''
    subprocess.run(SSH+['sudo -n python3 -c '+shlex.quote(remote)], input=payload, text=True, check=True)
    for url in ['http://139.155.148.169/store-ops/', 'http://139.155.148.169/daily-order/', 'http://139.155.148.169/beijing-order/', 'http://139.155.148.169/order-submit?token=xiongxiaoxiao-order']:
        subprocess.run(['curl', '--fail', '--silent', '--show-error', '--output', '/dev/null', url], check=True)
    print('四个正式订货入口 HTTP 验证通过')

if __name__ == '__main__':
    main()
