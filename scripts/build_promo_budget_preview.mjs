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
    "丽泽店": "熊小小牛排饭POKEBEAR（丽泽门店）",
    "光谷店": "熊小小牛排饭POKEBEAR（光谷店）",
    "双井店": "熊小小牛排饭POKEBEAR（双井店）",
    "保利中心店": "熊小小牛排饭POKEBEAR（保利中心店）",
    "安贞店": "熊小小牛排饭POKEBEAR（安贞店）",
    "五一广场店": "熊小小牛排饭POKEBEAR（五一广场店）",
  };
  return map[storeName] || "";
}

function canonicalStoreName(storeName) {
  const text = String(storeName || "").trim();
  return /第13档口|熙悦美食城|熙悦|丽泽/.test(text) ? "丽泽门店" : text;
}

globalThis.__files = {
  rules: await fs.readFile(rulesPath, "utf8"),
  logic: await fs.readFile(logicPath, "utf8"),
};

const { rules, logic } = loadRuntime();
const overrides = await loadOverrides();
const weekendPreset = buildWeekendPreset(overrides);
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
    action: matchMeituanName(store.name)
      ? `自动设置${period}预算 ${targetBudget} 元`
      : "未匹配到美团门店，需人工确认",
  };
}

const payload = {
  generated_at: new Date().toISOString(),
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
  const canonicalName = canonicalStoreName(storeName);
  const aliasName = Object.keys(overrides.stores || {}).find((name) => canonicalStoreName(name) === canonicalName);
  const byStore = overrides.stores?.[canonicalName] || overrides.stores?.[aliasName] || {};
  const byPlatform = byStore[platform] || byStore.all || {};
  const key = period === "午餐" ? "lunchBudget" : "dinnerBudget";
  const value = Number(byPlatform[key] ?? byStore[key]);
  const baseBudget = Number.isFinite(value) && value > 0 ? value : fallback;
  return applyWeekendPreset(baseBudget, period);
}

function applyOverride(task) {
  return { ...task, budget: budgetFor(task.platform, task.store, task.period, task.budget) };
}

function buildWeekendPreset(config) {
  const preset = config.weekendPreset || {};
  const today = new Date();
  const day = today.getDay();
  const activeDays = Array.isArray(preset.activeDays) ? preset.activeDays : [0, 6];
  const configured = Object.keys(preset).length > 0;
  const enabledSetting = Boolean(preset.enabled);
  const isActiveDay = activeDays.includes(day);
  const enabled = enabledSetting && isActiveDay;
  const name = preset.name || "周末预设方案";
  const status = enabled ? "active" : configured ? "configured_inactive" : "not_configured";
  const activeDayNames = activeDays.map(dayName).filter(Boolean);
  const message = enabled
    ? `${name}今日生效，预算将按周末规则预览。`
    : configured
      ? enabledSetting
        ? `${name}已启用，但今日不在启用日，当前不会改变任何门店预算。`
        : `${name}已配置但未启用，当前不会改变任何门店预算。`
      : "周末预设待配置，当前不会改变任何门店预算。";
  return {
    enabled,
    configured,
    enabled_setting: enabledSetting,
    status,
    message,
    next_action: enabledSetting
      ? "如需调整周末规则，修改 config/promo_budget_overrides.json 的 weekendPreset 倍率、最低预算或启用日。"
      : "确认周末预算规则后，把 config/promo_budget_overrides.json 的 weekendPreset.enabled 改为 true，并设置倍率、最低预算和取整规则。",
    name,
    today_day: day,
    is_active_day: isActiveDay,
    active_days: activeDays,
    active_day_names: activeDayNames,
    lunch_multiplier: Number(preset.lunchMultiplier || 1),
    dinner_multiplier: Number(preset.dinnerMultiplier || 1),
    min_budget: Number(preset.minBudget || 0),
    round_to: Number(preset.roundTo || 1),
    notes: preset.notes || "",
  };
}

function dayName(day) {
  return ["周日", "周一", "周二", "周三", "周四", "周五", "周六"][day] || "";
}

function applyWeekendPreset(budget, period) {
  if (!weekendPreset.enabled) return budget;
  const multiplier = period === "午餐" ? weekendPreset.lunch_multiplier : weekendPreset.dinner_multiplier;
  const roundTo = weekendPreset.round_to > 0 ? weekendPreset.round_to : 1;
  const minBudget = Math.max(0, weekendPreset.min_budget || 0);
  const adjusted = Math.max(minBudget, Number(budget || 0) * multiplier);
  return Math.round(adjusted / roundTo) * roundTo;
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
    "五一广场店": "五一广场",
  };
  return map[storeName] || "";
}

await fs.mkdir(outputDir, { recursive: true });
await fs.writeFile(jsonPath, JSON.stringify(payload, null, 2), "utf8");
await fs.writeFile(jsPath, `window.PROMO_BUDGET_PREVIEW = ${JSON.stringify(payload, null, 2)};\n`, "utf8");
console.log(JSON.stringify({ jsonPath, jsPath, summary: payload.summary }, null, 2));
