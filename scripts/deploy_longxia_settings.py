"""Deploy only the reviewed budget API sections and UI from a clean main checkout."""
import ast
import json
import socket
import shlex
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SSH=['ssh','-o','BatchMode=yes','-i',str(Path.home()/'.ssh/xiong_operation_cloud_ed25519'),'ubuntu@139.155.148.169']

def between(text,start,end):
    if text.count(start)!=1 or text.count(end)!=1:raise RuntimeError('后端代码标记不唯一，拒绝覆盖')
    return text[text.index(start):text.index(end)]

def main():
    if 'mini' not in socket.gethostname().lower():raise RuntimeError('只能由 Mac mini 发布')
    git=lambda *args:subprocess.check_output(['git','-C',str(ROOT),*args],text=True).strip()
    if git('branch','--show-current')!='main' or git('status','--porcelain') or git('rev-parse','HEAD')!=git('rev-parse','origin/main'):raise RuntimeError('需要干净的 GitHub main')
    active=subprocess.check_output(SSH+['systemctl show inventory-board -p WorkingDirectory --value'],text=True).strip()
    if active!='/opt/inventory-board' and not (active.startswith('/opt/operation-workbench-releases/') and active.endswith('/inventory-board')):
        raise RuntimeError('未知服务目录，拒绝覆盖')
    target='/opt/operation-workbench-releases/longxia-'+git('rev-parse','HEAD')+'/inventory-board'
    current=subprocess.check_output(SSH+['cat '+shlex.quote(active+'/app/main.py')],text=True)
    new=(ROOT/'inventory-board/app/main.py').read_text()
    for start,end in [('@app.get("/api/promo-budget-overrides")','@app.post("/api/import")'),('def _read_promo_budget_overrides()', 'def _validate_weekend_preset(')]:
        current=current.replace(between(current,start,end),between(new,start,end))
    if 'from . import longxia_config' not in current:current=current.replace('from fastapi import ', 'from . import longxia_config\nfrom fastapi import ',1)
    ast.parse(current)
    files={target+'/app/main.py':current}
    for name in ('longxia_config.py','longxia_defaults.json'):
        files[target+'/app/'+name]=(ROOT/'inventory-board/app'/name).read_text()
    for name in ('workbench.js','workbench.css'):
        files['/var/www/html/operation-workbench/'+name]=(ROOT/name).read_text()
    payload=json.dumps({'files':files,'active':active,'target':target},ensure_ascii=False)
    # Fixed server-side script; data is passed through stdin, never interpolated into shell.
    remote="""import json,sys,time,pathlib,shutil,re
payload=json.load(sys.stdin);files=payload['files'];target=pathlib.Path(payload['target'])
if not target.exists():shutil.copytree(payload['active'],target,symlinks=True,ignore=shutil.ignore_patterns('__pycache__'))
suffix='.backup-longxia-'+str(int(time.time()))
for name,text in files.items():
 if name.endswith('.py'):compile(text,name,'exec')
for name,text in files.items():
 p=pathlib.Path(name)
 if p.exists():p.with_name(p.name+suffix).write_bytes(p.read_bytes())
 temp=p.with_name(p.name+'.longxia-tmp');temp.write_text(text);temp.replace(p)
sys.path.insert(0,str(target/'app'))
import longxia_config as config
p=pathlib.Path('/opt/inventory-board/data/promo_budget_overrides.json')
data=json.loads(p.read_text());p.with_name(p.name+suffix).write_bytes(p.read_bytes())
data['longxia']=config.validate(data.get('longxia',config.DEFAULT));config.project(data)
tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2));tmp.replace(p)
override=pathlib.Path('/etc/systemd/system/inventory-board.service.d/zz-github-release.conf')
if override.exists():override.with_name(override.name+suffix).write_bytes(override.read_bytes())
previous=override.read_text() if override.exists() else '[Service]\\n'
line='WorkingDirectory='+str(target)
previous=re.sub(r'^WorkingDirectory=.*$',line,previous,flags=re.M) if 'WorkingDirectory=' in previous else previous+line+'\\n'
override.write_text(previous)
print('预算 API、模板与看板已发布到正式服务版本目录；运行数据已保留')
"""
    subprocess.run(SSH+['sudo -n python3 -c '+shlex.quote(remote)],input=payload,text=True,check=True)
    subprocess.run(SSH+['sudo systemctl daemon-reload && sudo systemctl restart inventory-board && systemctl is-active inventory-board'],check=True)
    subprocess.run(['curl','--retry','3','--retry-delay','1','--retry-all-errors','--location','--fail','--silent','--output','/dev/null','http://139.155.148.169/operation-workbench/'],check=True)

if __name__=='__main__':main()
