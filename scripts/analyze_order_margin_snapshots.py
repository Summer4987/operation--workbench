"""Parse private order snapshots; compute margin without allocating basket income.

Costs are supplied at runtime from the reviewed prior analysis, never inferred.
"""
import argparse
import collections
import datetime as dt
from decimal import Decimal as D
import json
from pathlib import Path
import re


def normalize(name, costs):
    name=name.replace('「招牌」','招牌')
    if '风味西冷牛排饭' in name:return '风味西冷牛排饭'
    if '炙烤眼肉牛排饭' in name:return '炙烤谷饲眼肉牛排饭'
    if '现烤' in name and '土豆泥' in name:
        for cut in ['菲力','板腱','眼肉','牛腩排']:
            if cut in name:return '现烤'+cut+'配黄油土豆泥'
    if '加一份' in name:
        if '酱汁' in name:return '额外酱汁'
        for raw,target in [('牛五花','牛五花'),('板腱','板腱牛排'),('菲力','菲力牛排'),('慢煮法香鸡肉','慢煮法香鸡肉'),('杂粮米饭','杂粮米饭'),('蒜香黄油嫩肩','蒜香黄油嫩肩'),('烤三文鱼','烤三文鱼')]:
            if raw in name:return '加一份'+target
    for raw in ['温泉蛋','低糖辣白菜','鲜豆腐味增汤','招牌黄油土豆泥','芝麻菠菜','山姆椰子水']:
        if raw in name and '饭' not in name:return raw
    for key in sorted(costs,key=len,reverse=True):
        if key in name:return key
    return name


def parse_record(rec,costs,*,normalize_name=normalize):
    mt=rec['platform']=='美团'
    orders=[]
    for page in rec['pages']:
        for text in re.split(r'(?m)^#',page['text'])[1:]:
            items=[]
            expected=re.search(r'(\d+)种商品，共(\d+)件',text)
            assert expected,(rec['store'],'Missing goods header')
            if mt:
                goods=re.search(r'\d+种商品，共\d+件\n收起\n(.*?)(?=\n打包费|\n商家给顾客的订单优惠)',text,re.S)
                assert goods
                lines=goods[1].splitlines()
                for i,line in enumerate(lines):
                    match=re.fullmatch(r'¥[\d.]+x(\d+)¥[\d.]+',line)
                    if not match:continue
                    quantity=int(match[1]);raw=lines[i-1];parts=[]
                    if i+1<len(lines) and re.search(r' x\d+',lines[i+1]):
                        parts=[dict(name=normalize_name(n.strip(),costs),quantity=int(q)) for n,q in re.findall(r'([^，]+?) x(\d+)',lines[i+1])]
                    items.append(dict(raw_name=raw,name=normalize_name(raw,costs),quantity=quantity,parts=parts))
                assert sum(sum(p['quantity'] for p in it['parts']) if it['parts'] else it['quantity'] for it in items)==int(expected[2])
                order_id=re.search(r'订单编号：(\d+)',text)[1]
                order_time=re.search(r'(\d\d-\d\d [\d:]+)下单',text)[1]
                listed=D(re.search(r'预计收入\n￥([\d.]+)',text)[1])
                head=text.split('备注')[0]
            else:
                for match in re.finditer(r'([^\n]+)\nx(\d+)\n¥([\d.]+)',text):
                    raw,q,price=match.groups();q=int(q)
                    following=next((l for l in text[match.end():].splitlines() if l.strip()),'')
                    parts=[dict(name=normalize_name(n,costs),quantity=q) for n in following[2:].split('/')] if following.startswith('套餐') else []
                    items.append(dict(raw_name=raw,name=normalize_name(raw,costs),quantity=q,parts=parts))
                assert sum(it['quantity'] for it in items)==int(expected[2])
                order_id=re.search(r'单号:\n(\d+)',text)[1]
                order_time=re.search(r'下单时间: ([^\n]+)',text)[1]
                listed=D(re.search(r'预计收入\n预计收入=[^\n]+\n¥([\d.]+)',text)[1])
                base=D(re.search(r'商家优惠后金额\n¥([\d.]+)',text)[1])
                commission=D(re.search(r'技术服务费\(佣金\)\n-¥([\d.]+)',text)[1])
                delivery=D(re.search(r'配送服务费\n-¥([\d.]+)',text)[1])
                assert base-commission-delivery==listed
                head=text.split('展开进度')[0]
            assert order_time.startswith(rec['date'][5:]+' ')
            refunded=any(w in head for w in ['订单已退款','已同意用户退款申请','订单已取消','订单取消','拒绝接单'])
            comp=None
            if refunded and any(w in head for w in ['审核通过','已到账','已赔付']):
                comp=re.search(r'赔付您([\d.]+)元',head) or re.search(r'赔付金额\s*[¥￥]?\s*([\d.]+)\s*元',head)
            income=D(comp[1]) if comp else listed
            expanded=[p for item in items for p in (item['parts'] or [dict(name=item['name'],quantity=item['quantity'])])]
            unknown=[p['name'] for p in expanded if p['name'] not in costs]
            cost=None if unknown else sum(D(costs[p['name']])*p['quantity'] for p in expanded)
            orders.append(dict(store=rec['store'],platform=rec['platform'],date=rec['date'],capture=rec['captured_at'],id=order_id,number=int(text.splitlines()[0]),order_time=order_time,income=str(income),listed_income=str(listed),compensation=str(D(comp[1]) if comp else 0),canceled=refunded and not comp,refunded=refunded,prepared='已出餐' in head,unprepared=('待出餐' in head if mt else '预订单' in head and '已出餐' not in head and '顾客已收餐' not in head),items=items,expanded_items=expanded,cost=None if cost is None else str(cost),unknown_costs=unknown,new_sku_units=sum(p['quantity'] for p in expanded if p['name']=='风味西冷牛排饭')))
    assert len(orders)==rec['total']
    assert len({o['id'] for o in orders})==len(orders)
    return orders


