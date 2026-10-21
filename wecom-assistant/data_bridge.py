"""Business reads only. No collection, ordering, platform actions or publication."""
import json
import math
import os
import shlex
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


def validate(q):
    a, b = date.fromisoformat(q['start']), date.fromisoformat(q['end'])
    if not 0 <= (b-a).days <= 92:
        raise ValueError('查询日期范围须为1至93天')
    if q.get('region', 'all') not in ('all', 'chengdu', 'beijing', 'daily'):
        raise ValueError('不支持的订货区域')
    if q.get('scope', 'all') not in ('all', 'franchise', 'direct'):
        raise ValueError('不支持的经营范围')
    if q.get('kind') == 'business_comparison':
        pa, pb = date.fromisoformat(q['previous_start']), date.fromisoformat(q['previous_end'])
        if (pb-pa).days != (b-a).days:
            raise ValueError('经营对比需要两段天数相同的期间，请明确起止日期')
        if not (pb < a or b < pa):
            raise ValueError('两段经营对比期间不能重叠')


def business(q, roots):
    rows, sources, errors = [], [], []
    for scope, name in [('franchise', 'latest.json'), ('direct', 'direct-latest.json')]:
        if q.get('scope', 'all') not in ('all', scope):
            continue
        candidates = []
        for root in roots:
            p = root / 'business-report-dashboard' / 'data' / name
            if p.exists():
                try:
                    payload = json.loads(p.read_text())
                    candidates.append((str(payload.get('generated_at', '')), p.stat().st_mtime, payload))
                except (OSError, ValueError):
                    errors.append(scope + '有源文件无法解析')
        if not candidates:
            errors.append(scope + '经营数据不存在')
            continue
        payload = max(candidates, key=lambda x: x[:2])[2]
        records = payload.get('records', [])
        latest = max((str(r.get('date', '')) for r in records), default='')
        sources.append({'scope': scope, 'generated_at': payload.get('generated_at'), 'latest_date': latest})
        for r in records:
            if not q['start'] <= str(r.get('date', '')) <= q['end']:
                continue
            if q.get('store') and q['store'] not in str(r.get('store', '')):
                continue
            row = {'范围': '加盟' if scope == 'franchise' else '直营', '日期': r.get('date'),
                   '门店': r.get('store'), '平台': r.get('platform'),
                   '收入': r.get('income'), '订单数': r.get('orders'),
                   '顾客实付': r.get('customer_paid') if r.get('customer_paid_available') else None}
            rows.append({k: None if isinstance(v, float) and not math.isfinite(v) else v for k, v in row.items()})
    groups = {}
    for row in rows:
        key = (row['范围'], row['门店'])
        group = groups.setdefault(key, {'范围': key[0], '门店': key[1], '收入': 0, '订单数': 0, '记录数': 0, '收入缺失记录数': 0})
        group['记录数'] += 1
        if row.get('收入') is None:
            group['收入缺失记录数'] += 1
        else:
            group['收入'] += float(row['收入'])
        group['订单数'] += float(row.get('订单数') or 0)
    for group in groups.values():
        group['收入'] = round(group['收入'], 2) if group['收入缺失记录数'] < group['记录数'] else None
    available = {str(r['日期']) for r in rows}
    start, end = date.fromisoformat(q['start']), date.fromisoformat(q['end'])
    missing = [(start + timedelta(days=i)).isoformat() for i in range((end-start).days+1)
               if (start + timedelta(days=i)).isoformat() not in available]
    return {'source': 'Mac mini 正式日报产物', 'start': q['start'], 'end': q['end'],
            'sources': sources, 'rows': rows, 'line_count': len(rows), 'errors': errors,
            'store_totals': list(groups.values()), 'missing_dates': missing,
            'missing_income_rows': sum(1 for r in rows if r.get('收入') is None),
            'totals': {'收入': round(sum(float(r['收入']) for r in rows if r.get('收入') is not None), 2) if any(r.get('收入') is not None for r in rows) else None,
                       '订单数': sum(float(r.get('订单数') or 0) for r in rows)},
            'note': '收入与顾客实付口径不同；空值不代表零。只覆盖已有日报记录，不保证所有门店平台完整。'}


