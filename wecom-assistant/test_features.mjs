import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import ExcelJS from 'exceljs';
import {createInbound,readInboundTemplate,matchInboundProduct,inboundDate} from './inbound.mjs';
import {businessReport,comparisonReport,orderReport,orderTotals} from './reports.mjs';
import {Assistant} from './core.mjs';
const dir=path.dirname(fileURLToPath(import.meta.url));
const template=path.join(dir,'fixtures/inbound-template.xlsx');
const config={WECOM_INBOUND_TEMPLATE:template};
function temp(t){const p=fs.mkdtempSync(path.join(os.tmpdir(),'wecom-features-'));t.after(()=>fs.rmSync(p,{recursive:true,force:true}));return p;}
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
