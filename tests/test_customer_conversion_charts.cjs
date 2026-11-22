const {test} = require('node:test');
const assert = require('node:assert/strict');
const {rank} = require('../business-report-dashboard/customer_conversion_charts.js');
const metric = 'new_customer_order_conversion';
const row = (store, rate, extra = {}) => ({date:'2026-11-21', platform:'美团', store, [metric]:rate, ...extra});
test('ranks only the selected date and platform; zero stays valid and missing stays last', () => {
  const rows = [row('A',.2), row('B',.7), row('C',0), row('D',null), row('A',.99,{platform:'饿了么'}), row('B',.01,{date:'2026-11-20'})];
  assert.deepEqual(rank(rows,['A','B','C','D','E'],'2026-11-21','美团',metric), [
    {store:'B',rate:.7},{store:'A',rate:.2},{store:'C',rate:0},{store:'D',rate:null},{store:'E',rate:null}
  ]);
  assert.equal(rank(rows,['A'],'2026-11-21','饿了么',metric)[0].rate,.99);
});
test('invalid or ambiguous rates are not silently averaged or converted to zero', () => {
  for (const rate of [undefined, '', NaN, Infinity, -0.1, 1.1]) {
    assert.equal(rank([row('A',rate)],['A'],'2026-11-21','美团',metric)[0].rate,null);
  }
  assert.equal(rank([row('A',.2),row('A',.3)],['A'],'2026-11-21','美团',metric)[0].rate,null);
});
test('old customer metric is independent from new customer metric', () => {
  const rows = [row('A',.1,{old_customer_order_conversion:.8})];
  assert.equal(rank(rows,['A'],'2026-11-21','美团','old_customer_order_conversion')[0].rate,.8);
});
