"""Rank below-store-average margin baskets without allocating order income.

All monetary values refer to the full order, including any add-ons. A basket
family is not a separately allocated standalone product margin.
"""
import argparse
import collections
from decimal import Decimal as D
import json
from pathlib import Path

from diagnose_order_margin_change import group, main_item, metric


def summarize(orders):
    total = metric(orders)
    groups = collections.defaultdict(list)
    for o in orders:
        groups[group(o)].append(o)
    rows = []
    for label, os in groups.items():
        m = metric(os)
        shortfall = total['margin']*m['income']-m['profit']
        platforms = []
        for platform in sorted(set(o['platform'] for o in os)):
            platforms.append(dict(platform=platform, **metric([o for o in os if o['platform']==platform])))
        selections = collections.defaultdict(list)
        for o in os:
            mains = sorted(set(p['name'].replace('草饲眼肉牛排饭','炙烤谷饲眼肉牛排饭')
                              for p in o['expanded_items'] if main_item(p['name'])))
            selections['＋'.join(mains) or '无主食'].append(o)
        row = dict(group=label, **m, profit_per_order=m['profit']/m['orders'],
                   income_share=m['income']/total['income'],
                   gap_below_store_margin_pp=(total['margin']-m['margin'])*100,
                   shortfall_to_store_average=shortfall,
                   drag_pp=shortfall/total['income']*100,
                   single_sale_item_orders=sum(len(o['items'])==1 for o in os),
                   platform_details=platforms,
                   main_selection_details=[dict(selection=k,**metric(v)) for k,v in sorted(selections.items())])
        rows.append(row)
    assert sum(r['orders'] for r in rows)==total['orders']
    assert sum(r['income'] for r in rows)==total['income']
    assert sum(r['cost'] for r in rows)==total['cost']
    assert abs(sum(r['shortfall_to_store_average'] for r in rows)) < D('0.000000001')
    rows.sort(key=lambda r:r['shortfall_to_store_average'],reverse=True)
    return dict(overall=total, below_average=[r for r in rows if r['shortfall_to_store_average']>0],
                all_groups=rows)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--analysis',type=Path,required=True)
    p.add_argument('--date',required=True)
    p.add_argument('--stores',nargs='+',required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    d=json.loads(a.analysis.read_text())
    result=[]
    for store in a.stores:
        orders=[o for o in d['orders'] if o['store']==store and o['date']==a.date and not o['canceled']]
        assert orders and all(o['cost'] is not None for o in orders)
        result.append(dict(store=store,**summarize(orders)))
    out=dict(date=a.date,source=a.analysis.name,stores=result,
             definition='Below average means basket-family margin below the same store current-date revenue-weighted margin. Order income and add-on costs remain in the complete basket; no arbitrary income allocation to products. Ranking is by (store margin * group income - group profit); this comparison amount is not an actual loss or a guaranteed recoverable gain. Three-piece sets retain selected-main detail separately.')
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(out,ensure_ascii=False,indent=2,default=str))
    for s in result:
        print(s['store'], 'valid_orders',s['overall']['orders'],'below_average_groups',len(s['below_average']))


if __name__=='__main__':main()
