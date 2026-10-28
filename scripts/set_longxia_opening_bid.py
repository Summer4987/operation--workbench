"""Migrate cloud bid floors to the owner's fixed 0.40 opening policy; budgets are preserved."""
import argparse
import copy
import inspect
import json
import shlex
import socket
import subprocess
from pathlib import Path


def updated_config(data):
    updated = copy.deepcopy(data)
    for template in updated['longxia']['templates']:
        if type(template.get('maxBid')) is not int or template['maxBid'] < 40:
            raise ValueError('模板出价上限低于0.40元，保留原配置')
        template['minBid'] = 40
    return updated


REMOTE = r'''
request=json.load(sys.stdin)
active=subprocess.check_output(['systemctl','show','inventory-board','-p','WorkingDirectory','--value'],text=True).strip()
root=Path(active).resolve()
if root!=Path('/opt/inventory-board') and not (str(root).startswith('/opt/operation-workbench-releases/') and root.name=='inventory-board'):
 raise RuntimeError('未知生产服务路径')
spec=importlib.util.spec_from_file_location('longxia_config',root/'app/longxia_config.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
p=Path('/opt/inventory-board/data/promo_budget_overrides.json')
original=p.read_bytes();data=json.loads(original)
updated=updated_config(data)
updated['longxia']=module.validate(updated['longxia'])
assert updated['longxia']['stores']==data['longxia']['stores'],'门店预算或分配发生变化'
print(json.dumps({'apply':request['apply'],'templates':[(t['name'],t['minBid'],t['maxBid']) for t in updated['longxia']['templates']],'revision':updated['longxia']['revision']},ensure_ascii=False))
if request['apply'] and updated!=data:
 if p.read_bytes()!=original:raise RuntimeError('配置已被其他操作更新，拒绝覆盖')
 defaults_path=root/'app/longxia_defaults.json'
 new_defaults=request['defaults']
 assert {r['profileId']:r['key'] for r in new_defaults['stores']}=={r['profileId']:r['key'] for r in module.DEFAULT['stores']},'默认绑定变动'
 if defaults_path.read_text()!=json.dumps(new_defaults,ensure_ascii=False,indent=2)+'\n':
  defaults_path.with_name(defaults_path.name+'.backup-opening40-'+str(time.time_ns())).write_bytes(defaults_path.read_bytes())
  defaults_tmp=defaults_path.with_name(defaults_path.name+'.opening40.tmp');defaults_tmp.write_text(json.dumps(new_defaults,ensure_ascii=False,indent=2)+'\n');defaults_tmp.replace(defaults_path)
 backup=p.with_name(p.name+'.backup-opening40-'+str(time.time_ns()))
 backup.write_bytes(original)
 tmp=p.with_name(p.name+'.opening40.tmp');tmp.write_text(json.dumps(updated,ensure_ascii=False,indent=2)+'\n');tmp.replace(p)
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='正式应用；默认仅预览')
    args = parser.parse_args()
    if 'mini' not in socket.gethostname().lower():
        raise RuntimeError('只能从 Mac mini 应用生产配置')
    program = 'import copy,json,sys,time,subprocess,importlib.util\nfrom pathlib import Path\n' + inspect.getsource(updated_config) + REMOTE
    command = ['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10','-i',str(Path.home()/'.ssh/xiong_operation_cloud_ed25519'),'ubuntu@139.155.148.169','sudo -n python3 -c '+shlex.quote(program)]
    subprocess.run(command,input=json.dumps({'apply':args.apply,'defaults':json.loads((Path(__file__).resolve().parents[1]/'inventory-board/app/longxia_defaults.json').read_text())}),text=True,check=True,timeout=30)


if __name__ == '__main__':
    main()
