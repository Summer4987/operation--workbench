import assert from 'node:assert/strict';
import fs from 'node:fs';
import {trialTask} from '../scripts/fleet-budget-trial.mjs';
const c=JSON.parse(fs.readFileSync(new URL('../config/promo_budget_overrides.json',import.meta.url))).longxia;
for(const date of ['2026-10-27','2026-10-28','2026-10-31'])for(const period of ['午餐','晚餐']){
 const task={sourceStore:'万象城店',platform:'美团',status:'auto',period};
 assert.equal(trialTask(task,date,999,c).targetBudget,period==='午餐'?72:120);
 assert.equal(trialTask({...task,status:'paused'},date,999,c).status,'paused');
 assert.throws(()=>trialTask(task,date,999),/尚未同步/);
}
for(const [date,lunch,daily] of [['2026-10-27',84,120],['2026-10-31',56,80]]){
 const task={sourceStore:'滨江店',platform:'美团',status:'auto'};
 assert.equal(trialTask({...task,period:'午餐'},date,999,c).targetBudget,lunch);
 assert.equal(trialTask({...task,period:'晚餐'},date,999,c).targetBudget,daily);
}
console.log('统一模板预算、持续每日执行及暂停保留通过');
