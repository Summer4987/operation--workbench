import test from 'node:test';
import assert from 'node:assert/strict';
import {TRIAL_DATE,TRIAL_STORES,trialTask} from './fleet-budget-trial.mjs';
test('only 8 exact stores on the authorized day; normal budgets resume next day',()=>{
 assert.equal(Object.keys(TRIAL_STORES).length,8);
 for(const sourceStore of Object.keys(TRIAL_STORES))for(const period of ['午餐','晚餐']){
  const t={platform:'美团',sourceStore,period,targetBudget:60,status:'auto'};
  const r=trialTask(t,TRIAL_DATE,150);assert.equal(r.targetBudget,150);assert.equal(r.status,period==='午餐'?'auto':'fleet_trial_skip');
  assert.equal(trialTask(t,'2026-10-28',150),t);
 }
 const t={platform:'美团',sourceStore:'金融街店',period:'午餐',status:'auto'};
 assert.equal(trialTask(t,TRIAL_DATE,150),t);
 assert.equal(trialTask({...t,platform:'饿了么',sourceStore:'万象城店'},TRIAL_DATE,150).fleetTrialDate,undefined);
 const paused={...t,sourceStore:'万象城店',status:'paused'};assert.equal(trialTask(paused,TRIAL_DATE,120).status,'auto');
});
