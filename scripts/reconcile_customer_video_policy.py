"""Apply the reference-only video policy to existing Mac mini captures."""
import json
import platform
from customer_message_data import OUT,atomic_json,scope_status


def main():
    if 'mini' not in platform.node().lower():raise SystemExit('只允许在 Mac mini 更新生产采集记录')
    count=0
    for path in [*OUT.glob('????-??-??/snapshot.json'),*OUT.glob('????-??-??/captures/*.json'),OUT/'latest.json']:
        if not path.exists():continue
        data=json.loads(path.read_text())
        before=json.dumps(data,sort_keys=True)
        for scope in data.get('scopes',{}).values() if 'scopes' in data else [data]:
            scope['status']=scope_status(scope)
        if json.dumps(data,sort_keys=True)!=before:
            atomic_json(path,data);count+=1
    print(f'已按视频仅标记规则更新 {count} 份记录；原始运行日志及已有附件保留。')
    from render_customer_messages import build
    build()


if __name__=='__main__':main()
