import fs from "node:fs/promises";
import vm from "node:vm";
import {
  applyWeekendPresetIfNeeded,
  budgetDateContext,
  buildWeekendPreset,
  resolveBudget,
} from "./promo_budget_resolver.mjs";

const rulesPath = "dianjin-prototype/rules.js";
const logicPath = "dianjin-prototype/logic.js";
const overridesPath = "config/promo_budget_overrides.json";
const statePath = process.argv[2] || "outputs/dianjin_automation/current_state_1040_all.json";
const outputDir = "outputs/dianjin_automation";

function argValue(name, fallback = "") {
  const index = process.argv.indexOf(`--${name}`);
  if (index < 0) return fallback;
  return process.argv[index + 1] || fallback;
}

function loadRuntime() {
  const context = { window: {} };
  vm.runInNewContext(globalThis.__files.rules, context);
  vm.runInNewContext(globalThis.__files.logic, context);
  return {
    rules: context.window.DIANJIN_RULES,
    logic: context.window.DIANJIN_LOGIC,
  };
}

function roundBid(value, minBid = 0.5) {
  if (!Number.isFinite(value)) return null;
  return Math.max(minBid, Math.round(value * 10) / 10);
}

function csvCell(value) {
  const text = value === undefined || value === null ? "" : String(value);
  return `"${text.replace(/"/g, '""')}"`;
}

function bidActionLabel(delta) {
  if (delta > 0) return `出价 +${delta.toFixed(1)}`;
  if (delta < 0) return `出价 ${delta.toFixed(1)}`;
  return "出价不变";
}

function filterTasks(tasks, time) {
  return tasks.filter((task) => !time || task.time === time);
}

globalThis.__files = {
  rules: await fs.readFile(rulesPath, "utf8"),
  logic: await fs.readFile(logicPath, "utf8"),
};

const { rules, logic } = loadRuntime();
const overrides = await loadOverrides();
const dateContext = budgetDateContext();
const weekendPreset = buildWeekendPreset(overrides, dateContext);
const state = JSON.parse(await fs.readFile(statePath, "utf8"));
const time = argValue("time", "10:40");
const rowsByShopId = new Map((state.currentRows || []).map((row) => [Number(row.shopId), row]));
const tasks = filterTasks(logic.buildTasks(rules), time);

async function loadOverrides() {
  try {
    return JSON.parse(await fs.readFile(overridesPath, "utf8"));
  } catch {
    return { stores: {} };
  }
}

function budgetFor(task) {
  if (task.type !== "budget") return task.budget;
  const resolution = resolveBudget({
    overrides,
    platform: task.platform,
    storeName: task.store,
    period: task.period,
    fallback: task.budget,
    dateContext,
  });
  return applyWeekendPresetIfNeeded(resolution.budget, task.period, resolution, weekendPreset);
}

const previewRows = tasks.map((task) => {
  const current = rowsByShopId.get(Number(task.shopId));
  const targetBudget = budgetFor(task);
  const base = {
    taskId: task.id,
    platform: task.platform,
    period: task.period,
    time: task.time,
    type: task.type,
    store: task.store,
    shopId: task.shopId,
    elemeFullName: task.elemeFullName,
    found: Boolean(current),
    currentBid: current?.bid ?? null,
    bidAssistantStatus: current?.bidAssistantStatus || "",
    currentBudget: current?.budget ?? null,
    currentSpend: current?.spend ?? null,
    minBid: task.minBid ?? rules.defaultMinBid ?? 0.5,
    budgetUsage: current?.budgetUsage || "",
    switchStatus: current?.switchStatus || "",
    targetBudget: task.type === "budget" ? targetBudget : current?.budget ?? null,
    expectedSpend: task.expectedSpend ?? null,
    bidDelta: 0,
    targetBid: current?.bid ?? null,
    action: "",
    risk: "",
    canExecute: Boolean(current),
  };

  if (!current) {
    return { ...base, action: "缺少后台状态", risk: "当前读取结果里没有该门店，禁止自动执行", canExecute: false };
  }

  if (task.type === "budget") {
    const changed = current.budget !== targetBudget;
    return {
      ...base,
      action: changed ? `预算 ${current.budget} -> ${targetBudget}` : "预算已符合",
      risk: current.switchStatus !== "开启" ? "投放开关不是开启状态" : "",
    };
  }

  const decision = logic.evaluateBid(task.expectedSpend, current.spend);
  const currentBid = current.bid ?? 0;
  const minBid = task.minBid ?? rules.defaultMinBid ?? 0.5;
  const targetBid = roundBid(currentBid + decision.delta, minBid);
  const actualDelta = Number.isFinite(targetBid) ? Math.round((targetBid - currentBid) * 10) / 10 : 0;
  const action = decision.delta !== 0 && actualDelta === 0 ? "出价已在下限" : bidActionLabel(actualDelta);
  return {
    ...base,
    bidDelta: actualDelta,
    targetBid,
    action,
    risk: current.switchStatus !== "开启" ? "投放开关不是开启状态" : "",
    decisionReason: decision.reason,
  };
});

const summary = {
  generatedAt: new Date().toISOString(),
  sourceState: statePath,
  time,
  total: previewRows.length,
  executable: previewRows.filter((row) => row.canExecute).length,
  missing: previewRows.filter((row) => !row.found).length,
  budgetChanges: previewRows.filter((row) => row.type === "budget" && row.currentBudget !== row.targetBudget).length,
  bidUp: previewRows.filter((row) => row.bidDelta > 0).length,
  bidDown: previewRows.filter((row) => row.bidDelta < 0).length,
  noChange: previewRows.filter((row) => row.action.includes("不变") || row.action.includes("已符合") || row.action.includes("已在下限")).length,
};

await fs.mkdir(outputDir, { recursive: true });
const safeTime = time.replace(":", "");
const jsonPath = `${outputDir}/execution_preview_${safeTime}.json`;
const csvPath = `${outputDir}/execution_preview_${safeTime}.csv`;
const jsPath = "dianjin-prototype/execution_preview.js";

const payload = { summary, rows: previewRows };
payload.budget_date_context = dateContext;
payload.weekend_preset = weekendPreset;
await fs.writeFile(jsonPath, JSON.stringify(payload, null, 2), "utf8");

const csvRows = [
  ["时间", "类型", "门店", "shopId", "最低出价", "当前出价", "目标出价", "出价变化", "当前预算", "目标预算", "今日花费", "预期花费", "预算使用率", "投放开关", "动作", "风险", "可执行"],
  ...previewRows.map((row) => [
    row.time,
    row.type,
    row.store,
    row.shopId,
    row.minBid,
    row.currentBid,
    row.targetBid,
    row.bidDelta,
    row.currentBudget,
    row.targetBudget,
    row.currentSpend,
    row.expectedSpend,
    row.budgetUsage,
    row.switchStatus,
    row.action,
    row.risk,
    row.canExecute ? "是" : "否",
  ]),
];
await fs.writeFile(csvPath, `\ufeff${csvRows.map((row) => row.map(csvCell).join(",")).join("\n")}`, "utf8");
await fs.writeFile(jsPath, `window.DIANJIN_EXECUTION_PREVIEW = ${JSON.stringify(payload, null, 2)};\n`, "utf8");

console.log(JSON.stringify({ summary, jsonPath, csvPath, jsPath }, null, 2));
