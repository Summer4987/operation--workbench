"""Explain observed margin changes from already collected private snapshots.

The symmetric decomposition separates revenue mix from within-group margin.
It is an accounting identity, not proof that a platform or promotion caused it.
"""
import argparse
import collections
from decimal import Decimal as D
import json
from pathlib import Path
import re


def metric(orders):
    income = sum((D(o['income']) for o in orders), D(0))
    cost = sum((D(o['cost']) for o in orders), D(0))
    return dict(orders=len(orders), income=income, cost=cost, profit=income-cost,
                margin=(income-cost)/income if income else D(0),
                income_per_order=income/len(orders) if orders else D(0),
                cost_per_order=cost/len(orders) if orders else D(0))


def main_item(name):
    return (('饭' in name and '加一份' not in name and '选购指南' not in name)
            or ('现烤' in name and '土豆泥' in name))


def group(order):
    labels = []
    for item in order['items']:
        name = item['raw_name']
        if item['parts'] and any(main_item(p['name']) for p in item['parts']):
            if '三件套' in name:
                labels.append('三件套')
            elif '1+1+1' in name or '随心配' in name:
                labels.append('随心配')
            elif '人气拍档' in name:
                labels.append('牛五花＋土豆泥组合')
            elif '热销安格斯牛五花单人餐' in name:
                labels.append('牛五花单人餐')
            else:
                labels.append(name)
        elif main_item(item['name']):
            labels.append(item['name'].replace('草饲眼肉牛排饭','炙烤谷饲眼肉牛排饭'))
    unique = set(labels)
    return next(iter(unique)) if len(unique) == 1 else '多主食混合订单' if unique else '仅配菜或其他'


def decompose(old, new, key):
    totals = [metric(old), metric(new)]
    grouped = []
    for orders in [old, new]:
        groups = collections.defaultdict(list)
        for o in orders:
            groups[key(o)].append(o)
        grouped.append(groups)
    result = []
    for label in sorted(set(grouped[0]) | set(grouped[1])):
        a, b = [metric(g.get(label, [])) for g in grouped]
        wa, wb = a['income']/totals[0]['income'], b['income']/totals[1]['income']
        # For an entering/exiting category the unobserved rate is held equal
        # to its observed rate; its entire contribution is a composition term.
        ra = a['margin'] if a['orders'] else b['margin']
        rb = b['margin'] if b['orders'] else a['margin']
        within = (wa+wb)/2*(rb-ra)
        # Center composition effects on the midpoint store margin so growth
        # in a below-average-margin segment is shown as a negative effect.
        # The total is unchanged because all share changes sum to zero.
        reference = (totals[0]['margin']+totals[1]['margin'])/2
        mix = ((ra+rb)/2-reference)*(wb-wa)
        result.append(dict(group=label, old=a, new=b, old_income_share=wa,
                           new_income_share=wb, within_pp=within*100,
                           mix_pp=mix*100, contribution_pp=(within+mix)*100))
    delta = (totals[1]['margin']-totals[0]['margin'])*100
    assert abs(sum(r['contribution_pp'] for r in result)-delta) < D('0.000000001')
    return dict(old=totals[0], new=totals[1], delta_pp=delta,
                within_pp=sum(r['within_pp'] for r in result),
                mix_pp=sum(r['mix_pp'] for r in result), groups=result)


def amount(text, pattern):
    match = re.search(pattern, text, re.S)
    return D(match[1]) if match else D(0)


def fees(order, text):
    if order['platform'] == '美团':
        goods = sum((D(x) for x in re.findall(r'¥[\d.]+x\d+¥([\d.]+)',text)),D(0))
        parts = dict(goods=goods,
            packaging=amount(text,r'打包费\n￥([\d.]+)'),
            discount=amount(text,r'商家给顾客的订单优惠\n-￥([\d.]+)'),
            delivery_subsidy=amount(text,r'商家给顾客的配送补贴\n-￥([\d.]+)'),
            commission=amount(text,r'佣金\([^\n]*\)\n-￥([\d.]+)'),
            delivery=amount(text,r'配送服务费(?:\n[^\n￥]*)?\n-￥([\d.]+)'))
    else:
        goods = sum((D(x) for x in re.findall(r'\nx\d+\n¥([\d.]+)',text)),D(0))
        parts = dict(goods=goods,
            packaging=amount(text,r'打包费\n¥([\d.]+)'),
            discount=amount(text,r'商家对顾客的订单补贴\n-¥([\d.]+)'),
            delivery_subsidy=amount(text,r'商家对顾客的配送补贴\n-¥([\d.]+)'),
            commission=amount(text,r'技术服务费\(佣金\)\n-¥([\d.]+)'),
            delivery=amount(text,r'配送服务费\n-¥([\d.]+)'))
    calculated=parts['goods']+parts['packaging']-sum(parts[k] for k in ['discount','delivery_subsidy','commission','delivery'])
    parts['residual']=D(order['listed_income'])-calculated
    return parts