def summarize(orders):
    valid=[o for o in orders if not o['canceled']]
    missing=collections.Counter(n for o in valid for n in o['unknown_costs'])
    income=sum(D(o['income']) for o in valid)
    cost=None if missing else sum(D(o['cost']) for o in valid)
    waste=sum(D(o['cost']) for o in orders if o['canceled'] and o['prepared'] and o['cost'] is not None)
    return dict(total_orders=len(orders),valid_orders=len(valid),income=str(income),cost=None if cost is None else str(cost),profit=None if cost is None else str(income-cost),margin=None if cost is None or not income else float((income-cost)/income),known_waste=str(waste),margin_after_known_waste=None if cost is None or not income else float((income-cost-waste)/income),missing_costs=dict(missing),new_sku_units=sum(o['new_sku_units'] for o in valid if not o['refunded']),new_sku_refunded_units=sum(o['new_sku_units'] for o in orders if o['refunded']),preorders=sum(o['unprepared'] for o in valid))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--snapshots',type=Path,nargs='+',required=True)
    p.add_argument('--chengdu-costs',type=Path,required=True)
    p.add_argument('--beijing-one-costs',type=Path,required=True)
    p.add_argument('--beijing-two-costs',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    versions=[json.loads(path.read_text())['unit_costs'] for path in [a.chengdu_costs,a.beijing_one_costs,a.beijing_two_costs]]
    for v in versions:v['风味西冷牛排饭']='15.5'
    orders=[]
    for path in a.snapshots:
        for line in path.read_text().splitlines():
            rec=json.loads(line)
            index=1 if rec['store'] in ['安贞店','中关村店','清河店'] else 2 if rec['store'] in ['双井店','望京店'] else 0
            orders.extend(parse_record(rec,versions[index]))
    assert len({(o['platform'],o['id']) for o in orders})==len(orders)
    groups=collections.defaultdict(list)
    channels=collections.defaultdict(list)
    for order in orders:
        groups[(order['date'],order['store'])].append(order)
        channels[(order['date'],order['store'],order['platform'])].append(order)
    result=dict(generated_at=dt.datetime.now().isoformat(),unit_cost_versions=versions,stores=[dict(date=d,store=s,**summarize(os)) for (d,s),os in sorted(groups.items())],channels=[dict(date=d,store=s,platform=pl,**summarize(os)) for (d,s,pl),os in sorted(channels.items())],orders=orders)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in result.items() if k not in ['orders','unit_cost_versions']},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