def realtime(q, roots, now=None):
    """Latest collected franchise sales snapshot; never supply-order data or live polling."""
    now = now or datetime.now(timezone(timedelta(hours=8)))
    if q.get('scope') == 'direct':
        raise ValueError('当前实时采集仅覆盖加盟门店，不能作为直营门店实时数据')
    candidates, errors = [], []
    for root in roots:
        p = root / 'outputs/realtime_order_income/latest.json'
        if not p.exists():
            continue
        try:
            payload = json.loads(p.read_text())
            stamp = datetime.fromisoformat(str(payload['generated_at']))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone(timedelta(hours=8)))
            if stamp > now + timedelta(minutes=5):
                raise ValueError('future timestamp')
            candidates.append((stamp, p.stat().st_mtime, payload))
        except (OSError, ValueError, KeyError, TypeError):
            errors.append('有实时数据源无法解析或时间异常')
    if not candidates:
        raise ValueError('实时经营数据不存在或不可用；不能用订货量代替销售单量')
    stamp, _, payload = max(candidates, key=lambda x: x[:2])
    age = max(0, int((now-stamp).total_seconds()/60))
    stale = stamp.date() != now.date() or age > 60
    reset = payload.get('status') == 'reset' or bool((payload.get('summary') or {}).get('daily_reset'))
    if reset:
        errors.append('当前为每日重置占位，尚未采集有效数据，不能把占位零当作真实零单')
    if stale:
        errors.append('实时快照已过期，以下仅为最近一次采集，不能代表此刻单量')
    if payload.get('status') != 'ok':
        errors.append('最近快照状态：'+str(payload.get('status', '未知')))
    stores = payload.get('stores') or []
    targets = payload.get('target_stores') or [s.get('store') for s in stores]
    names = sorted(set(str(n) for n in targets if n) | {str(s.get('store')) for s in stores if s.get('store')})
    wanted = str(q.get('store') or '').strip()
    selected = [n for n in names if not wanted or wanted in n]
    by_store = {s.get('store'): s for s in stores}
    rows, totals = [], []
    def number(v):
        return float(v) if not isinstance(v, bool) and isinstance(v, (int,float)) and math.isfinite(v) and v >= 0 else None
    for name in selected:
        platforms = by_store.get(name, {}).get('platforms') or {}
        for platform in sorted(set(platforms) | {'美团', '饿了么'}):
            item = platforms.get(platform) or {}
            orders = None if reset or item.get('source') in ('daily_reset','account_scope') or item.get('income_status') == 'account_out' else number(item.get('orders'))
            income = None if reset or item.get('income_status') not in ('trusted',) else number(item.get('income'))
            rows.append({'范围':'加盟', '日期':stamp.date().isoformat(), '门店':name, '平台':platform,
                         '订单数':orders, '收入':income,
                         '状态':'单量缺失' if orders is None else ('收入缺失或未验证' if income is None else '已采集')})
        rr = [r for r in rows if r['门店'] == name]
        values = [r['订单数'] for r in rr if r['订单数'] is not None]
        money = [r['收入'] for r in rr if r['收入'] is not None]
        totals.append({'范围':'加盟','门店':name, '订单数':sum(values) if values else None,
                       '收入':round(sum(money),2) if money else None,
                       '记录数':len(rr), '收入缺失记录数':sum(r['收入'] is None for r in rr),
                       '单量缺失记录数':sum(r['订单数'] is None for r in rr)})
    if wanted and not selected:
        errors.append('没有匹配的加盟门店：'+wanted)
    missing = sum(r['订单数'] is None for r in rows)
    if missing:
        errors.append(str(missing)+'个平台门店单量缺失，合计仅包含已采集部分')
    if payload.get('missing') or payload.get('account_out') or payload.get('errors'):
        errors.append('采集源报告缺失、退出账号或异常；请查看实时采集状态')
    values = [r['订单数'] for r in rows if r['订单数'] is not None]
    money = [r['收入'] for r in rows if r['收入'] is not None]
    return {'source':'Mac mini 正式加盟店实时采集快照', 'start':stamp.date().isoformat(), 'end':stamp.date().isoformat(),
            'generated_at':payload['generated_at'], 'age_minutes':age, 'stale':stale, 'reset':reset,
            'scope':'franchise', 'available_stores':names, 'store_count':len(selected),
            'platform_store_count':len(rows), 'missing_order_rows':missing,
            'sources':[{'scope':'franchise','generated_at':payload['generated_at'],'latest_date':stamp.date().isoformat()}],
            'rows':rows, 'line_count':len(rows), 'store_totals':totals,
            'totals':{'订单数':sum(values) if values else None, '收入':round(sum(money),2) if money else None},
            'errors':errors, 'note':'门店销售有效订单数，非采购订货量。读取最近一次正式采集快照，不触发平台刷新；按美团、饿了么分平台汇总。缺失不是零；有缺失时合计仅为已采集部分；收入仅含已验证值。'}


