const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../workbench.js'), 'utf8').split('// A separate runtime feed keeps hourly dashboard publishing from erasing ROI history.')[1];
const elements = new Map();
for (const id of ['roiDate','roiRange','roiSummary','roiRows','roiRefresh']) elements.set(id, {value:'',innerHTML:'',addEventListener(){}});
const context = vm.createContext({
  document:{getElementById:(id)=>elements.get(id),baseURI:'http://example.test/operation-workbench/'},
  window:{location:{hash:''}}, URL, Date, Number, setInterval(){}, setTimeout(){},
  localDateText:()=> '2026-11-19', text(){},
  escapeHtml:(s)=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;'),
  fetch:async()=>({status:404}),
});
vm.runInContext(source,context);
vm.runInContext('renderPromoRoi()',context); // Empty first-day state must render.
assert.match(elements.get('roiRows').innerHTML,/尚无记录/);
elements.get('roiDate').value='2026-11-19';
elements.get('roiRange').value='7';
vm.runInContext(`roiHistory=[
 {date:'2026-11-19',items:[{store:'<安贞>',status:'ok',spend:200,estimated_income:900,roi:4.5}]},
 {date:'2026-11-13',items:[{store:'中关村',status:'ok',spend:100,estimated_income:200,roi:2}]},
 {date:'2026-11-12',items:[{store:'过期样本',status:'ok',spend:500,estimated_income:5000,roi:10}]},
 {date:'2026-11-18',items:[{store:'缺失',status:'failed',error:'未取得转化率'}]}
]; renderPromoRoi();`, context);
assert.match(elements.get('roiSummary').innerHTML,/3\.67倍/);
assert.match(elements.get('roiRows').innerHTML,/&lt;安贞>/);
assert.doesNotMatch(elements.get('roiRows').innerHTML,/过期样本/);
assert.match(elements.get('roiRows').innerHTML,/采集失败/);
console.log('ROI UI empty state, 7-day boundary, weighted aggregation and escaping passed.');
