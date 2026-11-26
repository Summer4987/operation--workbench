"""Read-only, allowlisted dashboard projection; never invokes the fleet runner."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

TZ = timezone(timedelta(hours=8))
STORE_FIELDS = {'shopId', 'name', 'bid', 'spend', 'platformBudget', 'expected', 'gap',
                'action', 'reason', 'before', 'after', 'state', 'message', 'simulation'}
EVENT_FIELDS = {'type', 'at', 'shopId', 'name', 'action', 'reason', 'before', 'after',
                'expected', 'actual', 'message', 'simulation'}


def project(value, fields):
    return {k: v for k, v in value.items() if k in fields and
            (v is None or isinstance(v, (str, int, float, bool)))}


def build(root: Path, events_path: Path | None = None, now: datetime | None = None) -> dict:
    now = now or datetime.now(TZ)
    day = now.astimezone(TZ).strftime('%Y-%m-%d')
    try:
        source = json.loads((root / 'outputs/eleme_bid_fleet/latest.json').read_text())
        if not isinstance(source, dict) or not isinstance(source.get('stores'), list):
            raise ValueError('invalid snapshot')
    except (OSError, ValueError):
        source = {'error': '调价数据尚未生成或读取失败', 'stores': []}
    payload = project(source, {'generatedAt', 'day', 'error', 'nextCheckAt', 'simulation'})
    payload['stores'] = [project(s, STORE_FIELDS) for s in source['stores'] if isinstance(s, dict)]
    payload.update(historyDay=day, events=[], historyStatus='ok', historySkipped=0)
    path = events_path or Path.home() / 'Library/Application Support/xiong-eleme-fleet/eleme-fleet-events.jsonl'
    # Include the rotated file so a rotation during the day does not lose history.
    paths = [p for p in (path.with_suffix(path.suffix + '.1'), path) if p.exists()]
    if not paths:
        payload['historyStatus'] = 'missing'
    for p in paths:
        try:
            with p.open(encoding='utf-8') as stream:
                for line in stream:
                    try:
                        event = json.loads(line)
                        stamp = event['at']
                        if isinstance(stamp, bool):
                            raise ValueError('invalid timestamp')
                        date = datetime.fromtimestamp(stamp / 1000, TZ).strftime('%Y-%m-%d')
                        if date == day and event.get('type') in {'decision', 'adjusted', 'error', 'skip', 'recalibrate'}:
                            payload['events'].append(project(event, EVENT_FIELDS))
                    except (ValueError, TypeError, KeyError, OverflowError, OSError):
                        payload['historySkipped'] += 1
        except (OSError, UnicodeError):
            payload['historyStatus'] = 'partial'
    if payload['historySkipped']:
        payload['historyStatus'] = 'partial'
    payload['events'].sort(key=lambda e: e['at'])
    return payload