def business_comparison(q, roots):
    current = business(q, roots)
    previous = business(dict(q, start=q['previous_start'], end=q['previous_end']), roots)
    day_count = (date.fromisoformat(q['end'])-date.fromisoformat(q['start'])).days+1
    store_keys = sorted({(r['范围'], r['门店']) for r in current['rows']+previous['rows']})
    comparisons = []
    for scope, store in store_keys:
        a = [r for r in current['rows'] if (r['范围'], r['门店']) == (scope, store)]
        b = [r for r in previous['rows'] if (r['范围'], r['门店']) == (scope, store)]
        platforms = sorted({r['平台'] for r in a+b})
        comparable, excluded = [], []
        income_a = income_b = orders_a = orders_b = 0
        for platform in platforms:
            aa = [r for r in a if r['平台'] == platform]
            bb = [r for r in b if r['平台'] == platform]
            # A duplicate, missing date or missing value makes this platform unavailable.
            complete = all(len(period) == day_count and len({r['日期'] for r in period}) == day_count
                           and all(r.get('收入') is not None and r.get('订单数') is not None for r in period)
                           for period in [aa, bb])
            if not complete:
                excluded.append(platform)
                continue
            comparable.append(platform)
            income_a += sum(float(r['收入']) for r in aa)
            income_b += sum(float(r['收入']) for r in bb)
            orders_a += sum(float(r['订单数']) for r in aa)
            orders_b += sum(float(r['订单数']) for r in bb)
        valid = bool(comparable)
        delta = round(income_a-income_b, 2) if valid else None
        order_delta = orders_a-orders_b if valid else None
        comparisons.append({'范围': scope, '门店': store,
                            '本期可比收入': round(income_a, 2) if valid else None,
                            '上期可比收入': round(income_b, 2) if valid else None,
                            '收入差额': delta, '收入变化率': delta/income_b if valid and income_b else None,
                            '本期可比订单': orders_a if valid else None,
                            '上期可比订单': orders_b if valid else None,
                            '订单差额': order_delta, '订单变化率': order_delta/orders_b if valid and orders_b else None,
                            '可比平台': '、'.join(comparable),
                            '状态': ('缺失或重复记录，未纳入：'+'、'.join(excluded)) if excluded else '两期记录完整'})
    comparisons.sort(key=lambda r: (r['收入变化率'] is None, r['收入变化率'] or 0))
    return {'source': current['source'], 'start': q['start'], 'end': q['end'],
            'previous_start': q['previous_start'], 'previous_end': q['previous_end'],
            'sources': current['sources'], 'rows': comparisons, 'line_count': len(comparisons),
            'detail_rows': [dict(r, 期间='本期') for r in current['rows']]+[dict(r, 期间='上期') for r in previous['rows']],
            'errors': sorted(set(current['errors']+previous['errors'])),
            'note': '按两期均逐日完整的相同门店、平台和指标比较。缺失或重复记录的平台不纳入涨跌；上期为零时变化率留空。收入与顾客实付是不同指标，不作因果推断。'}


def query(q):
    validate(q)
    if q['kind'] in ('business', 'business_comparison', 'realtime'):
        roots = [Path(s).expanduser() for s in json.loads(os.environ.get('WECOM_DATA_ROOTS', json.dumps([
            str(Path.home() / 'Library/Application Support/xiong-operation/production'),
            str(Path.home() / 'Documents/operation-workbench-clean')])))]
        if q['kind'] == 'realtime':
            return realtime(q, roots)
        return business_comparison(q, roots) if q['kind'] == 'business_comparison' else business(q, roots)
    if q['kind'] != 'orders':
        raise ValueError('不支持的查询')
    script = Path(__file__).with_name('remote_query.py').read_text()
    command = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8',
               '-o', 'StrictHostKeyChecking=yes']
    key = Path.home() / '.ssh/xiong_operation_cloud_ed25519'
    if key.exists():
        command.extend(['-i', str(key)])
    command.extend([os.environ.get('WECOM_CLOUD_SERVER', 'ubuntu@139.155.148.169'),
                    'python3 -c ' + shlex.quote(script)])
    result = subprocess.run(command, input=json.dumps(q), text=True, capture_output=True, timeout=35)
    if result.returncode:
        raise ValueError('订货数据读取失败；请检查Mac mini至云端的SSH连接和只读数据源')
    return json.loads(result.stdout)


if __name__ == '__main__':
    try:
        print(json.dumps(query(json.load(sys.stdin)), ensure_ascii=False, allow_nan=False))
    except Exception as exc:
        print(json.dumps({'error': str(exc) if isinstance(exc, ValueError) else '数据查询失败或超时'}, ensure_ascii=False))
        sys.exit(1)
