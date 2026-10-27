"""Authenticated read-only mirror of sanitized Mac mini status."""
import json
import time
from pathlib import Path
from .longxia_config import DEFAULT

STORE_FIELDS={'id','name','bound','storeName','accountType','templateName','dailyBudget','lunchBudget','dinnerBudget','minBid','maxBid','platformBudget','spend','expected','gap','bid','bidScope','snapshotAt','day','status','pending','paused','promotionStatus','message','resultAt','nextDue','amounts'}
TOP_FIELDS={'schema','generatedAt','day','version','on','readOnly','busy','current','trial','sync','summary','stores','log'}

def read(path,now=None):
    now=int(time.time()*1000) if now is None else now
    path=Path(path)
    if not path.exists():return {'available':False,'online':False,'serverTime':now,'message':'等待 Mac mini 首次回传'}
    try:
        if path.stat().st_size>524288:raise ValueError('状态文件过大')
        raw=json.loads(path.read_text())
        if not isinstance(raw,dict) or raw.get('schema')!=1 or type(raw.get('generatedAt')) is not int or raw['generatedAt']>now+60000:raise ValueError('状态版本或时间无效')
        stores=raw.get('stores')
        if not isinstance(stores,list) or not 1<=len(stores)<=16 or any(not isinstance(s,dict) for s in stores):raise ValueError('门店清单无效')
        known={s['profileId'] for s in DEFAULT['stores']}
        identities={s.get('id') for s in stores}
        if len(identities)!=len(stores) or not known.issubset(identities):raise ValueError('门店身份不匹配')
        # Exporter and relay only publish business status. Fail closed if raw fields leak.
        if set(raw)-TOP_FIELDS or any(set(s)-STORE_FIELDS for s in stores):raise ValueError('状态含未授权字段')
        age=now-raw['generatedAt']
        return {**raw,'available':True,'online':age<=90000,'ageMs':max(0,age),'serverTime':now,'message':'Mac mini 正常回传' if age<=90000 else 'Mac mini 回传已过期，以下为最后一次状态'}
    except (OSError,ValueError,TypeError,KeyError):
        return {'available':False,'online':False,'serverTime':now,'message':'状态回传格式异常，等待 Mac mini 更新'}
