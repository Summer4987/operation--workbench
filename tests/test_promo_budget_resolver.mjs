import assert from "node:assert/strict";
import fs from "node:fs";
import {
  budgetDateContext,
  buildWeekendPreset,
  resolveBudget,
} from "../scripts/promo_budget_resolver.mjs";

const holidayContext = budgetDateContext("2026-06-19");
assert.equal(holidayContext.day_name, "周五");
assert.equal(holidayContext.day_type, "weekend");
assert.equal(holidayContext.is_china_holiday, true);
assert.equal(holidayContext.china_holiday_name, "端午节");

const adjustedWorkdayContext = budgetDateContext("2026-05-09");
assert.equal(adjustedWorkdayContext.day_name, "周六");
assert.equal(adjustedWorkdayContext.day_type, "weekday");
assert.equal(adjustedWorkdayContext.is_adjusted_workday, true);

const overrides = {
  weekendPreset: { enabled: true, activeDays: [0, 6], lunchMultiplier: 1 },
  stores: {
    "双井店": {
      "美团": {
        lunchBudget: 70,
        weekendLunchBudget: 120,
      },
    },
  },
};
const holidayResolution = resolveBudget({
  overrides,
  platform: "美团",
  storeName: "双井店",
  period: "午餐",
  fallback: 70,
  dateContext: holidayContext,
});
assert.equal(holidayResolution.budget, 120);
assert.equal(holidayResolution.source_type, "day_type");

const preset = buildWeekendPreset(overrides, holidayContext);
assert.equal(preset.enabled, true);
assert.equal(preset.is_active_day, true);

const productionOverrides = JSON.parse(fs.readFileSync("config/promo_budget_overrides.json", "utf8"));
const weekdayDinnerContext = budgetDateContext("2026-06-29");
const baoliMeituanDinner = resolveBudget({
  overrides: productionOverrides,
  platform: "美团",
  storeName: "保利中心店",
  period: "晚餐",
  fallback: 140,
  dateContext: weekdayDinnerContext,
});
assert.equal(baoliMeituanDinner.budget, 140);

console.log("promo budget resolver holiday tests passed");
