import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import ExcelJS from 'exceljs';
import {createInbound,readInboundTemplate,matchInboundProduct,inboundDate,parseDirectInbound} from './inbound.mjs';
import {businessReport,comparisonReport,orderReport,orderTotals} from './reports.mjs';
import {Assistant} from './core.mjs';
import {checkOperator,operatorToken,operatorInbound} from './operator.mjs';
import {inboundTemplate} from './inbound.mjs';
import {updateInboundCatalog,catalogFile} from './inbound-catalog.mjs';
const dir=path.dirname(fileURLToPath(import.meta.url));
const template=path.join(dir,'fixtures/inbound-template.xlsx');
const config={WECOM_INBOUND_TEMPLATE:template};
function temp(t){const p=fs.mkdtempSync(path.join(os.tmpdir(),'wecom-features-'));t.after(()=>fs.rmSync(p,{recursive:true,force:true}));return p;}
test('approved Sheet2 replaces the stale catalog and all 22 products generate exact reservations', async t=>{
 const root=temp(t),book=new ExcelJS.Workbook();await book.xlsx.readFile(template);
 const before=fs.readFileSync(template),sheet1=book.getWorksheet('Sheet1').getCell('E2').value;
 const approved=JSON.parse(fs.readFileSync(catalogFile,'utf8'));
 assert.equal(updateInboundCatalog(book).count,22);
 assert.equal(book.getWorksheet('Sheet1').getCell('E2').value,sheet1);
 const refreshed=path.join(root,'refreshed.xlsx');await book.xlsx.writeFile(refreshed);
 const config={WECOM_INBOUND_RUNTIME_TEMPLATE:refreshed};
 const {catalog}=await readInboundTemplate(config);
 assert.equal(catalog.length,22);
 for(const [i,row] of approved.rows.entries()){
  assert.deepEqual(catalog[i],{sku:row[2],name:row[1],spec:row[4],storage:row[3],unit:row[6]});
 }
 const a=new Assistant(config,root,{llm:async()=>{throw Error('AI must not be called');}});
 const raw='明天入库：'+catalog.map((p,i)=>`${p.name} ${i+1}件`).join('，');
 const result=await a.answer(raw,'approved-sheet2');assert.equal(result.artifacts.length,1);
 const output=new ExcelJS.Workbook();await output.xlsx.readFile(result.artifacts[0]);
 for(const [i,p] of catalog.entries()){
  const row=output.getWorksheet('Sheet1').getRow(i+2);
  assert.equal(row.getCell(5).value,p.sku);assert.equal(row.getCell(6).value,p.name);
  assert.equal(row.getCell(7).value,p.spec);assert.equal(row.getCell(8).value,p.storage);
  assert.equal(row.getCell(9).value,i+1);assert.equal(row.getCell(10).value,p.unit);
 }
 assert.equal(matchInboundProduct(catalog,'大米').sku,'CWXXX0005');
 assert.equal(matchInboundProduct(catalog,'燕麦米').sku,'CWXXX0006');
 assert.equal(matchInboundProduct(catalog,'黑米').sku,'CWXXX0007');
 for(const [query,sku,spec] of [
  ['牛肝菌','LDXXX00015','8kg/箱'],['安格斯牛肉丁','LDXXX00016','16kg/箱'],
  ['混合豉油拌饭汁','CWXXX00010','10kg/箱'],['腌辣椒汁','CWXXX00011','10kg/箱']
 ]) {
  const product=matchInboundProduct(catalog,query);
  assert.equal(product.sku,sku);assert.equal(product.spec,spec);assert.equal(product.unit,'件');
 }
 assert.equal(matchInboundProduct(catalog,'拌饭汁').sku,'CWXXX0001');
 assert.throws(()=>matchInboundProduct(catalog,'米'),/过短/);
 assert.throws(()=>matchInboundProduct(catalog,'不存在商品'),/不在模板字典/);
 assert.deepEqual(fs.readFileSync(template),before);
 assert.equal((await readInboundTemplate({WECOM_INBOUND_TEMPLATE:result.artifacts[0]})).catalog.length,22);
});
test('invalid approved catalog leaves the workbook untouched',async()=>{
 const book=new ExcelJS.Workbook();await book.xlsx.readFile(template);
 const before=book.getWorksheet('Sheet2').getCell('B3').value;
 const bad=JSON.parse(fs.readFileSync(catalogFile,'utf8'));bad.rows.push(bad.rows[0]);
 assert.throws(()=>updateInboundCatalog(book,bad),/重复/);
 assert.equal(book.getWorksheet('Sheet2').getCell('B3').value,before);
});
test('inbound creates an independent batch, keeps dictionary and exact numeric quantities',async t=>{
  const before=fs.readFileSync(template),root=temp(t);
  const {file}=await createInbound({items:[{product:'鸡胸',quantity:100,unit:'件'},{product:'鸡腿',quantity:50,unit:'箱'}]},'明天入库：鸡胸100件，鸡腿50箱',config,root,'2026-10-21');
  assert.deepEqual(fs.readFileSync(template),before);
  const b=new ExcelJS.Workbook();await b.xlsx.readFile(file);
  assert.deepEqual(b.worksheets.map(s=>s.name),['Sheet1','Sheet2']);
  assert.equal(b.getWorksheet('Sheet1').getCell('E2').value,'LDXXX0003');
  assert.equal(b.getWorksheet('Sheet1').getCell('I2').value,100);
  assert.equal(b.getWorksheet('Sheet1').getCell('A2').value.toISOString().slice(0,10),'2026-10-22');
  assert.equal(b.getWorksheet('Sheet1').getCell('J3').value,'箱');
  assert.equal(b.getWorksheet('Sheet1').getCell('E4').value,null);
  assert.equal(b.getWorksheet('Sheet2').getCell('B3').value,'熊小小牛排饭-腌制鸡胸（冻）');
  assert.equal(fs.statSync(file).mode&0o777,0o600);
});
test('inbound rejects hallucinated or swapped quantities and ambiguous products',async t=>{
 const root=temp(t),loaded=await readInboundTemplate(config);
 assert.throws(()=>matchInboundProduct([...loaded.catalog,{sku:'OTHER',name:'腌制鸡胸切片'}],'鸡胸'),/多个匹配/);
 await assert.rejects(createInbound({items:[{product:'鸡胸',quantity:200,unit:'件'}]},'鸡胸100件，鸡腿200件',config,root,'2026-10-21'),/无法从同一条原文核对/);
 await assert.rejects(createInbound({items:[{product:'未知商品',quantity:10}]},'未知商品10件',config,root,'2026-10-21'),/不在模板字典/);
 await assert.rejects(createInbound({items:[{product:'鸡胸',quantity:-1}]},'鸡胸-1件',config,root,'2026-10-21'),/正数/);
 await assert.rejects(createInbound({items:[{product:'鸡胸',quantity:100,unit:'件'}]},'鸡胸-100件',config,root,'2026-10-21'),/无法从同一条原文核对/);
 await assert.rejects(createInbound({items:[{product:'鸡胸',quantity:10,unit:'件'}]},'入库鸡胸10kg每箱，鸡腿10件',config,root,'2026-10-21'),/单位与原文不一致/);
 await assert.rejects(createInbound({inbound_date:'2026-11-01',items:[{product:'鸡胸',quantity:10}]},'明天鸡胸10件',config,root,'2026-10-21'),/日期与原文/);
});
test('inbound preserves decimal evidence and uses dictionary units only when omitted',async t=>{
 const r=await createInbound({items:[{product:'鸡胸',quantity:10}]},'入库鸡胸10.0',config,temp(t),'2026-10-21');assert.equal(r.items[0].unit,'件');
 assert.equal(inboundDate('后天入库','2026-12-31'),'2027-01-02');
 const chinese=await createInbound({items:[{product:'鸡胸',quantity:100,unit:'件'}]},'入库鸡胸一百件',config,temp(t),'2026-10-21');assert.equal(chinese.items[0].quantity,100);
 assert.equal(inboundDate('10月23日入库','2026-10-21'),'2026-10-23');
});
test('comparison workbook contains live formulas, original details and missing-value guards',async t=>{
 const file=await comparisonReport({start:'2026-10-20',end:'2026-10-20',previous_start:'2026-10-19',previous_end:'2026-10-19',rows:[{'范围':'直营','门店':'A','本期可比收入':80,'上期可比收入':100,'收入差额':-20,'收入变化率':-.2,'本期可比订单':4,'上期可比订单':5,'订单差额':-1,'订单变化率':-.2}],detail_rows:[]},temp(t));
 const b=new ExcelJS.Workbook();await b.xlsx.readFile(file);const s=b.getWorksheet('经营对比');
 assert.match(s.getCell('E2').formula,/C2-D2/);assert.equal(s.getCell('E2').result,-20);assert.equal(s.getCell('F2').result,-.2);assert.equal(s.getCell('F2').numFmt,'0.0%');assert.equal(b.worksheets[1].name,'原始明细');
});
test('order summaries never combine different units or SKUs',async t=>{
 const rows=[{'门店':'A','SKU':'a','品名':'鸡胸','数量':1,'单位':'件'},{'门店':'A','SKU':'a','品名':'鸡胸','数量':2,'单位':'件'},{'门店':'A','SKU':'a','品名':'鸡胸','数量':5,'单位':'斤'}];
 const totals=orderTotals(rows);assert.equal(totals.length,2);assert.equal(totals.find(r=>r['单位']==='件')['数量'],3);
 const file=await orderReport({start:'2026-10-21',end:'2026-10-21',rows},temp(t));const b=new ExcelJS.Workbook();await b.xlsx.readFile(file);assert.equal(b.worksheets[0].name,'订货汇总');assert.equal(b.getWorksheet('订货明细').rowCount,4);
});
test('AI inbound tool returns a real template attachment and blocks a generic replacement',async t=>{
 const a=new Assistant(config,temp(t));const artifacts=[];
 const r=await a.tool('create_inbound_reservation',{items:[{product:'鸡胸',quantity:100,unit:'件'}]},artifacts,undefined,{rawText:'入库鸡胸100件'});
 assert.equal(r.file_created,true);assert.equal(artifacts.length,1);assert.equal(r.file,undefined);
 await assert.rejects(a.tool('create_spreadsheet',{title:'入库',columns:['品名'],rows:[['鸡胸']]},[],undefined,{rawText:'入库鸡胸100件'}),/必须调用/);
});
test('the failed user request creates the exact reservation without calling an AI service',async t=>{
 let called=false;const root=temp(t);
 const a=new Assistant(config,root,{llm:async()=>{called=true;throw Error('AI must not be called');}});
 const r=await a.answer('预约明天入库拌饭汁24件，发表格给我','real-user-regression');
 assert.equal(called,false);assert.equal(r.artifacts.length,1);
 const b=new ExcelJS.Workbook();await b.xlsx.readFile(r.artifacts[0]);const s=b.getWorksheet('Sheet1');
 assert.equal(s.getCell('E2').value,'CWXXX0001');assert.equal(s.getCell('I2').value,24);assert.equal(s.getCell('H2').value,'常温');
 assert.match(r.text,/24件/);
});
test('direct parsing supports multi-line and Chinese quantities but skips cancellation',async()=>{
 const {catalog}=await readInboundTemplate(config);
 const r=parseDirectInbound('明天入库：鸡胸一百件，鸡腿50件。生成表格给我',catalog,'2026-10-21');
 assert.equal(r.items.length,2);assert.equal(r.items[0].quantity,100);assert.equal(r.inbound_date,'2026-10-22');
 assert.equal(parseDirectInbound('不要入库拌饭汁24件',catalog,'2026-10-21'),null);
});
test('the reported next-Monday request creates a reservation with the correct date and both SKUs',async t=>{
 const root=temp(t),book=new ExcelJS.Workbook();
 await book.xlsx.readFile(template);
 updateInboundCatalog(book);
 const refreshed=path.join(root,'refreshed.xlsx');
 await book.xlsx.writeFile(refreshed);
 const config={WECOM_INBOUND_RUNTIME_TEMPLATE:refreshed};
 const {catalog}=await readInboundTemplate(config);
 const raw='预约下周一入库：牛五花牛排20件，安格斯牛肉丁10件，给我Excel文件';
 const direct=parseDirectInbound(raw,catalog,'2026-11-27');
 assert.deepEqual(direct,{inbound_date:'2026-11-30',items:[
  {product:'LDXXX0001',quantity:20,unit:'件'},
  {product:'LDXXX00016',quantity:10,unit:'件'},
 ]});
 const {file}=await createInbound(direct,raw,config,root,'2026-11-27');
 await book.xlsx.readFile(file);
 const sheet=book.getWorksheet('Sheet1');
 for(const [row,sku,quantity] of [[2,'LDXXX0001',20],[3,'LDXXX00016',10]]){
  assert.equal(sheet.getCell('A'+row).value.toISOString(),'2026-11-30T00:00:00.000Z');
  assert.equal(sheet.getCell('E'+row).value,sku);
  assert.equal(sheet.getCell('I'+row).value,quantity);
  assert.equal(sheet.getCell('J'+row).value,'件');
 }
 assert.equal(sheet.getCell('E4').value,null);
});
test('weekly dates follow Monday-based weeks and reject conflicting dates',()=>{
 assert.equal(inboundDate('下周一入库','2026-11-29'),'2026-11-30');
 assert.equal(inboundDate('下星期一入库','2026-11-30'),'2026-12-07');
 assert.equal(inboundDate('本周日入库','2026-12-31'),'2027-01-03');
 assert.equal(inboundDate('下周一，2026-11-30入库','2026-11-27'),'2026-11-30');
 assert.throws(()=>inboundDate('下周一和12月1日入库','2026-11-27'),/入库日期有多批/);
});
test('a generated attachment survives a later model timeout',async t=>{
 let calls=0;const a=new Assistant({},temp(t),{llm:async()=>{
  if(calls++)return new Promise(()=>{});
  return {role:'assistant',tool_calls:[{id:'file',function:{name:'create_spreadsheet',arguments:JSON.stringify({title:'测试',columns:['状态'],rows:[['已核对']]})}}]};
 }});
 const r=await a.answer('生成一个测试表格','timeout-after-file',{timeoutMs:100});
 assert.equal(r.artifacts.length,1);assert.match(r.text,/表格已生成/);assert.equal(fs.existsSync(r.artifacts[0]),true);
});
test('the latest failed request uses the runtime template without calling AI',async t=>{
 const a=new Assistant({WECOM_INBOUND_RUNTIME_TEMPLATE:template,WECOM_INBOUND_TEMPLATE:'/unreadable/Desktop/template.xlsx'},temp(t),{llm:async()=>{throw Error('AI must not be called');}});
 const result=await a.answer('预约后天入库牛五花牛排34件','latest-request');
 assert.equal(result.artifacts.length,1);const b=new ExcelJS.Workbook();await b.xlsx.readFile(result.artifacts[0]);
 assert.equal(b.getWorksheet('Sheet1').getCell('E2').value,'LDXXX0001');assert.equal(b.getWorksheet('Sheet1').getCell('I2').value,34);
 assert.equal(inboundTemplate({WECOM_INBOUND_RUNTIME_TEMPLATE:template,WECOM_INBOUND_TEMPLATE:'/Desktop'}),template);
});
test('operator token is private and exact bearer authentication is required',t=>{
 const root=temp(t),token=operatorToken(root);assert.equal(fs.statSync(path.join(root,'operator-token')).mode&0o777,0o600);
 assert.equal(checkOperator('',token),false);assert.equal(checkOperator('Bearer wrong',token),false);assert.equal(checkOperator('Bearer '+token,token),true);
});
test('live-process recovery only sends to paired owner and does not resend acknowledged files',async t=>{
 const root=temp(t);fs.mkdirSync(path.join(root,'outbox'));const file=path.join(root,'outbox','reservation.xlsx');fs.copyFileSync(template,file);
 const sent=[];const context={root,owner:'paired-owner',assistant:{answer:async()=>({text:'已生成',artifacts:[file]})},client:{uploadMedia:async()=>({media_id:'test-media'}),sendMessage:async(owner,body)=>{sent.push({owner,body});}}};
 const result=await operatorInbound({text:'预约后天入库牛五花牛排34件',send:true,recipient:'someone-else'},context);
 assert.equal(result.file_delivered,true);assert.equal(sent.length,2);assert.ok(sent.every(s=>s.owner==='paired-owner'));
 assert.equal((await operatorInbound({text:'预约后天入库牛五花牛排34件',send:true},context)).already_delivered,true);assert.equal(sent.length,2);
});

