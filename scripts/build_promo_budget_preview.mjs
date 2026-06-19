import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";
import {
  applyWeekendPresetIfNeeded,
  budgetDateContext,
  buildWeekendPreset,
  canonicalStoreName,
  resolveBudget,
} from "./promo_budget_resolver.mjs";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, "..");
const rulesPath = path.join(repoRoot, "dianjin-prototype/rules.js");
const logicPath = path.join(repoRoot, "dianjin-prototype/logic.js");
const outputDir = path.join(repoRoot, "outputs/promo_budget_preview");
const jsonPath = path.join(outputDir, "latest.json");
const jsPath = path.join(outputDir, "latest-data.js");
const overridesPath = path.join(repoRoot, "config/promo_budget_overrides.json");

function loadRuntime() {
  const context = { window: {} };
  vm.runInNewContext(globalThis.__files.rules, context);
  vm.runInNewContext(globalThis.__files.logic, context);
  return {
    rules: context.window.DIANJIN_RULES,
    logic: context.window.DIANJIN_LOGIC,
  };
}

function matchMeituanName(storeName) {
  const map = {
    "第2号档口利康金桥美食城": "熊小小牛排饭POKEBEAR（第3档口吉祥美食城店）",
    "第5号档口川湘府美食城店": "熊小小牛排饭POKEBEAR(第5号档口川湘府美食城店)",
    "金融街店": "熊小小牛排饭POKEBEAR（金融街店）",
    "丽泽店": "熊小小牛排饭POKEBEAR（丽泽门店）",
    "光谷店": "熊小小牛排饭POKEBEAR（光谷店）",
    "双井店": "熊小小牛排饭POKEBEAR（双井店）",
    "保利中心店": "熊小小牛排饭POKEBEAR（保利中心店）",
    "安贞店": "熊小小牛排饭POKEBEAR（安贞店）",
    "朝阳门店": "熊小小牛排饭POKEEBEAR（第B2档口雅宝食堂美食城店）",
    "五一广场店": "熊小小牛排饭POKEBEAR（五一广场店）",
  };
  return map[storeName] || "";
}

globalThis.__files = {
  rules: await fs.readFile(rulesPath, "utf8"),
  logic: await fs.readFile(logicPath, "utf8"),
};

const { rules, logic } = loadRuntime();
const overrides = await loadOverrides();
const dateContext = budgetDateContext(undefined, overrides);
const weekendPreset = buildWeekendPreset(overrides, dateContext);
const tasks = logic.buildTasks(rules);
const elemeLunch = tasks.filter((task) => task.platform === "饿了么" && task.type === "budget" && task.time === "10:30").map(applyOverride);
const elemeDinner = tasks.filter((task) => task.platform === "饿了么" && task.type === "budget" && task.time === "16:30").map(applyOverride);
const meituanLunch = rules.stores
  .map((store) => meituanTask(store, "午餐"))
  .filter((row) => row.status !== "unmatched");
const meituanDinner = rules.stores
  .map((store) => meituanTask(store, "晚餐"))
  .filter((row) => row.status !== "unmatched");

function meituanTask(store, period) {
  const targetBudget = budgetFor("美团", store.name, period, period === "午餐" ? store.lunchBudget : store.dinnerBudget);
  return {
    platform: "美团",
    store: matchMeituanName(store.name),
    sourceStore: store.name,
    keyword: meituanKeyword(store.name),
    period,
    time: period === "午餐" ? "上午运营按钮" : "16:30",
    type: "budget",
    targetBudget,
    status: matchMeituanName(store.name) ? "auto" : "unmatched",
    directMeituanAccountId: store.name === "朝阳门店" ? "direct_chaoyangmen" : "",
    action: matchMeituanName(store.name)
      ? `自动设置${period}预算 ${targetBudget} 元`
      : "未匹配到美团门店，需人工确认",
  };
}

const payload = {
  generated_at: new Date().toISOString(),
  budget_date_context: dateContext,
  overrides,
  weekend_preset: {
    ...weekendPreset,
    total_budget: 0,
  },
  summary: {
    eleme_lunch_count: elemeLunch.length,
    eleme_dinner_count: elemeDinner.length,
    meituan_lunch_auto_count: meituanLunch.length,
    meituan_dinner_auto_count: meituanDinner.length,
    total_initial_budget_items: elemeLunch.length + meituanLunch.length,
    total_dinner_budget_items: elemeDinner.length + meituanDinner.length,
  },
  eleme_lunch: elemeLunch.map((task) => ({
    platform: task.platform,
    store: task.store,
    shopId: task.shopId,
    period: task.period,
    time: task.time,
    targetBudget: task.budget,
    status: "auto",
    action: `自动设置午餐预算 ${task.budget} 元`,
  })),
  meituan_lunch: meituanLunch,
  eleme_dinner: elemeDinner.map((task) => ({
    platform: task.platform,
    store: task.store,
    shopId: task.shopId,
    period: task.period,
    time: task.time,
    targetBudget: task.budget,
    status: "scheduled",
    action: `16:30 自动设置晚餐预算 ${task.budget} 元`,
  })),
  meituan_dinner: meituanDinner,
};

payload.weekend_preset.total_budget = [
  ...payload.eleme_lunch,
  ...payload.meituan_lunch,
  ...payload.eleme_dinner,
  ...payload.meituan_dinner,
].reduce((sum, item) => sum + Number(item.targetBudget || 0), 0);

async function loadOverrides() {
  try {
    return JSON.parse(await fs.readFile(overridesPath, "utf8"));
  } catch {
    return { stores: {} };
  }
}

function budgetFor(platform, storeName, period, fallback) {
  const resolution = resolveBudget({ overrides, platform, storeName, period, fallback, dateContext });
  return applyWeekendPresetIfNeeded(resolution.budget, period, resolution, weekendPreset);
}

function applyOverride(task) {
  return { ...task, budget: budgetFor(task.platform, task.store, task.period, task.budget) };
}

function meituanKeyword(storeName) {
  const map = {
    "第2号档口利康金桥美食城": "第3档口",
    "第5号档口川湘府美食城店": "川湘府",
    "金融街店": "金融街",
    "丽泽店": "丽泽",
    "光谷店": "光谷",
    "双井店": "双井",
    "保利中心店": "保利中心",
    "安贞店": "安贞",
    "朝阳门店": "雅宝",
    "五一广场店": "五一广场",
  };
  return map[storeName] || "";
}

await fs.mkdir(outputDir, { recursive: true });
await fs.writeFile(jsonPath, JSON.stringify(payload, null, 2), "utf8");
await fs.writeFile(jsPath, `window.PROMO_BUDGET_PREVIEW = ${JSON.stringify(payload, null, 2)};\n`, "utf8");
console.log(JSON.stringify({ jsonPath, jsPath, summary: payload.summary }, null, 2));
