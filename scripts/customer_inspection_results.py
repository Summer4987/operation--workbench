#!/usr/bin/env python3
"""Publish reviewed customer screenshots from the Mac mini, never raw device logs."""
from __future__ import annotations
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
HOME = Path.home()
PRIVATE = HOME / '.local/share/xiong-wecom-assistant'
RUNTIME = HOME / 'Documents/customer-inspection'
URL = 'http://139.155.148.169/operation-workbench/customer-inspection/'
CITY = {'银泰城店':'成都','保利中心店':'成都','万象城店':'成都','金融城店':'成都','万松园店':'武汉','光谷店':'武汉','滨江店':'杭州','五一广场店':'长沙'}
PLATFORMS = {'meituan', 'taobao-shangou'}
NAV = '              <a href="#customer-inspection">客户端巡检结果</a>\n'
SECTION = '''        <section class="center-section report-section" id="customer-inspection">
          <div class="section-head"><p>顾客端实采</p><h2>客户端巡检结果</h2></div>
          <iframe class="daily-report-frame" data-report-src="customer-inspection/" sandbox="allow-same-origin allow-scripts allow-popups" title="客户端巡检结果"></iframe>
        </section>

'''

def now():
    return datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S')

def add_entry(html):
    if 'href="#customer-inspection"' not in html:
        anchor='              <a href="#direct-messages">直营门店消息复盘</a>\n'
        if anchor not in html: raise ValueError('Expected navigation anchor absent')
        html=html.replace(anchor,anchor+NAV,1)
    if 'id="customer-inspection"' not in html:
        anchor='        <section class="center-section" id="budget">'
        if anchor not in html: raise ValueError('Expected section anchor absent')
        html=html.replace(anchor,SECTION+anchor,1)
    return html

