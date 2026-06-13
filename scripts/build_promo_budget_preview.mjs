import fs from "node:fs/promises";
import vm from "node:vm";

const rulesPath = "dianjin-prototype/rules.js";
const logicPath = "dianjin-prototype/logic.js";
const outputDir = "outputs/promo_budget_preview";
const jsonPath = `${outputDir}/latest.json`;
const jsPath = `${outputDir}/latest-data.js`;
const overridesPath = "config/promo_budget_overrides.json";

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
    "丽泽店": "熊小小牛排饭POKEBEAR·STEAK（第13档口熙悦美食城店）",
    "光谷店": "熊小小牛排饭POKEBEAR（光谷店）",
    "双井店": "熊小小牛排饭POKEBEAR（双井店）",
    "保利中心店": "熊小小牛排饭POKEBEAR（保利中心店）",
    "安贞店": "熊小小牛排饭POKEBEAR（安贞店）",
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
const tasks = logic.buildTasks(rules);
const elemeLunch = tasks.filter((task) => task.platform === "饿了么" && task.type === "budget" && task.time === "10:30").map(applyOverride);
const elemeDinner = tasks.filter((task) => task.platform === "饿了么" && task.type === "budget" && task.time === "17:30").map(applyOverride);
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
    time: period === "午餐" ? "上午运营按钮" : "17:30",
    type: "budget",
    targetBudget,
    status: matchMeituanName(store.name) ? "auto" : "unmatched",
    action: matchMeituanName(store.name)
      ? `自动设置${period}预算 ${targetBudget} 元`
      : "未匹配到美团门店，需人工确认",
  };
}

const payload = {
  generated_at: new Date().toISOString(),
  overrides,
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
    action: `17:30 自动设置晚餐预算 ${task.budget} 元`,
  })),
  meituan_dinner: meituanDinner,
};

async function loadOverrides() {
  try {
    return JSON.parse(await fs.readFile(overridesPath, "utf8"));
  } catch {
    return { stores: {} };
  }
}

function budgetFor(platform, storeName, period, fallback) {
  const byStore = overrides.stores?.[storeName] || {};
  const byPlatform = byStore[platform] || byStore.all || {};
  const key = period === "午餐" ? "lunchBudget" : "dinnerBudget";
  const value = Number(byPlatform[key] ?? byStore[key]);
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

function applyOverride(task) {
  return { ...task, budget: budgetFor(task.platform, task.store, task.period, task.budget) };
}

function meituanKeyword(storeName) {
  const map = {
    "第2号档口利康金桥美食城": "第3档口",
    "第5号档口川湘府美食城店": "川湘府",
    "金融街店": "金融街",
    "丽泽店": "第13档口",
    "光谷店": "光谷",
    "双井店": "双井",
    "保利中心店": "保利中心",
    "安贞店": "安贞",
    "五一广场店": "五一广场",
  };
  return map[storeName] || "";
}

await fs.mkdir(outputDir, { recursive: true });
await fs.writeFile(jsonPath, JSON.stringify(payload, null, 2), "utf8");
await fs.writeFile(jsPath, `window.PROMO_BUDGET_PREVIEW = ${JSON.stringify(payload, null, 2)};\n`, "utf8");
console.log(JSON.stringify({ jsonPath, jsPath, summary: payload.summary }, null, 2));
