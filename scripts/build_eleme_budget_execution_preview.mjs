import fs from "node:fs/promises";
import path from "node:path";

function parseArgs(argv) {
  const args = { time: "", source: "outputs/promo_budget_preview/latest.json", output: "" };
  for (let index = 0; index < argv.length; index += 1) {
    const value = argv[index];
    if (value === "--time") args.time = argv[++index] || "";
    else if (value === "--source") args.source = argv[++index] || args.source;
    else if (value === "--output") args.output = argv[++index] || "";
    else throw new Error(`未知参数：${value}`);
  }
  if (!['10:30', '16:30'].includes(args.time)) {
    throw new Error("--time 仅支持 10:30 或 16:30");
  }
  if (!args.output) {
    args.output = `outputs/dianjin_automation/execution_preview_${args.time.replace(':', '')}.json`;
  }
  return args;
}

const args = parseArgs(process.argv.slice(2));
const source = JSON.parse(await fs.readFile(args.source, "utf8"));
const period = args.time === "10:30" ? "午餐" : "晚餐";
const sourceRows = args.time === "10:30" ? source.eleme_lunch : source.eleme_dinner;
if (!Array.isArray(sourceRows) || sourceRows.length === 0) {
  throw new Error(`预算源文件没有${period}饿了么任务`);
}

const rows = sourceRows.map((row) => ({
  taskId: `${args.time === "10:30" ? "lunch" : "dinner"}-budget-${row.store}`,
  platform: "饿了么",
  period,
  time: args.time,
  type: "budget",
  store: row.store,
  shopId: Number(row.shopId),
  elemeFullName: "",
  found: true,
  currentBid: null,
  bidAssistantStatus: "",
  currentBudget: null,
  currentSpend: null,
  minBid: null,
  budgetUsage: "",
  switchStatus: "",
  targetBudget: Number(row.targetBudget),
  expectedSpend: null,
  bidDelta: 0,
  targetBid: null,
  action: `批量页设置${period}预算 ${Number(row.targetBudget)} 元`,
  risk: "",
  canExecute: true,
}));

const payload = {
  summary: {
    generatedAt: new Date().toISOString(),
    sourceState: args.source,
    sourceMode: "oldBranch-visible-table",
    time: args.time,
    total: rows.length,
    executable: rows.length,
    missing: 0,
    budgetChanges: rows.length,
    bidUp: 0,
    bidDown: 0,
    noChange: 0,
  },
  rows,
};

await fs.mkdir(path.dirname(args.output), { recursive: true });
await fs.writeFile(args.output, JSON.stringify(payload, null, 2), "utf8");
console.log(JSON.stringify({ output: args.output, time: args.time, rows: rows.length }, null, 2));