def write_json(path, data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    temp.replace(path)

def build(source: Path, stage: Path):
    source=source.resolve(); report=json.loads((source/'reviewed-progress.json').read_text())
    (stage/'images').mkdir(parents=True,exist_ok=True)
    date=report['date']
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',date): raise ValueError('Invalid report date')
    datetime.strptime(date,'%Y-%m-%d')
    dest=stage/'data'/f'{date}.json'
    previous=json.loads(dest.read_text()) if dest.exists() else {'records':[]}
    merged={(r['platform'],r['store']):r for r in previous['records']}
    for row in report['records']:
        platform,store=row['platform'],row['store']
        if platform not in PLATFORMS: raise ValueError('Unknown platform')
        item=dict(platform=platform,store=store,city=CITY.get(store,'北京'),status=row['status'],images=[],captured_at=None)
        if row['status']=='visually_accepted':
            files=row.get('files') or []
            if len(files)!=2: raise ValueError(f'{store}: reviewed pair must contain two images')
            expected={f'{platform}/{store}/01-first-screen.png',f'{platform}/{store}/02-steak-category.png'}
            if {f['path'] for f in files}!=expected: raise ValueError('Image paths do not match reviewed store')
            times=[]
            for entry in sorted(files,key=lambda f:f['path']):
                f=(source/entry['path']).resolve()
                if not f.is_relative_to(source): raise ValueError('Image escapes source')
                data=f.read_bytes();digest=hashlib.sha256(data).hexdigest()
                if digest!=entry['sha256'] or not data.startswith(b'\x89PNG\r\n\x1a\n'):raise ValueError('Image integrity mismatch')
                relative=f'images/{date}/{platform}/{digest}.png';target=stage/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
                times.append(datetime.fromtimestamp(f.stat().st_mtime,ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S'))
                item['images'].append(dict(url=relative,label='① 进店首屏 · 红包满减' if f.name.startswith('01') else '② 牛排饭 STEAK · 商品首屏',sha256=digest))
            item['captured_at']=max(times)
        else:
            item['status_label']={'blocked_human_verification':'身份验证阻塞','identity_pending':'门店待核实','recapture_needed':'待补图'}.get(row['status'],'未完成')
            item['reason']=row.get('note') or '尚未取得并复核两张合格原图。'
        merged[(platform,store)]=item
    result=dict(date=date,published_at=now(),records=list(merged.values()),notes=report.get('limitations',[]))
    write_json(dest,result)
    dates=sorted([p.stem for p in (stage/'data').glob('????-??-??.json')],reverse=True)
    write_json(stage/'data/index.json',dict(dates=dates,updated_at=now()))
    return result

def notify(date):
    token=(PRIVATE/'operator-token').read_text().strip()
    req=Request('http://127.0.0.1:18769/operator/inspection',data=json.dumps(dict(date=date)).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},method='POST')
    with urlopen(req,timeout=20) as response: return json.load(response)

def publish(source):
    stage=RUNTIME/'published';stage.mkdir(parents=True,exist_ok=True)
    before=hashlib.sha256((source/'reviewed-progress.json').read_bytes()).hexdigest()
    state_path=stage/'publisher-state.json';state=json.loads(state_path.read_text()) if state_path.exists() else {}
    key=str(source.resolve());previous=state.get(key,{})
    if previous.get('fingerprint')==before and previous.get('notified'):return
    report=build(source,stage); date=report['date']
    ssh=['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10','-i',str(HOME/'.ssh/xiong_operation_cloud_ed25519')]
    server='ubuntu@139.155.148.169';remote='/var/www/html/operation-workbench'
    def run(args,**kwargs):return subprocess.run(args,check=True,timeout=120,**kwargs)
    run(ssh+[server,f'mkdir -p {remote}/customer-inspection/data {remote}/customer-inspection/images'])
    transport=' '.join(ssh)
    run(['rsync','-az','--chmod=D755,F644','--exclude=data','--exclude=images','-e',transport,str(ROOT/'customer-inspection')+'/',f'{server}:{remote}/customer-inspection/'])
    run(['rsync','-az','--chmod=D755,F644','-e',transport,str(stage/'images')+'/',f'{server}:{remote}/customer-inspection/images/'])
    # Upload data only after all originals. Rename each JSON atomically; catalog last.
    for name in [f'{date}.json','index.json']:
        run(['scp','-q','-i',str(HOME/'.ssh/xiong_operation_cloud_ed25519'),str(stage/'data'/name),f'{server}:{remote}/customer-inspection/data/{name}.tmp'])
        run(ssh+[server,f'chmod 644 {remote}/customer-inspection/data/{name}.tmp && mv {remote}/customer-inspection/data/{name}.tmp {remote}/customer-inspection/data/{name}'])
    # Preserve any unrelated live homepage updates when inserting this entry.
    patch='from pathlib import Path\np=Path("'+remote+'/index.html")\nh=p.read_text()\n'+f'nav={NAV!r}\nsection={SECTION!r}\n'+'''a='              <a href="#direct-messages">直营门店消息复盘</a>\\n'
b='        <section class="center-section" id="budget">'
if 'href="#customer-inspection"' not in h:
 assert a in h;h=h.replace(a,a+nav,1)
if 'id="customer-inspection"' not in h:
 assert b in h;h=h.replace(b,section+b,1)
t=p.with_suffix('.inspection.tmp');t.write_text(h);t.chmod(0o644);t.replace(p)
'''
    run(ssh+[server,'python3 -'],input=patch.encode())
    # Verify actual deployed bytes for page, manifest, and every original via loopback.
    checks={f'{remote}/customer-inspection/index.html':hashlib.sha256((ROOT/'customer-inspection/index.html').read_bytes()).hexdigest(),f'{remote}/customer-inspection/data/{date}.json':hashlib.sha256((stage/'data'/f'{date}.json').read_bytes()).hexdigest()}
    for r in report['records']:
        for f in r['images']:checks[f'{remote}/customer-inspection/'+f['url']]=f['sha256']
    for name in ['styles.css','app.js']:
        checks[f'{remote}/customer-inspection/{name}']=hashlib.sha256((ROOT/'customer-inspection'/name).read_bytes()).hexdigest()
    checks[f'{remote}/customer-inspection/data/index.json']=hashlib.sha256((stage/'data/index.json').read_bytes()).hexdigest()
    verify = """import hashlib,json,urllib.request,http.cookiejar
from pathlib import Path
config={}
for line in Path('/etc/inventory-board.env').read_text().splitlines():
 if '=' in line and not line.lstrip().startswith('#'):
  k,v=line.split('=',1);config[k.strip()]=v.strip().strip('\"').strip("'")
base='http://139.155.148.169'
jar=http.cookiejar.CookieJar();opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
login=urllib.request.Request(base+'/api/auth/login',data=json.dumps({'username':config.get('OPERATION_AUTH_USERNAME','summer'),'password':config['INVENTORY_PASSWORD']}).encode(),headers={'Content-Type':'application/json'})
with opener.open(login,timeout=15) as r: assert json.load(r)['status']=='success'
checks=CHECKS
for p,d in checks.items():
 url=base+'/operation-workbench/customer-inspection/'+p.split('/customer-inspection/',1)[1]
 with opener.open(url,timeout=15) as r:
  assert r.status==200 and '/login' not in r.geturl(),p
  assert hashlib.sha256(r.read()).hexdigest()==d,p
with opener.open(base+'/operation-workbench/',timeout=15) as r:assert 'id="customer-inspection"' in r.read().decode()
print(json.dumps({'verified_http_files':len(checks),'authenticated_http':True}))
""".replace('CHECKS',repr(checks))
    run(ssh+[server,'sudo -n python3 -'],input=verify.encode())
    receipt=stage/f'{date}.json'
    write_json(receipt,{**report,'url':URL,'publication_verified':True})
    state[key]=dict(fingerprint=before,published_at=now(),notified=False);write_json(state_path,state)
    result=notify(date)
    state[key]['notified']=bool(result.get('delivered') or result.get('already_delivered'));write_json(state_path,state)
    if not state[key]['notified']:raise RuntimeError('Published; private message not acknowledged')
    print(json.dumps(dict(published=True,notified=True,url=URL),ensure_ascii=False))

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',type=Path);parser.add_argument('--watch',action='store_true');parser.add_argument('--build-only',type=Path);args=parser.parse_args()
    if args.build_only:
        if not args.source:parser.error('--source required')
        print(json.dumps(build(args.source,args.build_only),ensure_ascii=False));return
    if args.watch:
        date=now()[:10]
        for p in sorted(RUNTIME.glob(f'{date}*/reviewed-progress.json')):publish(p.parent)
    elif args.source:publish(args.source)
    else:parser.error('--source or --watch required')

if __name__=='__main__':main()
