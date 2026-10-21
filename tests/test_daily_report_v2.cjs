const {test} = require('node:test');
const assert = require('node:assert/strict');
const {analyze, compare, aggregate} = require('../business-report-dashboard/daily_report_v2.js');
const row = (date, income, extra={}) => ({date, store:'A', platform:'美团', income, orders:100, impressions:1000, visit_conversion:.1, order_conversion:.3,...extra});
const review = (a,b,c) => analyze([row('2026-10-20',a),row('2026-10-19',b),row('2026-10-13',c)],['A'],'2026-10-20')[0];
test('10% threshold includes positive and negative boundary',()=>{
  assert.equal(review(110,100,100).status,'up');
  assert.equal(review(90,100,100).status,'down');
  assert.equal(review(99,100,100).status,'stable');
});
test('four-week baseline cannot trigger a single-day alert',()=>{
  const r=analyze([row('2026-10-20',100),row('2026-10-19',100),row('2026-10-13',100),row('2026-10-06',10),row('2026-09-29',10),row('2026-09-22',10)],['A'],'2026-10-20')[0];
  assert.equal(r.status,'stable');
});
test('opposite comparison directions stay explicit',()=>assert.equal(review(100,120,80).status,'mixed'));
test('a missing calendar day never falls back to an older available day',()=>{
  const all=[row('2026-10-20',100),row('2026-10-18',50),row('2026-10-13',100)];
  const r=analyze(all,['A'],'2026-10-20')[0];
  assert.equal(r.comparisons[0].changes.income,null);
  assert.equal(r.status,'unknown');
});
test('same platform is paired within the same store',()=>{
  const c=compare([row('2026-10-20',100),row('2026-10-19',200,{store:'B'}),row('2026-10-19',500,{platform:'饿了么'})],'2026-10-20','2026-10-19','A');
  assert.equal(c.count,0); assert.equal(c.changes.income,null);
});
test('missing platform is not an income collapse',()=>{
  const all=[row('2026-10-20',100),row('2026-10-19',100),row('2026-10-13',100),row('2026-10-19',300,{platform:'饿了么'})];
  const r=analyze(all,['A'],'2026-10-20')[0];
  assert.equal(r.status,'pending'); assert.deepEqual(r.missing,['饿了么']);
  assert.equal(r.comparisons[0].changes.income,0);
  assert.equal(r.comparisons[0].complete,false);
});
test('zero baseline does not produce infinity or a stable label',()=>{
  assert.equal(review(100,0,0).status,'unknown');
  assert.equal(review(100,0,0).comparisons[0].changes.income,null);
});
test('a true current-day zero is a decline',()=>assert.equal(review(0,100,100).status,'down'));
test('missing current record remains unknown rather than zero',()=>{
  const r=analyze([row('2026-10-19',100)],['A'],'2026-10-20')[0];
  assert.equal(r.current.income,null); assert.equal(r.status,'pending');
});
test('conversion change is relative 10%, with a separate one-point difference',()=>{
  const r=analyze([row('2026-10-20',100,{visit_conversion:.09}),row('2026-10-19',100),row('2026-10-13',100)],['A'],'2026-10-20')[0];
  const s=r.signals.find(s=>s.key==='visit_conversion');
  assert.ok(Math.abs(s.change+.1)<1e-10); assert.ok(Math.abs(s.point+.01)<1e-10);
});
test('conversion aggregation uses funnel denominators',()=>{
  const a=aggregate([row('2026-10-20',100,{impressions:100,visit_conversion:.1,order_conversion:.2}),row('2026-10-20',100,{platform:'饿了么',impressions:900,visit_conversion:.2,order_conversion:.5})]);
  assert.equal(a.visit_conversion,.19);
  assert.ok(Math.abs(a.order_conversion-92/190)<1e-10);
});
test('missing conversion fields are not treated as zero',()=>{
  assert.equal(aggregate([row('2026-10-20',100,{order_conversion:null})]).order_conversion,null);
});
