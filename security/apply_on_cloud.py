#!/usr/bin/env python3
"""Apply reviewed security fixes; invoked by the Mac mini from GitHub main."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import stat
import subprocess
import sys
import time
from nginx_hardening import configurations

ROOT=Path(__file__).resolve().parents[1]
OLD_ORDER_SHA='179c0cb8813a0dbd980c55049eccc1f1cf4f6ba5d156f0d5af9463a32330e2b6'
HTTP=Path('/etc/nginx/conf.d/inventory-board.conf')
TLS=Path('/etc/nginx/conf.d/qiwei-avatar-tls.conf')
ROUTES=Path('/etc/nginx/snippets/xiong-workbench-https.conf')

def run(*args):
    return subprocess.check_output(args,text=True,stderr=subprocess.PIPE).strip()

def atomic(path,content,mode=None):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    meta=path.stat() if path.exists() else None
    tmp=path.with_name(path.name+'.security-tmp')
    tmp.write_text(content);os.chmod(tmp,mode or (stat.S_IMODE(meta.st_mode) if meta else 0o644))
    if meta:os.chown(tmp,meta.st_uid,meta.st_gid)
    tmp.replace(path)

def env_secret(path,key):
    text=path.read_text() if path.exists() else ''
    text=re.sub(r'^'+re.escape(key)+r'=.*\n?', '', text, flags=re.M)
    atomic(path,text.rstrip()+'\n'+key+'='+secrets.token_urlsafe(48)+'\n',0o600)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--commit',required=True);args=parser.parse_args()
    if os.geteuid()!=0:raise RuntimeError('root required')
    git=lambda *a:run('git','-c','safe.directory='+str(ROOT),'-C',str(ROOT),*a)
    if git('branch','--show-current')!='main' or git('status','--porcelain') or git('rev-parse','HEAD')!=args.commit or git('rev-parse','origin/main')!=args.commit:
        raise RuntimeError('clean verified GitHub main required')
    run('openssl','x509','-in','/etc/qiwei-letsencrypt/live/qiwei-ip/fullchain.pem','-noout','-checkend','86400')
    if 'does match certificate' not in run('openssl','x509','-in','/etc/qiwei-letsencrypt/live/qiwei-ip/fullchain.pem','-noout','-checkip','139.155.148.169'):
        raise RuntimeError('Certificate IP mismatch')
    active=Path(run('systemctl','show','daily-order','-p','WorkingDirectory','--value'))
    if not (str(active).startswith('/opt/operation-workbench-releases/') and active.name=='daily-order'):
        raise RuntimeError('Unknown daily-order release')
    order=active/'app/main.py';new=(ROOT/'daily-order/app/main.py').read_text()
    if hashlib.sha256(order.read_bytes()).hexdigest() not in {OLD_ORDER_SHA,hashlib.sha256(new.encode()).hexdigest()}:
        raise RuntimeError('Production order code changed; refusing overwrite')
    # A second run must never rotate sessions again or derive HTTPS routes from the redirect server.
    marker=Path('/var/lib/xiong-security/applied.json')
    if marker.exists():raise RuntimeError('Already hardened; inspect existing deployment before applying again')
    http,tls,routes=configurations(HTTP.read_text(),TLS.read_text())
    compile(new,str(order),'exec')
    backup=Path('/var/backups/xiong-security')/time.strftime('%Y%m%d-%H%M%S');backup.mkdir(parents=True,mode=0o700)
    bind=Path('/etc/systemd/system/waimai-cloud.service.d/zz-loopback-only.conf')
    service=Path('/etc/systemd/system/xiong-private-ports.service')
    paths=[HTTP,TLS,ROUTES,order,bind,service,Path('/etc/inventory-board.env'),Path('/etc/store-order-auth.env')]
    originals={p:p.read_bytes() if p.exists() else None for p in paths}
    for i,(p,data) in enumerate(originals.items()):
        if data is not None:
            target=backup/(str(i)+'-'+p.name);target.write_bytes(data);target.chmod(0o600)
    atomic(backup/'manifest.json',json.dumps({str(i):str(p) for i,p in enumerate(paths)},indent=2),0o600)
    try:
        atomic(ROUTES,routes);atomic(TLS,tls);atomic(HTTP,http)
        run('/usr/sbin/nginx','-t')
        atomic(order,new)
        atomic(bind,'[Service]\nExecStart=\nExecStart=/opt/waimai-cloud-server/.venv/bin/gunicorn -w 2 -b 127.0.0.1:8088 app:app\n')
        # Rotate only session-signing material. Account passwords and business configuration stay intact.
        env_secret(Path('/etc/inventory-board.env'),'OPERATION_AUTH_SECRET')
        env_secret(Path('/etc/store-order-auth.env'),'STORE_ORDER_AUTH_SECRET')
        with sqlite3.connect('/var/lib/xiong-access/accounts.sqlite3') as con:con.execute('DELETE FROM sessions')
        atomic(service,'[Unit]\nDescription=Restrict legacy private service ports\nAfter=network.target\nBefore=nginx.service\n[Service]\nType=oneshot\nRemainAfterExit=yes\nExecStart=/bin/sh '+str(ROOT/'security/private_ports.sh')+'\n[Install]\nWantedBy=multi-user.target\n')
        run('systemctl','daemon-reload')
        run('systemctl','restart','inventory-board','daily-order','xiong-access','waimai-cloud')
        run('systemctl','enable','--now','xiong-private-ports')
        run('systemctl','reload','nginx')
        for name in ['inventory-board','daily-order','xiong-access','waimai-cloud','xiong-private-ports']:
            if run('systemctl','is-active',name)!='active':raise RuntimeError(name+' unhealthy')
        run('curl','--retry','5','--retry-delay','1','--retry-all-errors','--fail','--silent','--show-error','https://139.155.148.169/login')
        # Smoke uses existing owner authentication, test-owned accounts, scoped reads and denied paths only.
        run('/opt/inventory-board/.venv/bin/python',str(ROOT/'access-control/smoke_live.py'))
        marker.parent.mkdir(parents=True,exist_ok=True)
        atomic(marker,json.dumps({'commit':args.commit,'backup':str(backup),'appliedAt':int(time.time())}),0o600)
    except Exception:
        for p,data in originals.items():
            # Legacy port containment is independent and remains effective on a TLS rollback.
            if p in (bind,service):continue
            if data is None:p.unlink(missing_ok=True)
            else:p.write_bytes(data)
        run('systemctl','daemon-reload')
        for name in ['inventory-board','daily-order','xiong-access','waimai-cloud']:
            subprocess.run(['systemctl','restart',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        run('/usr/sbin/nginx','-t');run('systemctl','reload','nginx')
        raise
    print(json.dumps({'security':'applied','commit':args.commit,'https':'verified','beijingScope':'verified','legacyPort':'loopback-only','oldSessions':'revoked','backup':str(backup)}))

if __name__=='__main__':main()
