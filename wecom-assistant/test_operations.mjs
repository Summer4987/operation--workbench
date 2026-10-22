import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {isOperationsRequest,requestDate,loadOperations,operationsReply,OperationsNotifier} from './operations.mjs';
function fixture(t){const root=fs.mkdtempSync(path.join(os.tmpdir(),'ops-test-'));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));return root;}
function save(file,value){fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file,JSON.stringify(value));}
const now=()=>new Date('2026-10-22T02:00:00Z');
const failure={id:'ops.morning_collection',name:'上午运营',status:'failed',step:'汇总',message:'客服消息采集失败',details:['万象城店|美团：视频采集失败'],updated_at:'2026-10-22 08:41:10'};
test('Chinese operations queries and Beijing dates do not route business revenue to operations',()=>{
 assert(isOperationsRequest('今天运营哪里失败了'));assert(isOperationsRequest('运营恢复了吗'));assert(isOperationsRequest('哪个平台采集异常'));assert(!isOperationsRequest('昨天收入下滑最多门店'));
 assert.equal(requestDate('今天运营',new Date('2026-10-21T23:00Z')),'2026-10-22');assert.equal(requestDate('昨天运营',now()),'2026-10-21');assert.equal(requestDate('2026-10-19任务状态',now()),'2026-10-19');
});
test('reads current production ledger, safe store/platform failure details, historical dates and missing records',t=>{
 const root=fixture(t),config={WECOM_DATA_ROOTS:JSON.stringify([root])};
 save(path.join(root,'outputs/task_runs/latest.json'),{generated_at:'2026-10-22 09:00:00',tasks:{'ops.morning_collection':{status:'failed',message:'失败 /Users/owner/private.log token=secret',updated_at:'2026-10-22 08:41:10',extra:{failure_details:JSON.stringify([{name:'客服采集',output_tail:'万象城店|美团: partial https://example.org/?secret=x'}])}},'growth.promo_budget':{status:'success',updated_at:'2026-10-21 08:30:00'}},events:[{task_id:'growth.promo_budget',status:'success',message:'预算成功',created_at:'2026-10-21 08:30:00'}]});
 const report=loadOperations(config,'2026-10-22'),reply=operationsReply(report,'哪里失败');
 assert.equal(report.tasks.length,1);assert.match(reply,/万象城店\|美团/);assert.match(reply,/尚无记录/);assert.doesNotMatch(reply,/owner|token=secret|example.org/);
 assert.equal(loadOperations(config,'2026-10-21').tasks[0].status,'success');assert.match(operationsReply(loadOperations({WECOM_DATA_ROOTS:'["/nonexistent"]'})),/不能判断/);
});
test('newer morning reconciliation overrides generic wrapper failure while old details do not hide it',t=>{
 const root=fixture(t),config={WECOM_DATA_ROOTS:JSON.stringify([root])};
 save(path.join(root,'outputs/task_runs/latest.json'),{tasks:{'ops.morning_collection':{status:'failed',updated_at:'2026-10-22 08:41:10'}}});
 save(path.join(root,'outputs/morning_collection_status/latest.json'),{status:'success',task_message:'视频按新规则完成复核',updated_at:'2026-10-22 10:00:00',failed_steps:[]});
 assert.equal(loadOperations(config,'2026-10-22').tasks[0].status,'success');
 save(path.join(root,'outputs/morning_collection_status/latest.json'),{status:'success',updated_at:'2026-10-21 10:00:00'});
 assert.equal(loadOperations(config,'2026-10-22').tasks[0].status,'failed');
});
test('alerts deduplicate across polling, changing run timestamp and process restart; recover once',async t=>{
 const root=fixture(t),sent=[];let rows=[{...failure}];
 const deps={stateFile:path.join(root,'state.json'),readReport:()=>({tasks:rows}),send:async text=>sent.push(text),save,now};
 let n=new OperationsNotifier(deps);assert.equal((await n.tick()).sent,1);assert.equal((await n.tick()).sent,0);
 rows=[{...failure,updated_at:'2026-10-22 09:00:00'}];n=new OperationsNotifier(deps);assert.equal((await n.tick()).sent,0);
 rows=[{...failure,status:'success',message:'已恢复',details:[]}];assert.equal((await n.tick()).sent,1);await n.tick();assert.equal(sent.length,2);assert.match(sent[1],/运营恢复/);
});
test('failed send retries without marking delivered; startup successes stay silent; text is byte limited',async t=>{
 const root=fixture(t);let fail=true,rows=[{...failure,details:['长'.repeat(4000)]}],sent=[];
 const n=new OperationsNotifier({stateFile:path.join(root,'state.json'),readReport:()=>({tasks:rows}),send:async text=>{if(fail)throw Error('offline');sent.push(text);},save,now});
 assert((await n.tick()).error);assert(!fs.existsSync(n.stateFile));fail=false;assert.equal((await n.tick()).sent,1);assert(Buffer.byteLength(sent[0])<=3800);
 rows=[{...failure,id:'growth.promo_budget',status:'success'}];assert.equal((await n.tick()).sent,0);
});
test('overlapping ticks do not double send and missing sources never produce recovery',async t=>{
 let release,rows=[failure],count=0;const root=fixture(t);
 const n=new OperationsNotifier({stateFile:path.join(root,'state.json'),readReport:()=>({tasks:rows}),send:()=>{count++;return new Promise(r=>release=r);},save,now});
 const running=n.tick();assert((await n.tick()).busy);release();await running;assert.equal(count,1);
 n.readReport=()=>({error:'unavailable'});assert((await n.tick()).error);assert(n.state.tasks[failure.id].active);
});

test('Assistant routes operations without model and exposes a read-only tool',async t=>{
 const {Assistant,TOOLS}=await import('./core.mjs');const root=fixture(t);
 save(path.join(root,'outputs/task_runs/latest.json'),{tasks:{'ops.morning_collection':{status:'failed',message:'万象城店美团客服采集失败',updated_at:new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai'}).format(new Date())+' 08:40:00'}}});
 const a=new Assistant({WECOM_DATA_ROOTS:JSON.stringify([root])},path.join(root,'private'),{llm:()=>{throw Error('must not call model');}});
 assert(TOOLS.some(t=>t.function.name==='query_operations'));
 assert.match((await a.answer('今天运营哪里失败了','test')).text,/万象城店美团/);
 assert.equal((await a.tool('query_operations',{},[],new AbortController().signal)).tasks[0].status,'failed');
});
test('operator test uses only bound owner, fixed validation message and real data',async t=>{
 const {operatorOperations}=await import('./operator.mjs');const root=fixture(t),sent=[];
 save(path.join(root,'outputs/task_runs/latest.json'),{tasks:{}});
 const deps={assistant:{config:{WECOM_DATA_ROOTS:JSON.stringify([root])}},client:{sendMessage:async(...args)=>sent.push(args)},owner:'bound-owner'};
 const preview=await operatorOperations({send:false},deps);assert(!preview.delivered);assert.equal(sent.length,0);
 const result=await operatorOperations({send:true,owner:'other',text:'arbitrary'},deps);assert(result.delivered);assert.equal(sent[0][0],'bound-owner');assert.doesNotMatch(JSON.stringify(sent),/arbitrary/);
});
