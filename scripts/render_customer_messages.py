#!/usr/bin/env python3
"""Build the authenticated direct-store conversation archive from local snapshots."""
import html
import json
import shutil
from customer_message_data import ROOT,OUT,WEB,scope_status


def esc(v):return html.escape(str(v),quote=True)


def summary(messages):
    customers=[m['content'] for m in messages if m['role']=='customer' and not m['content'].startswith('我要咨询以下订单')]
    replies=[m['content'] for m in messages if m['reply_type']=='门店回复']
    joined='\n'.join(customers)
    if any(x in joined for x in ['失败','没收到','异物','少了','漏了','变质','不新鲜']):status='需跟进：尚需核实业务处理结果'
    elif replies:status='已有门店回复；实际处理结果以业务凭证或顾客确认为准'
    elif customers:status='未见门店人工回复；请检查 AI 回复及业务处理记录'
    else:status='系统/卡片记录；请结合原文核实是否需要处理'
    return status,customers,replies


def page(data,dates):
    stores=json.loads((ROOT/'config/customer_messages.json').read_text())['stores']
    cards=[];coverage=[];total=0;messages=0;unavailable=0
    for c in stores:
        for platform in ['美团','淘宝闪购']:
            s=data.get('scopes',{}).get(c['store']+'|'+platform)
            if not s:s=dict(store=c['store'],platform=platform,status='failed',sessions=[],error='本次未采集')
            status=s.get('status','failed');label={'ready':'界面范围已核验','partial':'待复查：采集不完整','failed':'采集失败'}.get(status,status)
            coverage.append(f'<div class="coverage {status}"><b>{esc(c["store"])} · {platform}</b><span>{label} · {len(s["sessions"])} 段</span></div>')
            previous_note=f'<p class=warning>本次复采不完整，保留上次同日采集内容：{esc(s["previous_capture_at"])}；不代表本次读取成功。</p>' if s.get('previous_capture_at') else ''
            issue='；'.join([s.get('error',''),*s.get('errors',[])])
            body=[]
            for session in s['sessions']:
                selected=[m for m in session['messages'] if m['on_target_date']]
                total+=1;messages+=len(selected);unavailable+=sum(m.get('unavailable_text',False) for m in selected)
                status_text,customer,replies=summary(selected)
                bubbles=[]
                for m in session['messages']:
                    # Keep original full fetched history separately; display target-day messages plus preceding context in collapsible block.
                    attachments=[]
                    for a in m.get('media',[]):
                        if a.get('status')=='saved':
                            url=esc(a['file']);kind=a.get('kind','image')
                            if kind=='image':attachments.append(f'<a href="{url}" target="_blank" rel="noopener"><img class="attachment" src="{url}" loading="lazy" alt="{esc(a.get("alt") or "消息图片")}"></a>')
                            elif kind=='audio':attachments.append(f'<audio controls src="{url}"></audio><a href="{url}" target="_blank">语音原文件（未转写）</a>')
                            else:attachments.append(f'<video controls src="{url}"></video>')
                        else:attachments.append('<p class="warning">附件未成功保存，需复查</p>')
                    if m.get('required_media') and not any(a.get('status')=='saved' and a.get('kind')==m['required_media'] for a in m.get('media',[])):
                        attachments.append('<p class=warning>语音/视频原文件尚未取得，需复查；截图或时长不等于完整消息内容。</p>')
                    bubble=f'<div class="msg {esc(m["role"])}"><small>{esc(m["reply_type"])} {esc(m.get("sender", ""))} · {esc(m["timestamp"] or "时间未识别")}{" · 时间取自分组/上下文" if m.get("time_inferred") else ""}</small><div>{esc(m["content"]).replace(chr(10),"<br>")}</div>{"".join(attachments)}</div>'
                    if m['on_target_date']:bubbles.append(bubble)
                context=[m for m in session['messages'] if not m['on_target_date']]
                prior=''
                if context:
                    texts='\n\n'.join(f'{m["timestamp"] or "时间未识别"} {m["reply_type"]}\n{m["content"]}' for m in context)
                    prior=f'<details class="context"><summary>跨日上下文 · {len(context)} 条（不计入当日）</summary><pre>{esc(texts)}</pre></details>'
                body.append(f'<article><h3>{esc(session.get("title") or session["label"].split(chr(10))[0])}</h3><p class="status">{esc(status_text)}</p><p><b>顾客：</b>{esc(" / ".join(customer) or "仅有系统/订单等卡片记录")}<br><b>门店：</b>{esc(" / ".join(replies) or "未见人工回复")}</p><details><summary>查看当日完整原文 · {len(selected)} 条</summary><div class="chat">{"".join(bubbles)}</div>{prior}</details><p class="basis">{esc(session.get("history_basis", ""))}</p></article>')
            empty='本次核验范围内未发现目标日期的消息。' if status=='ready' else '当前结果不可视为“当天没有消息”。'
            cards.append(f'<section class="scope" data-store="{esc(c["store"])}" data-platform="{platform}"><div class="scopehead"><h2>{esc(c["store"])} · {platform}</h2><span class="badge {status}">{label}</span></div><p class="basis">检查会话 {s.get("scanned_sessions",0)} 个 · {esc(s.get("list_basis", ""))} · {esc(s.get("collected_at", ""))}</p>{f"<p class=warning>{esc(issue)}</p>" if issue.strip("；") else ""}{"".join(body) or f"<p>{empty}</p>"}</section>')
    restore_warning=f'<p class=warning>总部范围恢复异常：{esc(data["context_error"])}</p>' if data.get('context_error') else ''
    good=sum(v.get('status')=='ready' for v in data.get('scopes',{}).values())
    options=''.join(f'<option>{esc(c["store"])}</option>' for c in stores)
    links=' '.join(f'<a href="{d}.html">{d}</a>' for d in dates)
    return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>直营门店客服消息</title><style>
