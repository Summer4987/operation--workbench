import assert from 'node:assert/strict';
import fs from 'node:fs';
import { budgetDateContext, buildWeekendPreset, resolveBudget, applyWeekendPresetIfNeeded } from '../scripts/promo_budget_resolver.mjs';
const overrides = JSON.parse(fs.readFileSync(new URL('../config/promo_budget_overrides.json', import.meta.url)));
let count = 0;
for (const date of ['2026-09-24', '2026-09-25', '2026-09-26', '2026-09-27', '2026-09-28', '2027-09-25']) {
  const dateContext = budgetDateContext(date);
  const preset = buildWeekendPreset(overrides, dateContext);
  const active = date >= '2026-09-25' && date <= '2026-09-27';
  assert.equal(Boolean(preset.temporary_adjustment), active);
  for (const [storeName, platforms] of Object.entries(overrides.stores)) {
    for (const platform of Object.keys(platforms)) {
      for (const period of ['午餐', '晚餐']) {
        const resolution = resolveBudget({ overrides, storeName, platform, period, fallback: 100, dateContext });
        assert.equal(applyWeekendPresetIfNeeded(resolution.budget, period, resolution, preset), active ? Math.round(resolution.budget * .7) : resolution.budget);
        count++;
      }
    }
  }
}
const preset = buildWeekendPreset({weekendPreset: {enabled:true, lunchMultiplier:.8}}, budgetDateContext('2026-09-25'));
assert.equal(applyWeekendPresetIfNeeded(100, '午餐', {source_type:'default'}, preset), 56);
assert.equal(applyWeekendPresetIfNeeded(100, '午餐', {source_type:'day'}, preset), 70);
console.log(`Passed ${count} store/platform/period/date checks and preset composition checks`);
