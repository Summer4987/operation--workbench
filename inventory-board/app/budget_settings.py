"""All-store template selections; existing daily totals are immutable."""
import copy
import hashlib
import json
from pathlib import Path

BASELINE=json.loads(Path(__file__).with_name('budget_totals_baseline.json').read_text())

def amounts(budget,shares):
    total=budget//100
    values=[total*s//10000 for s in shares]
    order=sorted(range(6),key=lambda i:(-(total*shares[i]%10000),i))
    for i in order[:total-sum(values)]:values[i]+=1
    return [v*100 for v in values]

def validate(payload,longxia):
    templates={t['id']:t for t in longxia['templates']}
    bound={r['sourceStore']:r for r in longxia['stores']}
    if payload is None:
        entries=[]
        for original in BASELINE['stores']:
            row=copy.deepcopy(original)
            for platform,days in row['platforms'].items():
                for day,value in days.items():
                    managed=bound.get(row['sourceStore']) if platform=='美团' else None
                    value['templateId']=(managed.get('dayTypes',{}).get(day,{}).get('templateId') or managed['templateId']) if managed else None
            entries.append(row)
        return validate({'schema':1,'entries':entries},longxia)
    if not isinstance(payload,dict) or payload.get('schema')!=1 or not isinstance(payload.get('entries'),list) or len(payload['entries'])!=len(BASELINE['stores']):raise ValueError('需要完整的全部门店预算清单')
    known={r['sourceStore']:r for r in BASELINE['stores']};clean=[]
    for row in payload['entries']:
        base=known.pop(row.get('sourceStore'),None)
        if not base or row.get('name')!=base['name'] or set(row.get('platforms',{}))!={'美团','饿了么'}:raise ValueError('门店或平台清单无效')
        item=copy.deepcopy(base)
        for platform,days in row['platforms'].items():
            if set(days)!={'weekday','weekend'}:raise ValueError('需要工作日与周末及节假日两档')
            for day,value in days.items():
                if value.get('dailyBudget')!=base['platforms'][platform][day]['dailyBudget']:raise ValueError('单日总预算已锁定，选择模板不会修改原金额')
                tid=value.get('templateId')
                if tid is not None and tid not in templates:raise ValueError('请选择有效的分时模板')
                if platform=='美团' and row['sourceStore'] in bound and not tid:raise ValueError('已接入龙虾的门店需要分时模板')
                if tid:
                    a=amounts(value['dailyBudget'],templates[tid]['shares'])
                    if not 0<sum(a[:3])<value['dailyBudget']:raise ValueError('模板需为午餐和晚餐分别保留预算')
                item['platforms'][platform][day]['templateId']=tid
        clean.append(item)
    result={'schema':1,'entries':clean}
    result['revision']=hashlib.sha256(json.dumps(result,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return result

def project(data):
    config=data['longxia'];templates={t['id']:t for t in config['templates']}
    entries={r['sourceStore']:r for r in data['budgetSettings']['entries']}
    for source,row in entries.items():
        target=data['stores'].setdefault(source,{})
        for platform,days in row['platforms'].items():
            result={}
            for day,v in days.items():
                lunch=sum(amounts(v['dailyBudget'],templates[v['templateId']]['shares'])[:3]) if v.get('templateId') else v['lunchBudget']
                prefix='' if day=='weekday' else 'weekend'
                result['lunchBudget' if not prefix else 'weekendLunchBudget']=lunch//100
                result['dinnerBudget' if not prefix else 'weekendDinnerBudget']=v['dailyBudget']//100
            target[platform]=result
    config.update(schema=2,rounding='yuan',budgetSettingsRevision=data['budgetSettings']['revision'],calendar={k:{**v,**data.get(k,{})} for k,v in BASELINE['calendar'].items()})
    for row in config['stores']:
        days=entries[row['sourceStore']]['platforms']['美团']
        row['dayTypes']={day:{'dailyBudget':v['dailyBudget'],'templateId':v['templateId']} for day,v in days.items()}
        row.update(dailyBudget=days['weekday']['dailyBudget'],templateId=days['weekday']['templateId'])
    config.pop('revision',None)
    config['revision']=hashlib.sha256(json.dumps(config,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return data
