"""Read the existing fleet export. No browser, network, or fallback collector."""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = Path.home() / 'Library/Application Support/xiong-dianjin-fleet-test/fleet-public-status.json'
CONFIG_PATH = ROOT / 'config/promo_budget_overrides.json'
TZ = timezone(timedelta(hours=8))
MAX_SNAPSHOT_AGE_MS = 30 * 60 * 1000


def read_records(tasks, *, path=None, config_path=None, now=None):
    now = int(time.time() * 1000) if now is None else now
    day = datetime.fromtimestamp(now / 1000, TZ).strftime('%F')
    records = []
    try:
        path = Path(path or SNAPSHOT_PATH)
        if path.stat().st_size > 524288:
            raise ValueError('龙虾快照文件过大')
        payload = json.loads(path.read_text())
        generated = payload.get('generatedAt')
        if payload.get('schema') != 1 or type(generated) is not int or not -60000 <= now - generated <= 90000:
            raise ValueError('龙虾店长状态缺失或已过期')
        rows = payload.get('stores')
        if not isinstance(rows, list) or not 1 <= len(rows) <= 16 or any(not isinstance(row, dict) or not row.get('id') for row in rows):
            raise ValueError('龙虾门店清单无效')
        by_id = {row['id']: row for row in rows}
        if len(by_id) != len(rows):
            raise ValueError('龙虾门店身份重复')
        config = json.loads(Path(config_path or CONFIG_PATH).read_text())['longxia']['stores']
        error = ''
    except (OSError, ValueError, TypeError, KeyError) as exc:
        by_id, config, error = {}, [], '龙虾快照不可用：' + type(exc).__name__
    for task in tasks:
        record = {key: task[key] for key in ('keyword', 'store', 'sourceStore') if key in task}
        record.update(ok=False, source='longxia_snapshot', today_spend=None, budget=None,
                      snapshot_at=None, error=error, elapsed_seconds=0)
        if not error:
            # Match configured identity exactly, then read by immutable fleet profile id.
            names = {str(task.get(key) or '') for key in ('sourceStore', 'keyword', 'store')} - {''}
            matches = [row for row in config if names.intersection({row.get('name'), row.get('sourceStore')})]
            if len(matches) != 1:
                record['error'] = '龙虾门店身份未唯一匹配，未读取'
            else:
                row = by_id.get(matches[0]['profileId'], {})
                at = row.get('snapshotAt')
                spend, budget = row.get('spend'), row.get('platformBudget')
                if row.get('paused') or row.get('status') == 'error':
                    record['error'] = '龙虾门店暂停或异常：' + str(row.get('message') or '')
                elif row.get('day') != day or type(at) is not int or not -60000 <= now - at <= MAX_SNAPSHOT_AGE_MS:
                    record['error'] = '龙虾店长尚无今日有效推广快照；等待龙虾采集，不逐店补读'
                elif type(spend) is not int or spend < 0:
                    record['error'] = '龙虾快照未提供有效推广消耗'
                else:
                    record.update(ok=True, error='', today_spend=spend / 100, snapshot_at=at)
                    if type(budget) is int and budget >= 0:
                        record['budget'] = budget / 100
                        record['budget_source'] = 'longxia_platform_snapshot'
                        record['remaining_budget'] = max(budget - spend, 0) / 100
                        record['budget_percent'] = round(spend / budget * 100, 1) if budget else None
        records.append(record)
    return records


def read_balance_items(*, path=None, config_path=None, now=None):
    """Reuse fleet reads; no browser, subprocess, queue lease or platform request."""
    now = int(time.time() * 1000) if now is None else now
    day = datetime.fromtimestamp(now / 1000, TZ).strftime('%F')
    items, issues = [], []
    config = json.loads(Path(config_path or CONFIG_PATH).read_text())['longxia']['stores']
    if not config or len({r['profileId'] for r in config}) != len(config):
        raise ValueError('龙虾余额门店配置缺失或身份重复')
    try:
        source = Path(path or SNAPSHOT_PATH)
        if source.stat().st_size > 524288:
            raise ValueError('快照过大')
        data = json.loads(source.read_text())
        generated = data.get('generatedAt')
        rows = data.get('stores')
        if data.get('schema') != 1 or type(generated) is not int or not -60000 <= now-generated <= 90000:
            raise ValueError('龙虾状态文件缺失或过期')
        if not isinstance(rows, list) or not 1 <= len(rows) <= 16 or any(not isinstance(r, dict) or not r.get('id') for r in rows):
            raise ValueError('龙虾门店清单无效')
        by_id = {r['id']: r for r in rows}
        if len(by_id) != len(rows):
            raise ValueError('龙虾门店身份重复')
        error = ''
    except (OSError, ValueError, TypeError) as exc:
        by_id, error = {}, '龙虾余额快照不可用：' + type(exc).__name__
    for store in config:
        row = by_id.get(store['profileId'], {})
        at, balance = row.get('snapshotAt'), row.get('accountBalance')
        reason = error
        if not reason:
            if row.get('paused') or row.get('status') in {'error', 'inspection_paused', 'pending'}:
                reason = '门店巡检暂停、异常或有待核对保存'
            elif row.get('day') != day or type(at) is not int or not -60000 <= now-at <= MAX_SNAPSHOT_AGE_MS:
                reason = '尚无当日有效余额快照或快照已过期'
            elif type(balance) is not int or abs(balance) > 10**12:
                reason = '推广页未读到账户余额（不能用剩余预算替代）'
        name = store.get('name') or store.get('sourceStore') or store['profileId']
        if reason:
            issues.append({'platform': '美团', 'store_name': name, 'message': reason})
        else:
            items.append({'platform': '美团', 'store_name': name, 'balance': balance / 100,
                          'source': '龙虾店长账户余额快照', 'confirmed_zero': balance == 0,
                          'balance_field': 'accountBalance',
                          'collected_at': datetime.fromtimestamp(at/1000, TZ).strftime('%F %T')})
    return items, issues
