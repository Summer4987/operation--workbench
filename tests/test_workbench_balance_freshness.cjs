const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('workbench.js', 'utf8');
function extract(name) {
  const start = source.indexOf(`function ${name}(`);
  const end = source.indexOf('\nfunction ', start + 1);
  return source.slice(start, end);
}
let now = Date.parse('2026-11-22T12:00:00+08:00');
class Clock extends Date { static now() { return now; } }
const output = {};
const context = vm.createContext({ Date: Clock, Number, String, data: {},
  text: (id, value) => { output[id] = value; }, html: (id, value) => { output[id] = value; },
  cls: () => {}, document: { querySelector: () => ({classList: {toggle: () => {}}}) },
});
vm.runInContext(['timestampValue', 'freshPromoBalanceStatus', 'countPromoBalanceAbnormal', 'renderBalances'].map(extract).join('\n'), context);
const balances = {generated_at: '2026-11-22 11:30:00', items: []};
const status = {source_generated_at: balances.generated_at, generated_at: balances.generated_at,
  summary: {freshness_window_minutes: 90, low_balance_count: 0}};
assert.equal(context.freshPromoBalanceStatus(balances, status).summary.source_is_stale, false);
context.priorityDetailList = (items, format, empty) => items.length ? items.map(format).join(';') : empty;
context.balanceValue = item => item.balance;
context.shortStore = name => name;
context.yuan = value => `¥${value}`;
context.escapeHtml = value => String(value).replaceAll('<', '&lt;');
context.balanceDisplay = item => `¥${item.balance}`;
context.rows = (id, items, render) => { output[id] = items.map(render).join(''); };
assert.equal(context.countPromoBalanceAbnormal(balances, status, 200).count, 0);
const lowStatus = {...status, summary: {low_balance_count: 1}, low_balance_items: [{platform: '美团', store_name: '双井店', balance: 40}]};
assert.equal(context.countPromoBalanceAbnormal(balances, lowStatus, 200).count, 1);
// A daily collection stays visible after 90 minutes, with its capture time.
now += 91 * 60000;
const expired = context.freshPromoBalanceStatus(balances, status);
assert.equal(expired.summary.source_is_stale, false);
assert.equal(expired.summary.source_is_realtime_stale, true);
context.data = {balances, promo_balance_status: lowStatus};
context.renderBalances();
assert.equal(output.balanceStatus, '今日巡检已采集');
assert.match(output.balanceRows, /双井店/);
assert.match(output.balanceSummary, /11:30:00/);
assert.match(output.balanceSummary, /不代表实时余额/);
// Beijing midnight expires the daily result even in a page left open. Keep history.
now = Date.parse('2026-11-22T23:59:59+08:00');
assert.equal(context.freshPromoBalanceStatus(balances, status).summary.source_is_stale, false);
now += 1000;
assert.equal(context.freshPromoBalanceStatus(balances, status).status, 'stale');
assert.equal(context.countPromoBalanceAbnormal(balances, context.freshPromoBalanceStatus(balances, status), 200).pending, true);
context.data = {balances: {...balances, items: [{platform: '美团', store_name: '双井店', balance: 40}]}, promo_balance_status: status};
context.renderBalances();
assert.equal(output.balanceStatus, '待复查');
assert.equal(output.metricWarnings, '待复查');
assert.match(output.balanceRows, /当前低余额情况未知/);
assert.match(output.balanceRows, /双井店/);
assert.match(output.balanceRows, /历史采集值/);
assert.match(output.balanceSummary, /11:30:00/);
assert.equal(context.freshPromoBalanceStatus({}, {}).status, 'missing');
// A newly collected source supersedes an older stale status.
now = Date.parse('2026-11-23T10:00:00+08:00');
assert.equal(context.freshPromoBalanceStatus({generated_at: '2026-11-23 08:00:00'}, expired).summary.source_is_stale, false);
assert.equal(context.freshPromoBalanceStatus({generated_at: '2026-11-24 08:00:00'}, {}).status, 'missing');
console.log('Daily balance display, Beijing midnight and historical rendering checks passed');
