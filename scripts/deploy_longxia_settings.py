"""Deploy only the reviewed budget API sections and UI from a clean main checkout."""
import ast
import copy
import inspect
import json
import socket
import shlex
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SSH=['ssh','-o','BatchMode=yes','-i',str(Path.home()/'.ssh/xiong_operation_cloud_ed25519'),'ubuntu@139.155.148.169']

def between(text,start,end):
    if text.count(start)!=1 or text.count(end)!=1:raise RuntimeError('后端代码标记不唯一，拒绝覆盖')
    return text[text.index(start):text.index(end)]

def register_missing_stores(data, defaults):
    """Register reviewed bindings and fill only missing Meituan template choices."""
    updated = copy.deepcopy(data)
    registered = {row['profileId'] for row in updated['longxia']['stores']}
    selections = {row['sourceStore']: row['platforms']['美团']
                  for row in updated.get('budgetSettings', {}).get('entries', [])}
    for original in defaults['stores']:
        if original['profileId'] in registered:
            continue
        row = copy.deepcopy(original)
        if updated['longxia'].get('schema') == 2:
            days = selections[row['sourceStore']]
            for value in days.values():
                if not value.get('templateId'):
                    value['templateId'] = row['templateId']
            row['dayTypes'] = {day: {'dailyBudget': value['dailyBudget'],
                                    'templateId': value['templateId']}
                              for day, value in days.items()}
        updated['longxia']['stores'].append(row)
        registered.add(row['profileId'])
    return updated

def deploy_status_only(active):
    """Update the status validator without writing budgets, templates, or UI."""
    source=(ROOT/'inventory-board/app/longxia_status.py').read_text()
    remote="""import json,sys,pathlib,shutil,time,os,stat
payload=json.load(sys.stdin);active=pathlib.Path(payload['active'])
path=active/'app/longxia_status.py';source=payload['source']
compile(source,str(path),'exec')
metadata=path.stat();backup=path.with_name(path.name+'.backup-status-'+str(time.time_ns()))
shutil.copy2(path,backup)
tmp=path.with_name(path.name+'.status-'+str(os.getpid())+'.tmp')
try:
 tmp.write_text(source);os.chown(tmp,metadata.st_uid,metadata.st_gid);os.chmod(tmp,stat.S_IMODE(metadata.st_mode));tmp.replace(path)
 sys.path.insert(0,str(active))
 from app import longxia_status
 result=longxia_status.read('/opt/inventory-board/data/longxia_fleet_status.json')
 if not result.get('available') or not result.get('online'):raise RuntimeError('最新生产状态未通过校验，恢复原模块')
 print(json.dumps({'available':result['available'],'online':result['online'],'version':result.get('version'),'generatedAt':result['generatedAt'],'stores':len(result['stores'])}))
except Exception:
 shutil.copy2(backup,path);raise
finally:tmp.unlink(missing_ok=True)
"""
    subprocess.run(SSH+['sudo -n python3 -c '+shlex.quote(remote)],input=json.dumps({'active':active,'source':source}),text=True,check=True)
    subprocess.run(SSH+['sudo systemctl restart inventory-board && systemctl is-active inventory-board'],check=True,stdin=subprocess.DEVNULL)
    subprocess.run(['curl','--retry','3','--retry-delay','1','--retry-all-errors','--location','--fail','--silent','--output','/dev/null','http://139.155.148.169/operation-workbench/'],check=True)

