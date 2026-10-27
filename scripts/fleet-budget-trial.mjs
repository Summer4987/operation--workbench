import {budgetDateContext} from './promo_budget_resolver.mjs';
// Explicit one-day handover requested by the owner. Source names are matched by
// the existing production CDP mapping, never by the editable fleet row label.
export const TRIAL_DATE='2026-10-27';
export const TRIAL_STORES=Object.freeze({
 '朝阳门店':'5650880','银泰城店':'26047144','万象城店':'27259618',
 '金融城店':'29363511','保利中心店':'32022526','安贞店':'28944820',
 '第2号档口利康金桥美食城':'30703865','第5号档口川湘府美食城店':'32346101',
});
export function trialTask(task,date,dinnerBudget,config){
 const id=TRIAL_STORES[task.sourceStore];
 if(!id||task.platform!=='美团')return task;
 if(!config||![1,2].includes(config.schema)||config.budgetMode!=='split')throw Error('八店龙虾统一预算配置尚未同步，禁止设置预算');
 const row=config.stores.find(r=>r.sourceStore===task.sourceStore);
 const selected=config.schema===2?row?.dayTypes?.[budgetDateContext(date,config.calendar).day_type]:row;
 const budget=selected?.dailyBudget;
 const t=config.templates.find(t=>t.id===selected?.templateId);
 if(!row||row.key.split('|')[1]!==id||!t||t.shares.length!==6||t.shares.reduce((a,b)=>a+b,0)!==10000)throw Error('龙虾门店身份或模板无效');
 const unit=config.schema===2?100:1,total=budget/unit;
 if(!Number.isSafeInteger(total)||total<=0)throw Error('单日总预算无效');
 const amounts=t.shares.map(s=>Math.floor(total*s/10000));
 const order=t.shares.map((s,i)=>({i,r:total*s%10000})).sort((a,b)=>b.r-a.r||a.i-b.i);
 for(let i=0,left=total-amounts.reduce((a,b)=>a+b,0);i<left;i++)amounts[order[i].i]++;
 const lunch=amounts.slice(0,3).reduce((a,b)=>a+b,0)*unit,targetBudget=(task.period==='午餐'?lunch:budget)/100;
 if(!Number.isInteger(targetBudget)||targetBudget<=0)throw Error('平台预算须为整元');
 return {...task,targetBudget,longxiaRevision:config.revision,fleetTrialStoreId:id,
  action:task.status==='auto'?`龙虾模板：设置${task.period==='午餐'?'午餐上限':'全天累计上限'} ${targetBudget} 元`:task.action};
}
