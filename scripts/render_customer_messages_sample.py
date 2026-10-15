"""Render a local production capture into an escaped, self-contained sample page."""
import argparse
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def esc(value):
    return html.escape(str(value), quote=True)


def triage(session):
    customers = '\n'.join(m['content'] for m in session['messages'] if m['on_target_date'] and m['role']=='customer')
    replies = [m for m in session['messages'] if m['on_target_date'] and m['role']=='merchant' and m['reply_type']=='门店回复']
    if '开票失败' in customers:
        return '发票问题', '需跟进', '顾客反馈开票失败；可见门店回复不构成开票成功凭证。'
    if any(x in customers for x in ['不放','不要','少放','多放','单放']):
        return '用餐要求', '已回复，履约待核实' if replies else '待核实回复', '可查看门店是否确认要求；聊天无法证明实际制作结果。'
    if any(x in customers for x in ['牛肉','现烤','现做']):
        return '商品咨询', '已回复，结果待确认' if replies else '待核实回复', '保留顾客原话和门店答复，未据此推断顾客满意。'
    return '顾客咨询', '已回复，结果待确认' if replies else '待核实回复', '处理结果以明确的业务记录或顾客确认为准。'


def render(data):
    cards=[]
    count=0
    for session in data['sessions']:
        topic,status,note=triage(session)
        messages=[]
        for m in session['messages']:
            if not m.get('content'):
                continue
            target=m['on_target_date']
            count+=bool(target and m['role']!='system')
            body=esc(m['content']).replace('\n','<br>')
            # Preserve media references as a labelled attachment; never mistake a product image for customer evidence.
            if m.get('media') and not m['content']:
                body='[图片消息：原图待核验]'
            messages.append(f'<div class="msg {esc(m["role"])} {"" if target else "context"}"><div class="meta">{esc(m["reply_type"])} · {esc(m["timestamp"] or "时间未单独标注")} {"· 跨日上下文" if not target and m["role"]!="system" else ""}</div><div>{body}</div><small>{esc(m.get("read_status", ""))}</small></div>')
        customer_text = ' / '.join(m['content'] for m in session['messages'] if m['on_target_date'] and m['role']=='customer' and not m['content'].startswith('我要咨询以下订单'))
        merchant_text = ' / '.join(m['content'] for m in session['messages'] if m['on_target_date'] and m['reply_type']=='门店回复')
        brief = f'<p><b>顾客：</b>{esc(customer_text)}<br><b>门店：</b>{esc(merchant_text or "未见门店人工回复")}</p>'
        title=session['label'].split('\n')[0]
        target_count=sum(m['on_target_date'] and m['role']!='system' for m in session['messages'])
        cards.append(f'<article><div class="cardhead"><h2>{esc(title)}</h2><span class="tag">{esc(topic)}</span><span class="status">{esc(status)}</span></div><p class="note">{esc(note)}</p>{brief}<details open><summary>对话原文 · 当日 {target_count} 条 · {"已到历史末尾" if session["history_complete"] else "历史加载未确认完整"}</summary><div class="chat">{"".join(messages)}</div></details></article>')
    complete=data['session_list_complete'] and not data['errors'] and all(s['history_complete'] for s in data['sessions'])
    return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>朝阳门店 · 客服对话试览</title><style>
*{box-sizing:border-box}body{margin:0;background:#f3f6fa;color:#1e293b;font:15px/1.65 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}main{max-width:1080px;margin:40px auto;padding:0 22px}a{color:#2563eb}h1{font-size:30px;margin:16px 0 5px}h2{font-size:19px;margin:0}.eyebrow{color:#64748b;font-size:13px}.intro{color:#64748b;max-width:900px}.metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin:24px 0}.metric,article{background:white;border:1px solid #e2e8f0;border-radius:16px;padding:22px}.metric strong{display:block;font-size:30px}.metric span{color:#64748b}.banner{padding:15px 18px;background:#fff7e5;border-radius:12px;color:#78551b;margin-bottom:22px}.cardhead{display:flex;align-items:center;flex-wrap:wrap;gap:10px}.tag,.status{font-size:12px;background:#eff6ff;color:#2563eb;padding:3px 10px;border-radius:20px}.status{background:#fff7e5;color:#a16207}.note{color:#64748b}article{margin-bottom:20px}summary{cursor:pointer;color:#475569;padding:12px 0;border-top:1px solid #f1f5f9}.chat{display:flex;flex-direction:column;gap:12px;padding:18px;background:#f8fafc;border-radius:10px}.msg{max-width:82%;padding:12px 16px;border-radius:12px;background:white;border:1px solid #e2e8f0;overflow-wrap:anywhere}.merchant{align-self:flex-end;background:#edf7f2;border-color:#cde7d9}.customer{align-self:flex-start}.system{align-self:center;background:transparent;border:0;font-size:12px;color:#94a3b8}.meta{font-size:12px;color:#64748b;margin-bottom:6px}.context{opacity:.65}small{font-size:11px;color:#94a3b8}footer{font-size:12px;color:#94a3b8;padding:20px 0}@media(max-width:600px){main{margin:20px auto;padding:0 12px}.metrics{gap:8px}.metric{padding:12px}.metric strong{font-size:24px}.msg{max-width:95%}article{padding:15px}h1{font-size:25px}}</style><main><a href="../../#direct-daily">← 返回直营门店看板</a><p class="eyebrow">直营门店 · 客服消息处理 · 单店试览</p>''' + f'''<h1>{esc(data['store'])} · 昨日在线对话</h1><p class="intro">{esc(data['date'])} · {esc(data['platform'])} · 原文按时间从早到晚展示；AI、自动回复与门店回复分别标记。</p><div class="metrics"><div class="metric"><strong>{len(data['sessions'])}</strong><span>当日有消息的顾客会话</span></div><div class="metric"><strong>{count}</strong><span>当日消息及订单卡片</span></div><div class="metric"><strong>{sum(triage(s)[1]=='需跟进' for s in data['sessions'])}</strong><span>规则提示需跟进</span></div></div><div class="banner">试采范围：仅朝阳门店美团。淘宝闪购尚未采集，不代表没有消息。<br>已检查 {data['scanned_sessions']} 个可见顾客会话；{"可见会话列表及入选对话已加载至末尾" if complete else "存在未确认完整的记录"}。业务处理是否成功仍需相应凭证。</div>{''.join(cards)}<footer>来源：{esc(data['source'])} · 采集时间：{esc(data['collected_at'])}<br>此页为单店试览，尚未加入每日自动任务；不含群发营销日志。原始记录保存在 Mac mini，不进入 GitHub。<br>采集错误：{esc(json.dumps(data['errors'],ensure_ascii=False))}</footer></main></html>'''


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('source',type=Path)
    args=ap.parse_args()
    data=json.loads(args.source.read_text(encoding='utf-8'))
    output=ROOT/'business-report-dashboard/direct-dashboard/customer-messages-sample.html'
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(render(data),encoding='utf-8')
    print(output)

if __name__=='__main__': main()