def main():
    if 'mini' not in socket.gethostname().lower():raise RuntimeError('只能由 Mac mini 发布')
    git=lambda *args:subprocess.check_output(['git','-C',str(ROOT),*args],text=True).strip()
    if git('branch','--show-current')!='main' or git('status','--porcelain') or git('rev-parse','HEAD')!=git('rev-parse','origin/main'):raise RuntimeError('需要干净的 GitHub main')
    active=subprocess.check_output(SSH+['systemctl show inventory-board -p WorkingDirectory --value'],text=True,stdin=subprocess.DEVNULL).strip()
    if active!='/opt/inventory-board' and not (active.startswith('/opt/operation-workbench-releases/') and active.endswith('/inventory-board')):
        raise RuntimeError('未知服务目录，拒绝覆盖')
    if '--status-only' in sys.argv:
        deploy_status_only(active)
        return
    target='/opt/operation-workbench-releases/longxia-'+git('rev-parse','HEAD')+'/inventory-board'
    current=subprocess.check_output(SSH+['cat '+shlex.quote(active+'/app/main.py')],text=True,stdin=subprocess.DEVNULL)
    new=(ROOT/'inventory-board/app/main.py').read_text()
    for start,end in [('@app.get("/api/promo-budget-overrides")','@app.post("/api/import")'),('def _read_promo_budget_overrides()', 'def _validate_weekend_preset(')]:
        current=current.replace(between(current,start,end),between(new,start,end))
    if 'from . import budget_settings' not in current:current=current.replace('from fastapi import ', 'from . import budget_settings\nfrom fastapi import ',1)
    if 'from . import longxia_status' not in current:current=current.replace('from fastapi import ', 'from . import longxia_status\nfrom fastapi import ',1)
    if 'from . import longxia_config' not in current:current=current.replace('from fastapi import ', 'from . import longxia_config\nfrom fastapi import ',1)
    ast.parse(current)
    files={target+'/app/main.py':current}
    for name in ('longxia_config.py','longxia_defaults.json','longxia_status.py','budget_settings.py','budget_totals_baseline.json'):
        files[target+'/app/'+name]=(ROOT/'inventory-board/app'/name).read_text()
    index=subprocess.check_output(SSH+['cat /var/www/html/operation-workbench/index.html'],text=True,stdin=subprocess.DEVNULL)
    for first,last in [('budget','bidding'),('bidding','balances')]:
        start=f'<section class="center-section" id="{first}">'
        end=f'<section class="center-section" id="{last}">'
        index=index.replace(between(index,start,end),between((ROOT/'index.html').read_text(),start,end))
    files['/var/www/html/operation-workbench/index.html']=index
    for name in ('workbench.js','workbench.css'):
        files['/var/www/html/operation-workbench/'+name]=(ROOT/name).read_text()
    payload=json.dumps({'files':files,'active':active,'target':target},ensure_ascii=False)
    # Fixed server-side script; data is passed through stdin, never interpolated into shell.
    remote="""import json,sys,time,pathlib,shutil,re,os,stat
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
import budget_settings as settings
p=pathlib.Path('/opt/inventory-board/data/promo_budget_overrides.json')
original=p.read_bytes();metadata=p.stat();data=json.loads(original)
backup=p.with_name(p.name+suffix);backup.write_bytes(original);backup.chmod(0o600)
# Registration comes only from reviewed GitHub bindings, with existing totals preserved.
data=register_missing_stores(data,config.DEFAULT)
data['longxia']=config.validate(data.get('longxia',config.DEFAULT))
data['budgetSettings']=settings.validate(data.get('budgetSettings'),data['longxia']);settings.project(data)
if p.read_bytes()!=original:raise RuntimeError('预算配置已变化，拒绝覆盖')
tmp=p.with_name(p.name+'.register-'+str(os.getpid())+'.tmp')
try:
 tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2))
 os.chown(tmp,metadata.st_uid,metadata.st_gid);os.chmod(tmp,stat.S_IMODE(metadata.st_mode))
 tmp.replace(p)
finally:tmp.unlink(missing_ok=True)
override=pathlib.Path('/etc/systemd/system/inventory-board.service.d/zz-github-release.conf')
if override.exists():override.with_name(override.name+suffix).write_bytes(override.read_bytes())
previous=override.read_text() if override.exists() else '[Service]\\n'
line='WorkingDirectory='+str(target)
previous=re.sub(r'^WorkingDirectory=.*$',line,previous,flags=re.M) if 'WorkingDirectory=' in previous else previous+line+'\\n'
override.write_text(previous)
print('预算 API、模板与看板已发布到正式服务版本目录；运行数据已保留')
"""
    remote = 'import copy\n' + inspect.getsource(register_missing_stores) + remote
    subprocess.run(SSH+['sudo -n python3 -c '+shlex.quote(remote)],input=payload,text=True,check=True)
    subprocess.run(SSH+['sudo systemctl daemon-reload && sudo systemctl restart inventory-board && systemctl is-active inventory-board'],check=True,stdin=subprocess.DEVNULL)
    subprocess.run(['curl','--retry','3','--retry-delay','1','--retry-all-errors','--location','--fail','--silent','--output','/dev/null','http://139.155.148.169/operation-workbench/'],check=True)

if __name__=='__main__':main()
