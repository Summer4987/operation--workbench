import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const inputPath = "outputs/ele_dianjin_rules/饿了么点金推广_门店规则配置表.xlsx";
const outputPath = "dianjin-prototype/rules.js";

function parseRows(ndjson) {
  const row = ndjson
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line))
    .find((item) => item.kind === "table");
  return row?.values ?? [];
}

function readTableRows(values) {
  const headers = values[2];
  return values
    .slice(3)
    .filter((row) => row.some((cell) => cell !== null && cell !== ""))
    .map((row) => Object.fromEntries(headers.map((header, index) => [header, row[index]])));
}

const blob = await FileBlob.load(inputPath);
const workbook = await SpreadsheetFile.importXlsx(blob);

const lunchInspect = await workbook.inspect({
  kind: "table",
  range: "午餐预算初始化!A1:H60",
  include: "values",
  tableMaxRows: 60,
  tableMaxCols: 8,
});
const dinnerInspect = await workbook.inspect({
  kind: "table",
  range: "晚餐预算初始化!A1:H60",
  include: "values",
  tableMaxRows: 60,
  tableMaxCols: 8,
});
const expectedInspect = await workbook.inspect({
  kind: "table",
  range: "午餐预期消耗表!A1:E20",
  include: "values",
  tableMaxRows: 20,
  tableMaxCols: 5,
});

const lunchRows = readTableRows(parseRows(lunchInspect.ndjson)).filter((row) => row["启用"] === "是");
const dinnerRows = readTableRows(parseRows(dinnerInspect.ndjson)).filter((row) => row["启用"] === "是");
const expectedRows = readTableRows(parseRows(expectedInspect.ndjson));

const dinnerByStore = new Map(dinnerRows.map((row) => [row["门店名称"], Number(row["晚餐预算"])]));
const lowMinBidStores = new Set(["银泰城店", "万象城店", "金融城店", "保利中心店", "五一广场店", "光谷店"]);
const stores = lunchRows.map((row) => ({
  name: row["门店名称"],
  lunchBudget: Number(row["午餐初始预算"]),
  dinnerBudget: dinnerByStore.get(row["门店名称"]) ?? 0,
  minBid: lowMinBidStores.has(row["门店名称"]) ? 0.4 : 0.5,
}));

const expectedSpendByBudget = {};
for (const row of expectedRows) {
  const budget = Number(row["初始预算"]);
  if (!budget) continue;
  expectedSpendByBudget[budget] = {
    "10:40": Number(row["10:40预算预计使用金额"]),
    "10:50": Number(row["10:50预算预计使用金额"]),
    "11:00": Number(row["11:00预算预计使用金额"]),
    "11:30": Number(row["11:30预算预计使用金额"]),
  };
}

const rules = {
  sourceFile: inputPath,
  generatedAt: new Date().toISOString(),
  platform: "饿了么",
  defaultMinBid: 0.5,
  lowMinBidStores: Array.from(lowMinBidStores),
  expectedSpendByBudget,
  stores,
};

const js = `window.DIANJIN_RULES = ${JSON.stringify(rules, null, 2)};\n`;
await fs.writeFile(outputPath, js, "utf8");
console.log(JSON.stringify({ outputPath, storeCount: stores.length, budgetKeys: Object.keys(expectedSpendByBudget) }, null, 2));