test('realtime sales correction bypasses polluted history, model and supply orders',async t=>{
 const root=temp(t),calls=[];
 const payload={generated_at:'2026-10-21 20:01:00',store_count:1,platform_store_count:2,available_stores:['中关村'],
   rows:[{'门店':'中关村','平台':'美团','订单数':142},{'门店':'中关村','平台':'饿了么','订单数':206}],
   store_totals:[{'门店':'中关村','订单数':348}],totals:{'订单数':348},errors:[],missing_order_rows:0};
 const a=new Assistant({},root,{llm:()=>{throw Error('must not call model');},bridge:async args=>{calls.push(args);return structuredClone(payload);}});
 const r=await a.answer('加盟店的订单量，你要查实时单量，不是查订货量','sales-correction');
 assert.equal(calls.length,1);assert.equal(calls[0].kind,'realtime');
 assert.match(r.text,/销售订单合计：348单/);assert.match(r.text,/20:01:00/);assert.match(r.text,/美团142单，饿了么206单/);
 const direct=await a.answer('直营门店实时单量','direct');assert.match(direct.text,/尚未接入/);assert.equal(calls.length,1);
});

test('realtime tool exists for model questions and stale snapshots are clearly marked',async t=>{
 const {TOOLS}=await import('./core.mjs');const {isRealtimeRequest,realtimeReply}=await import('./realtime.mjs');
 assert(TOOLS.some(t=>t.function.name==='query_realtime'));
 assert(isRealtimeRequest('今日加盟店订单量'));assert(!isRealtimeRequest('今天成都订货量'));assert(!isRealtimeRequest('昨天加盟店订单量'));
 const s=realtimeReply({generated_at:'2026-10-20 20:00:00',stale:true,reset:false,store_count:1,platform_store_count:2,missing_order_rows:1,totals:{'订单数':4},store_totals:[],errors:['快照已过期']});
 assert.match(s,/已过期/);assert.match(s,/仅已采集部分/);assert.match(s,/不触发平台刷新/);
 const reset=realtimeReply({reset:true,totals:{'订单数':null}});assert.match(reset,/尚未就绪/);assert.match(reset,/合计：缺失/);
});

test('realtime filters requested store/platform and refuses unverified city mapping',async t=>{
 const a=new Assistant({},temp(t),{llm:()=>{throw Error('no model');},bridge:async()=>({generated_at:'2026-10-21 20:01:00',available_stores:['中关村','清河'],store_count:2,platform_store_count:4,
 rows:[{'门店':'中关村','平台':'美团','订单数':3,'收入':12},{'门店':'中关村','平台':'饿了么','订单数':4,'收入':16},{'门店':'清河','平台':'美团','订单数':8,'收入':32},{'门店':'清河','平台':'饿了么','订单数':9,'收入':36}],
 store_totals:[{'门店':'中关村','订单数':7},{'门店':'清河','订单数':17}],totals:{'订单数':24,'收入':96},errors:[]})});
 const r=await a.answer('查中关村美团实时单量','filter');assert.match(r.text,/合计：3单/);assert.doesNotMatch(r.text,/饿了么|清河/);assert.match(r.text,/12.00元/);
 const city=await a.answer('成都加盟店实时单量','city');assert.match(city.text,/请指定门店/);assert.doesNotMatch(city.text,/合计/);
});
