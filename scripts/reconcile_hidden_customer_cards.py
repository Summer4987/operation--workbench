"""Reclassify already retained PC-hidden system records without deleting messages."""
import json
import platform
from customer_message_data import OUT,atomic_json,reconcile_hidden_cards

def main():
    if 'mini' not in platform.node().lower():raise SystemExit('只允许在 Mac mini 更新生产采集记录')
    count=0
    for path in [*OUT.glob('????-??-??/snapshot.json'),*OUT.glob('????-??-??/captures/*.json')]:
        data=json.loads(path.read_text())
        scopes=data.get('scopes',{}).values() if 'scopes' in data else [data]
        changed=sum(reconcile_hidden_cards(s) for s in scopes)
        if changed:atomic_json(path,data);count+=changed
    latest=OUT/'latest.json'
    if latest.exists():
        data=json.loads(latest.read_text());source=OUT/data['target_date']/'snapshot.json'
        if source.exists():atomic_json(latest,json.loads(source.read_text()))
    print(f'已更新已保留的隐藏系统记录标记：{count} 条；未删除任何消息')
    from render_customer_messages import build
    build()

if __name__=='__main__':main()