*{box-sizing:border-box}body{margin:0;background:#f4f6fa;color:#1e293b;font:15px/1.7 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}main{max-width:1180px;margin:32px auto;padding:0 20px}h1{font-size:30px;margin-bottom:4px}h2{font-size:21px}h3{font-size:17px;margin:0}.subtitle,.basis{color:#64748b}.basis{font-size:12px}.toolbar{display:flex;gap:12px;flex-wrap:wrap;margin:20px 0;align-items:center}select{padding:10px 14px;border:1px solid #cbd5e1;border-radius:8px;background:white;font:inherit}.coveragegrid{display:grid;grid-template-columns:repeat(5,1fr);gap:8px}.coverage{padding:12px;background:white;border:1px solid #e2e8f0;border-radius:10px;font-size:12px}.coverage b,.coverage span{display:block}.coverage span{color:#64748b}.partial,.failed{border-color:#f7cb94;background:#fffbeb}.banner{background:#fff7e5;border-radius:10px;padding:14px 18px;color:#78551b;margin:18px 0}.scope{margin:26px 0}.scopehead{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.badge{font-size:12px;padding:4px 10px;border-radius:16px;background:#e6f4eb}.badge.partial,.badge.failed{background:#ffedd5}.scopehead h2{margin:0}article{padding:22px;margin-top:16px;background:white;border:1px solid #e2e8f0;border-radius:14px}.status{color:#91610f;font-size:13px}.warning{color:#a34b12;background:#fff7e5;padding:10px;border-radius:8px}summary{cursor:pointer;color:#2563eb;padding:10px 0}.chat{background:#f8fafc;border-radius:10px;padding:16px;display:flex;flex-direction:column;gap:10px}.msg{padding:12px 16px;background:white;border:1px solid #e2e8f0;border-radius:10px;max-width:86%;overflow-wrap:anywhere}.msg.merchant{align-self:flex-end;background:#edf7f2}.msg.system{align-self:center;background:#f1f5f9;font-size:13px}small{display:block;color:#64748b;font-size:12px;margin-bottom:6px}.attachment{max-height:260px;max-width:100%;border-radius:6px}video,audio{max-width:100%}.context{margin:10px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.7 inherit;color:#64748b}a{color:#2563eb}.archive a{margin-right:10px}footer{font-size:12px;color:#64748b;margin:30px 0}.hidden{display:none}@media(max-width:800px){.coveragegrid{grid-template-columns:repeat(2,1fr)}main{padding:0 12px}article{padding:16px}.msg{max-width:96%}} </style><main>''' + f'''<h1>直营门店客服消息</h1><p class="subtitle">消息日期：{esc(data['target_date'])} · 最近采集：{esc(data['generated_at'])}<br>门店、AI、自动回复、系统及三方群聊记录分别保留；处理是否成功以实际业务记录为准。</p><div class="banner">5 家门店 × 2 个平台，界面范围核验通过 {good}/10；当日 {total} 段会话、{messages} 条消息（含系统及卡片）。<br>“核验通过”表示当前平台可见范围检查通过；平台已删除、撤回正文或不可访问的历史无法恢复。电脑版未展示正文的系统提示卡 {unavailable} 条，已保留时间和类型标记。未解析或附件失败会标为待复查。淘宝历史起点按滚动复核，美团按平台末尾提示核对。</div>{restore_warning}<div class="coveragegrid">{''.join(coverage)}</div><div class="toolbar"><label>门店 <select id="store"><option value="">全部门店</option>{options}</select></label><label>平台 <select id="platform"><option value="">全部平台</option><option>美团</option><option>淘宝闪购</option></select></label><button id="expand">展开当前原文</button><button id="collapse">收起原文</button></div><p class="archive">历史日期：{links}</p>{''.join(cards)}<footer>原始数据及附件由 Mac mini 每日留档，不上传 GitHub；展示范围为目标日，跨日上下文单独折叠。打开平台会话可能更新已读状态；采集不发送回复、不处理退款或开票。<br>本页面支持按门店、平台筛选。规则提示仅辅助复核。</footer><script>
function filter(){{const s=document.querySelector('#store').value,p=document.querySelector('#platform').value;document.querySelectorAll('.scope').forEach(x=>x.classList.toggle('hidden',(s&&x.dataset.store!==s)||(p&&x.dataset.platform!==p)));}}
document.querySelector('#store').addEventListener('change',filter);document.querySelector('#platform').addEventListener('change',filter);document.querySelector('#expand').onclick=()=>document.querySelectorAll('.scope:not(.hidden) article>details').forEach(x=>x.open=true);document.querySelector('#collapse').onclick=()=>document.querySelectorAll('details').forEach(x=>x.open=false);
</script></main></html>'''


def build():
    WEB.mkdir(parents=True,exist_ok=True)
    snapshots=sorted(OUT.glob('????-??-??/snapshot.json'),reverse=True)
    if not snapshots:
        return
    dates=[p.parent.name for p in snapshots]
    for source in snapshots:
        data=json.loads(source.read_text())
        attachments=source.parent/'attachments'
        if attachments.exists():shutil.copytree(attachments,WEB/'attachments',dirs_exist_ok=True)
        (WEB/f'{data["target_date"]}.html').write_text(page(data,dates),encoding='utf-8')
    latest=json.loads((OUT/'latest.json').read_text())
    (WEB/'index.html').write_text(page(latest,dates),encoding='utf-8')
    print(f'客服消息网页：{WEB}/index.html')

if __name__=='__main__':build()
