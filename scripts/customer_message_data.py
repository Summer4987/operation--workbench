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
        if str(row.get('type')) in {'17019','9','17024','1000'}:row['role']='system'
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


VIDEO_NOTICE='[视频消息：暂不保存视频文件，如需查看请到门店平台后台查看]'


def apply_reference_media_policy(message):
    """Audio and video are references only; retain message identity and saved covers."""
    kind = message.get('required_media')
    if kind not in {'audio', 'video'}:
        kind = next((k for k in ['audio', 'video'] if message.get(k+'_not_archived')), None)
    if kind is None:
        kind = next((a.get('kind') for a in message.get('media',[]) if a.get('kind') in {'audio','video'}), None)
    if kind not in {'audio','video'}:
        return False
    message[kind+'_not_archived']=True
    message['required_media']=kind
    message['media']=[a for a in message.get('media',[]) if a.get('kind') not in {'audio','video'} and a.get('status')=='saved']
    if not message.get('content') or message['content'].startswith(('[未解析','[附件')):
        label='语音' if kind=='audio' else '视频'
        message['content']=f'[{label}消息：暂不保存文件，如需查看请到门店平台后台查看]'
    message['needs_review']=not bool(message.get('timestamp'))
    message.pop('capture_error',None)
    return True


def apply_video_policy(message):
    """Compatibility entry point for existing video reconciliation callers."""
    if message.get('required_media')=='video' or message.get('video_not_archived') or any(a.get('kind')=='video' for a in message.get('media',[])):
        return apply_reference_media_policy(message)
    return False


def scope_status(scope):
    if scope.get('error'):return 'failed'
    if not scope.get('list_complete') or scope.get('errors'):return 'partial'
    for s in scope.get('sessions',[]):
        for m in s['messages']:apply_reference_media_policy(m)
        if not s.get('history_complete') or any(m.get('needs_review') or (m.get('required_media') and m['required_media'] not in {'audio','video'} and not any(a.get('status')=='saved' and a.get('kind')==m['required_media'] for a in m.get('media',[]))) or any(a.get('status')!='saved' for a in m.get('media',[])) for m in s['messages'] if m.get('on_target_date') or not m.get('timestamp')):
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
    changed=set()
    for session in scope.get('sessions',[]):
        for m in session['messages']:
            if str(m.get('type'))=='10089' and m.get('required_media')=='audio':
                m.pop('required_media',None);changed.add(m['id'])
            if str(m.get('type')) not in {'17019','9','17024','1000'}:continue
            if m.get('role')!='system':
                m.update(role='system',reply_type='系统/群聊参与者');changed.add(m['id'])
            if m.get('content')!='[未解析消息，保留原始类型]' or m.get('media'):continue
            m.update(content=f'[平台系统记录：电脑版未展示正文（类型{m.get("type")}）]',role='system',reply_type='系统/群聊参与者',unavailable_text=True,needs_review=False)
            m.pop('capture_error',None);changed.add(m['id'])
    scope['status']=scope_status(scope)
    return len(changed)


def media_type(declared,content):
    """Platform CDNs sometimes label valid images as application/octet-stream."""
    if content.startswith(b'\x89PNG\r\n\x1a\n'):return 'image/png'
    if content.startswith(b'\xff\xd8\xff'):return 'image/jpeg'
    if content.startswith((b'GIF87a',b'GIF89a')):return 'image/gif'
    if content.startswith(b'RIFF') and content[8:12]==b'WEBP':return 'image/webp'
    if content.startswith(b'OggS'):return 'audio/ogg'
    if content.startswith(b'#!AMR'):return 'audio/amr'
    if content.startswith(b'ID3'):return 'audio/mpeg'
    if content[4:8]==b'ftyp':
        return 'image/avif' if content[8:12] in [b'avif',b'avis'] else 'video/mp4'
    declared=declared.lower().split(';')[0]
    if declared.startswith(('image/','audio/','video/')) and not content.lstrip().lower().startswith((b'<!doctype html',b'<html')):return declared
    return ''


def retain_previous_scope(previous,current):
    """A failed refresh retains same-day evidence, explicitly labelled as previous capture."""
    if not previous or current.get('status')=='ready' or previous.get('date')!=current.get('date'):return current
    import copy
    seen={s['id']:s for s in current.get('sessions',[])}
    retained=False
    for old in previous.get('sessions',[]):
        if old['id'] not in seen:
            saved=copy.deepcopy(old);saved['retained_from']=previous.get('collected_at','')
            current['sessions'].append(saved);retained=True
        else:
            new=seen[old['id']];ids={m['id'] for m in new['messages']}
            for m in old['messages']:
                if m['id'] not in ids:
                    saved=copy.deepcopy(m);saved['retained_from']=previous.get('collected_at','')
                    new['messages'].append(saved);retained=True
            new['messages'].sort(key=lambda m:m.get('timestamp',''))
    if retained:current['previous_capture_at']=previous.get('collected_at','')
    return current


def unique_group_store(merchant_stores,hint_stores):
    choices=(set(merchant_stores)-{''}) or (set(hint_stores)-{''})
    return next(iter(choices)) if len(choices)==1 else ''
