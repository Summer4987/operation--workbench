"""One validated configuration for the dashboard and Mac mini. Amounts are cents."""
import hashlib
import json
from pathlib import Path

DEFAULT = json.loads(Path(__file__).with_name('longxia_defaults.json').read_text())

def validate(payload):
    if not isinstance(payload, dict) or payload.get('schema') != 1 or payload.get('budgetMode') != 'split' or payload.get('periods') != DEFAULT['periods']:
        raise ValueError('龙虾模板版本或推广时段无效')
    templates = payload.get('templates')
    if not isinstance(templates, list) or not 1 <= len(templates) <= 30:
        raise ValueError('需要 1–30 个模板')
    clean = {k: DEFAULT[k] for k in ('schema', 'budgetMode', 'periods')}
    clean['templates'] = []
    ids = set()
    for t in templates:
        tid, name, shares = t.get('id'), t.get('name'), t.get('shares')
        if not isinstance(tid, str) or not tid or len(tid)>80 or tid in ids or not isinstance(name,str) or not 1<=len(name.strip())<=40:
            raise ValueError('模板名称或身份无效')
        if not isinstance(shares,list) or len(shares)!=6 or any(type(v) is not int or v<0 for v in shares) or sum(shares)!=10000 or not 0<sum(shares[:3])<10000:
            raise ValueError('六段占比须合计 100%，午餐和晚餐均须大于零')
        low, high = t.get('minBid'), t.get('maxBid')
        if any(type(v) is not int or v%10 for v in (low,high)) or not 10<=low<=high<=10000:
            raise ValueError('出价范围须为 0.10–100 元且按 0.10 元递增')
        ids.add(tid)
        clean['templates'].append(dict(id=tid,name=name.strip(),shares=shares,minBid=low,maxBid=high))
    rows=payload.get('stores')
    if not isinstance(rows,list) or len(rows)!=len(DEFAULT['stores']):
        raise ValueError('八店清单不完整')
    known={r['profileId']:r for r in DEFAULT['stores']}
    clean['stores']=[]
    for row in rows:
        original=known.pop(row.get('profileId'),None)
        if not original or any(row.get(k)!=original[k] for k in ('key','sourceStore','name')):
            raise ValueError('门店平台绑定不可修改')
        budget=row.get('dailyBudget')
        if type(budget) is not int or not 100<=budget<=999900 or budget%100 or row.get('templateId') not in ids:
            raise ValueError('全天预算须为 1–9999 整元，并选择有效模板')
        t=next(t for t in clean['templates'] if t['id']==row['templateId'])
        # Platform budget editor accepts whole yuan. Reject fractional lunch caps.
        amounts=allocate(budget,t['shares'])
        if sum(amounts[:3])%100 or sum(amounts[:3])<100:
            raise ValueError('模板换算的午餐预算须为至少 1 元的整数，请调整全天预算或比例')
        clean['stores'].append({**original,'dailyBudget':budget,'templateId':row['templateId']})
    clean['revision']=hashlib.sha256(json.dumps(clean,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return clean

def allocate(total,shares):
    amounts=[total*s//10000 for s in shares]
    order=sorted(range(6),key=lambda i:(-(total*shares[i]%10000),i))
    for i in order[:total-sum(amounts)]: amounts[i]+=1
    return amounts

def project(data):
    for row in data['longxia']['stores']:
        t=next(t for t in data['longxia']['templates'] if t['id']==row['templateId'])
        lunch=sum(allocate(row['dailyBudget'],t['shares'])[:3])//100
        daily=row['dailyBudget']//100
        data['stores'].setdefault(row['sourceStore'],{})['美团']={
            'lunchBudget':lunch,'dinnerBudget':daily,'weekendLunchBudget':lunch,'weekendDinnerBudget':daily}
    return data
