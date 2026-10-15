"""Customer conversation data contract and date/completeness checks (no credentials)."""
from __future__ import annotations
import hashlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
TZ=ZoneInfo('Asia/Shanghai')
OUT=ROOT/'outputs/customer_messages'
WEB=ROOT/'business-report-dashboard/direct-dashboard/customer-messages'


def stamp(raw, today=None):
    today=today or datetime.now(TZ).date()
    raw=str(raw or '').strip()
    explicit_year=bool(re.match(r'^\d{4}[-年]',raw))
    if not raw:return ''
    prefix=today
    if raw.startswith('昨天'):prefix=today-timedelta(days=1)
    elif raw.startswith('前天'):prefix=today-timedelta(days=2)
    if raw.startswith(('昨天','今天','前天')):
        raw=f'{prefix} '+raw[2:].strip()
    raw=re.sub(r'(\d{4})年(\d{1,2})月(\d{1,2})日',lambda m:f'{m[1]}-{int(m[2]):02}-{int(m[3]):02}',raw)
    raw=re.sub(r'(?<!\d)(\d{1,2})月(\d{1,2})日',lambda m:f'{today.year}-{int(m[1]):02}-{int(m[2]):02}',raw)
    if re.match(r'^\d{1,2}[-/]\d{1,2}(?:\s|$)',raw):
        raw=f'{today.year}-'+raw.replace('/','-')
        # A December message shown during January belongs to the preceding year.
        month=int(raw[5:].split('-')[0])
        if month>today.month+1:raw=str(today.year-1)+raw[4:]
    elif re.fullmatch(r'\d{1,2}:\d{2}(?::\d{2})?',raw):raw=f'{today} {raw}'
    raw=raw.strip()
    for fmt in ['%Y-%m-%d %H:%M:%S','%Y-%m-%d %H:%M','%Y-%m-%d']:
        try:
            dt=datetime.strptime(raw,fmt)
            if not explicit_year and dt.year==today.year and dt.month>today.month+1:dt=dt.replace(year=dt.year-1)
            return dt.strftime('%Y-%m-%d %H:%M:%S') if 'H' in fmt else dt.date().isoformat()
        except ValueError:pass
    return ''


def normalize(rows,target,today=None,newest_first=False):
    rows=list(reversed(rows)) if newest_first else rows
    result=[];seen=set();carry=''
    for raw in rows:
        row=dict(raw)
        if row.get('separator'):
            carry=stamp(row['separator'],today) or carry
            continue
        ident=str(row.get('id') or '')
        if not ident or ident in seen:continue
        seen.add(ident)
        explicit=stamp(row.get('time'),today)
        if explicit:carry=explicit
        row['timestamp']=explicit or carry
        row['time_inferred']=row.get('time_inferred',False) or not bool(explicit)
        row['on_target_date']=row['timestamp'].startswith(target)
        row['media']=row.get('media') or []
        if not row.get('content') and not row['media'] and str(row.get('type')) in {'17019','9','17024','1000'}:
            row.update(content=f'[平台系统记录：电脑版未展示正文（类型{row.get("type")}）]',role='system',unavailable_text=True)
        row['content']=row.get('content') or ('[附件消息]' if row['media'] else '[未解析消息，保留原始类型]')
        role=row.get('role','system')
        sender=row.get('sender','')
        row['reply_type']=('AI回复' if row.get('is_ai') or '[AI客服]' in sender else '自动回复' if row.get('is_auto') or '[自动回复]' in sender else '门店回复') if role=='merchant' else ('顾客' if role=='customer' else '系统/群聊参与者')
        row['needs_review']=not row['timestamp'] or row['content'].startswith('[未解析')
        result.append(row)
    # System events before the first explicit timestamp use the next group's time.
    next_time=''
    for row in reversed(result):
        if row['timestamp']:next_time=row['timestamp']
        elif next_time:
            row.update(timestamp=next_time,time_inferred=True,on_target_date=next_time.startswith(target))
            row['needs_review']=row['content'].startswith('[未解析')
    return sorted(result,key=lambda m:m['timestamp'] or '9999')


def merge_messages(batches):
    """Union every rendered batch, preserving distinct messages even with equal text/time."""
    result={}
    for rows in batches:
        for row in rows:
            if row.get('id'):result[row['id']]=row
    return list(result.values())


def scope_status(scope):
    if scope.get('error'):return 'failed'
    if not scope.get('list_complete') or scope.get('errors'):return 'partial'
    for s in scope.get('sessions',[]):
        if not s.get('history_complete') or any(m.get('needs_review') or any(a.get('status')!='saved' for a in m.get('media',[])) for m in s['messages'] if m.get('on_target_date') or not m.get('timestamp')):
            return 'partial'
    return 'ready'


def atomic_json(path,payload):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');tmp.replace(path)


def safe_error(exc):
    # Browser errors can contain signed URLs, cookies or request bodies.
    return str(exc)[:250] if type(exc) is RuntimeError else f'{type(exc).__name__}：平台页面读取异常，请在 Mac mini 检查登录态和页面结构'


def media_name(url):return hashlib.sha256(url.encode()).hexdigest()[:32]


def project_scope(raw,target):
    """Materialize one calendar day from overlapping captures, preserving cross-day context."""
    import copy
    scope=copy.deepcopy(raw);scope['date']=target
    retained=[]
    for session in scope.get('sessions',[]):
        for m in session['messages']:
            m['on_target_date']=m.get('timestamp','').startswith(target)
        if any(m['on_target_date'] or not m.get('timestamp') for m in session['messages']):retained.append(session)
    scope['sessions']=retained;scope['status']=scope_status(scope)
    return scope


def reconcile_hidden_cards(scope):
    count=0
    for session in scope.get('sessions',[]):
        for m in session['messages']:
            if str(m.get('type')) not in {'17019','9','17024','1000'}:continue
            if m.get('content')!='[未解析消息，保留原始类型]' or m.get('media'):continue
            m.update(content=f'[平台系统记录：电脑版未展示正文（类型{m.get("type")}）]',role='system',reply_type='系统/群聊参与者',unavailable_text=True,needs_review=False)
            m.pop('capture_error',None);count+=1
    scope['status']=scope_status(scope)
    return count
