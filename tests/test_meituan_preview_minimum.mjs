import assert from 'node:assert/strict';
import fs from 'node:fs';
const source=fs.readFileSync(new URL('../scripts/build_promo_budget_preview.mjs',import.meta.url),'utf8');
assert.match(source,/requestedTargetBudget/);
assert.match(source,/targetBudget:\s*50/);
assert.match(source,/平台最低 ¥50/);
console.log('美团预览将低于 ¥50 的单次预算提升至 ¥50');
