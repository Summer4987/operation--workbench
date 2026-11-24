"""Review one store/platform using complete order baskets and matched contents.

Platform and basket comparisons explain accounting differences, not traffic or
promotion-setting causality. All private inputs/outputs stay outside Git.
"""
import argparse
import collections
from decimal import Decimal as D
import json
from pathlib import Path
import re

from diagnose_order_margin_change import decompose, fees, group, metric, signature


def fee_summary(orders, raw):
    amounts = collections.defaultdict(D)
    rates = collections.Counter()
    for o in orders:
        text = raw[o['platform'], o['id']]
        parts = fees(o, text)
        assert parts['residual'] == 0
        for k, v in parts.items():
            amounts[k] += v
        rate = re.search(r'佣金\(([^\n]*)\)', text)
        if rate:
            rates[rate[1]] += 1
    n = len(orders)
    return dict(totals=dict(amounts), per_order={k:v/n for k,v in amounts.items()},
                commission_rate_labels=dict(rates),
                income_before_platform_delivery=(amounts['goods']+amounts['packaging']-amounts['discount'])/n)


def read_raw(paths):
    result = {}
    for path in paths:
        for line in path.read_text().splitlines():
            record = json.loads(line)
            pattern = r'订单编号：(\d+)' if record['platform']=='美团' else r'单号:\n(\d+)'
            for page in record['pages']:
                for text in re.split(r'(?m)^#', page['text'])[1:]:
                    key = record['platform'], re.search(pattern,text)[1]
                    assert key not in result or result[key] == text
                    result[key] = text
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--analysis', type=Path, required=True)
    p.add_argument('--snapshots', type=Path, nargs='+', required=True)
    p.add_argument('--store', required=True)
    p.add_argument('--platform', default='美团')
    p.add_argument('--reference-platform', default='饿了么')
    p.add_argument('--peer-store')
    p.add_argument('--date', required=True)
    p.add_argument('--history-analysis', type=Path, nargs='*', default=[])
    p.add_argument('--history-dates', nargs='*', default=[])
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    data = json.loads(a.analysis.read_text())
    raw = read_raw(a.snapshots)
    valid = [o for o in data['orders'] if o['date']==a.date and not o['canceled']]
    orders = [o for o in valid if o['store']==a.store and o['platform']==a.platform]
    reference = [o for o in valid if o['store']==a.store and o['platform']==a.reference_platform]
    assert orders and reference and all(o['cost'] is not None for o in orders+reference)
    overall = metric(orders)
    grouped = collections.defaultdict(list)
    for o in orders:
        grouped[group(o)].append(o)
    families = []
    for label, os in grouped.items():
        row = metric(os)
        families.append(dict(group=label, **row, income_share=row['income']/overall['income'],
            shortfall_to_store_average=overall['margin']*row['income']-row['profit'],
            fees=fee_summary(os,raw)))
    families.sort(key=lambda x:x['shortfall_to_store_average'],reverse=True)
    assert sum(x['income'] for x in families)==overall['income']
    assert sum(x['cost'] for x in families)==overall['cost']
    assert abs(sum(x['shortfall_to_store_average'] for x in families)) < D('0.000000001')
    selected = {x['group'] for x in families if x['shortfall_to_store_average']>0}
    top = {x['group'] for x in families[:3] if x['shortfall_to_store_average']>0}
    matching = collections.defaultdict(lambda:collections.defaultdict(list))
    for o in orders+reference:
        matching[signature(o)][o['platform']].append(o)
    matched = []
    for sig, platforms in matching.items():
        if len(platforms)!=2:
            continue
        cells = [dict(platform=k, **metric(v), fees=fee_summary(v,raw)) for k,v in sorted(platforms.items())]
        assert cells[0]['cost_per_order']==cells[1]['cost_per_order']
        matched.append(dict(items=list(sig),platforms=cells))
    matched.sort(key=lambda x:(-min(p['orders'] for p in x['platforms']),str(x['items'])))
    history = []
    history_orders = {}
    for path in a.history_analysis:
        doc = json.loads(path.read_text())
        for o in doc['orders']:
            day = o.get('date',doc.get('date'))
            if day not in a.history_dates or o['store']!=a.store or o['platform']!=a.platform or o['canceled']:
                continue
            history_orders[o['platform'],o['id']] = dict(o,date=day)
    for day in sorted({o['date'] for o in history_orders.values()}):
        history.append(dict(date=day, **metric([o for o in history_orders.values() if o['date']==day])))
    out = dict(date=a.date,store=a.store,platform=a.platform,reference_platform=a.reference_platform,
        overall=overall,reference=metric(reference),fees=fee_summary(orders,raw),
        reference_fees=fee_summary(reference,raw),families=families,
        below_average_groups=sorted(selected),
        top_three_groups=dict(groups=sorted(top),**metric([o for o in orders if group(o) in top])),
        other_groups=metric([o for o in orders if group(o) not in top]),
        reference_decomposition=decompose(reference,orders,group),matched_baskets=matched,
        history=history,known_waste=sum((D(o['cost']) for o in data['orders']
            if o['store']==a.store and o['platform']==a.platform and o['date']==a.date
            and o['canceled'] and o['prepared']),D(0)),
        sources=dict(analysis=a.analysis.name,snapshots=[x.name for x in a.snapshots],
                     history=[x.name for x in a.history_analysis]))
    if a.peer_store:
        peer = [o for o in valid if o['store']==a.peer_store and o['platform']==a.platform]
        assert peer
        out['peer_comparison'] = dict(store=a.peer_store,overall=metric(peer),fees=fee_summary(peer,raw),
            decomposition=decompose(peer,orders,group))
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(out,ensure_ascii=False,indent=2,default=str))
    print(json.dumps({k:out[k] for k in ['store','platform','overall','reference','history','known_waste']},ensure_ascii=False,default=str))


if __name__ == '__main__':
    main()