def summarize_fees(orders, raw):
    summary=collections.defaultdict(D)
    residuals=[]
    for o in orders:
        f=fees(o,raw[(o['platform'],o['id'])])
        for k,v in f.items():summary[k]+=v
        if f['residual']:residuals.append(dict(platform=o['platform'],id=o['id'],residual=f['residual']))
    return dict(totals=dict(summary),per_order={k:v/len(orders) for k,v in summary.items()},residual_orders=residuals)


def signature(order):
    parts=collections.Counter()
    for p in order['expanded_items']:
        parts[p['name'].replace('草饲眼肉牛排饭','炙烤谷饲眼肉牛排饭')]+=p['quantity']
    return tuple(sorted(parts.items()))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--analysis',type=Path,required=True)
    p.add_argument('--snapshots',type=Path,nargs='+',required=True)
    p.add_argument('--stores',nargs='+',required=True)
    p.add_argument('--baseline',default='2026-11-22')
    p.add_argument('--current',default='2026-11-23')
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    data=json.loads(a.analysis.read_text())
    raw={}
    for path in a.snapshots:
        for line in path.read_text().splitlines():
            rec=json.loads(line)
            for page in rec['pages']:
                for text in re.split(r'(?m)^#',page['text'])[1:]:
                    pat=r'订单编号：(\d+)' if rec['platform']=='美团' else r'单号:\n(\d+)'
                    oid=re.search(pat,text)
                    assert oid
                    key=(rec['platform'],oid[1])
                    assert key not in raw or raw[key]==text
                    raw[key]=text
    assert all((o['platform'],o['id']) in raw for o in data['orders'])
    results=[]
    for store in a.stores:
        os=[o for o in data['orders'] if o['store']==store and not o['canceled']]
        assert all(o['cost'] is not None for o in os)
        old=[o for o in os if o['date']==a.baseline]
        new=[o for o in os if o['date']==a.current]
        assert old and new
        platforms=[]
        for platform in sorted(set(o['platform'] for o in os)):
            periods=[[o for o in period if o['platform']==platform] for period in [old,new]]
            fa,fb=[summarize_fees(period,raw) for period in periods]
            matched=[]
            groups=[]
            for period in periods:
                g=collections.defaultdict(list)
                for o in period:g[signature(o)].append(o)
                groups.append(g)
            for sig in set(groups[0])&set(groups[1]):
                aa,bb=groups[0][sig],groups[1][sig]
                matched.append(dict(items=list(sig),old=metric(aa),new=metric(bb),
                    old_fees=summarize_fees(aa,raw),new_fees=summarize_fees(bb,raw)))
            platforms.append(dict(platform=platform,old_fees=fa,new_fees=fb,
                                  basket_decomposition=decompose(*periods,group),matched_baskets=matched))
        results.append(dict(store=store,platform_decomposition=decompose(old,new,lambda o:o['platform']),
            basket_decomposition=decompose(old,new,group),platform_details=platforms,
            refunds=[dict(date=day,orders=sum(o['canceled'] for o in data['orders'] if o['store']==store and o['date']==day),
                prepared_waste=sum((D(o['cost']) for o in data['orders'] if o['store']==store and o['date']==day and o['canceled'] and o['prepared']),D(0))) for day in [a.baseline,a.current]]))
    out=dict(baseline=a.baseline,current=a.current,analysis_source=a.analysis.name,
             snapshot_sources=[x.name for x in a.snapshots],stores=results,
             method='Symmetric revenue-share decomposition: delta margin=sum(avg revenue share * delta segment margin + (avg segment margin - midpoint total margin) * delta revenue share). Centering does not change the total, as share changes sum to zero. Separate platform and basket decompositions overlap and must not be added. Matched baskets retain full product quantities and platform identity; no allocation of basket revenue to individual dishes.')
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(out,ensure_ascii=False,indent=2,default=lambda x:str(x) if isinstance(x,D) else x))
    for r in results:
        dec=r['platform_decomposition']
        print(r['store'],json.dumps({k:v for k,v in dec.items() if k!='groups'},ensure_ascii=False,default=str))


if __name__=='__main__':main()
