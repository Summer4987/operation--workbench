const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../business-report-dashboard/daily_insights.js'), 'utf8');
function render(records, date='2026-10-19') {
  const panel = {innerHTML:''};
  const elements = {'header':{after(){}}, '.focus-panel':{}, '.analysis-panel':{}};
  const document = {createElement:tag=>tag==='section'?panel:{},head:{append(){}},querySelector:s=>elements[s],getElementById:()=>({children:[]})};
  vm.runInNewContext(source,{document,records,targetStores:['A','B'],storeReportFiles:{},dateSelect:{value:date,addEventListener(){}}});
  return panel.innerHTML;
}
const row=(date,store,platform,income)=>({date,store,platform,income,orders:10});
let html=render([row('2026-10-19','A','美团',80),row('2026-10-12','A','美团',100),row('2026-10-12','A','饿了么',500)]);
assert.match(html,/-20.0%/);assert.match(html,/1 项待核实缺报/);assert.doesNotMatch(html,/-86.7%/);
html=render([row('2026-10-19','A','美团',80)]);
assert.match(html,/历史不足，暂不判断下滑/);assert.doesNotMatch(html,/-100.0%/);
html=render([row('2026-10-19','A','美团',80),row('2026-10-12','A','美团',0)]);
assert.match(html,/无可比基准/);assert.doesNotMatch(html,/Infinity|NaN/);
html=render([row('2026-10-19','A','美团',80),row('2026-10-12','A','美团',100),row('2026-10-18','A','美团',90)]);
assert.match(html,/折线断开/);assert.match(html,/2026-10-17：数据不完整/);
console.log('PASS: matching population, missing coverage, absent history, zero baseline and trend gaps');
