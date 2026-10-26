// Explicit one-day handover requested by the owner. Source names are matched by
// the existing production CDP mapping, never by the editable fleet row label.
export const TRIAL_DATE='2026-10-27';
export const TRIAL_STORES=Object.freeze({
 '朝阳门店':'5650880','银泰城店':'26047144','万象城店':'27259618',
 '金融城店':'29363511','保利中心店':'32022526','安贞店':'28944820',
 '第2号档口利康金桥美食城':'30703865','第5号档口川湘府美食城店':'32346101',
});
export function trialTask(task,date,dinnerBudget){
 const id=TRIAL_STORES[task.sourceStore];
 if(date!==TRIAL_DATE||!id||task.platform!=='美团'||task.status==='unmatched'||task.status==='platform_unavailable')return task;
 if(!Number.isFinite(dinnerBudget)||dinnerBudget<=0)throw Error('测试全天预算无效：'+task.sourceStore);
 return {...task,targetBudget:dinnerBudget,fleetTrialDate:date,fleetTrialStoreId:id,pauseReason:'',
  status:task.period==='午餐'?'auto':'fleet_trial_skip',
  action:task.period==='午餐'?`龙虾店长测试：上午直接设置全天预算 ${dinnerBudget} 元`:'龙虾店长测试：全天预算上午已设置，跳过晚餐调整'};
}
