import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = "outputs/ele_dianjin_rules";
const outputPath = `${outputDir}/饿了么点金推广_门店规则配置表.xlsx`;

const stores = [
  ["第2号档口利康金桥美食城", 120, 200],
  ["第5号档口川湘府美食城店", 100, 150],
  ["金融街店", 100, 150],
  ["光谷店", 80, 120],
  ["万象城店", 60, 120],
  ["双井店", 80, 150],
  ["金融城店", 100, 150],
  ["银泰城店", 100, 150],
  ["丽泽店", 100, 150],
  ["保利中心店", 90, 140],
  ["安贞店", 100, 150],
  ["朝阳门店", 120, 200],
  ["五一广场店", 80, 130],
  ["望京店", 100, 150],
  ["滨江店", 100, 150],
];

const expectedByBudget = {
  60: { "10:40": 5, "10:50": 10, "11:00": 20, "11:30": 30 },
  80: { "10:40": 10, "10:50": 20, "11:00": 30, "11:30": 65 },
  90: { "10:40": 10, "10:50": 20, "11:00": 30, "11:30": 65 },
  100: { "10:40": 10, "10:50": 20, "11:00": 30, "11:30": 65 },
  120: { "10:40": 15, "10:50": 30, "11:00": 45, "11:30": 80 },
};

const workbook = Workbook.create();
const colors = {
  dark: "#1F4E78",
  paleBlue: "#D9EAF7",
  paleGreen: "#E2F0D9",
  paleYellow: "#FFF2CC",
  red: "#C00000",
  border: "#D9D9D9",
  text: "#1F1F1F",
};

function colName(index) {
  let n = index + 1;
  let name = "";
  while (n > 0) {
    const rem = (n - 1) % 26;
    name = String.fromCharCode(65 + rem) + name;
    n = Math.floor((n - 1) / 26);
  }
  return name;
}

function addTitle(sheet, lastCol, title, subtitle) {
  const end = colName(lastCol - 1);
  sheet.mergeCells(`A1:${end}1`);
  sheet.getRange(`A1:${end}1`).values = [[title]];
  sheet.getRange(`A1:${end}1`).format = {
    fill: { color: colors.dark },
    font: { color: "#FFFFFF", bold: true, size: 15 },
    wrapText: true,
  };
  sheet.getRange(`A1:${end}1`).format.rowHeightPx = 34;
  sheet.mergeCells(`A2:${end}2`);
  sheet.getRange(`A2:${end}2`).values = [[subtitle]];
  sheet.getRange(`A2:${end}2`).format = {
    fill: { color: colors.paleBlue },
    font: { color: colors.text, italic: true },
    wrapText: true,
  };
  sheet.getRange(`A2:${end}2`).format.rowHeightPx = 32;
}

function writeTable(sheet, headers, rows, widths, { title, subtitle, requiredCols = 0 }) {
  addTitle(sheet, headers.length, title, subtitle);
  sheet.getRangeByIndexes(2, 0, 1, headers.length).values = [headers];
  sheet.getRangeByIndexes(2, 0, 1, headers.length).format = {
    fill: { color: colors.dark },
    font: { color: "#FFFFFF", bold: true },
    wrapText: true,
    borders: { preset: "all", style: "thin", color: colors.border },
  };
  if (requiredCols) {
    sheet.getRangeByIndexes(2, 0, 1, requiredCols).format.fill = { color: colors.red };
  }
  const bodyRows = Math.max(rows.length, 40);
  const normalized = Array.from({ length: bodyRows }, (_, r) =>
    Array.from({ length: headers.length }, (_, c) => rows[r]?.[c] ?? "")
  );
  sheet.getRangeByIndexes(3, 0, bodyRows, headers.length).values = normalized;
  sheet.getRangeByIndexes(3, 0, bodyRows, headers.length).format = {
    borders: { preset: "all", style: "thin", color: colors.border },
    font: { color: colors.text, size: 10 },
    wrapText: true,
  };
  widths.forEach((width, i) => {
    sheet.getRangeByIndexes(0, i, 1, 1).format.columnWidthPx = width;
  });
  sheet.freezePanes.freezeRows(3);
  sheet.showGridLines = false;
}

const summary = workbook.worksheets.add("执行总览");
writeTable(
  summary,
  ["平台", "时段", "执行时间", "任务类型", "是否调整预算", "是否调整出价", "任务说明"],
  [
    ["饿了么", "午餐", "10:30", "预算初始化", "是", "否", "10:30前完成所有门店预算调整；初始出价保持不变。"],
    ["饿了么", "午餐", "10:40", "消耗检查并调出价", "否", "是", "读取实际使用金额，对比该门店预算对应的10:40预期消耗。"],
    ["饿了么", "午餐", "10:50", "消耗检查并调出价", "否", "是", "读取实际使用金额，对比该门店预算对应的10:50预期消耗。"],
    ["饿了么", "午餐", "11:00", "消耗检查并调出价", "否", "是", "读取实际使用金额，对比该门店预算对应的11:00预期消耗。"],
    ["饿了么", "午餐", "11:30", "消耗检查并调出价", "否", "是", "读取实际使用金额，对比该门店预算对应的11:30预期消耗。"],
    ["饿了么", "晚餐", "16:30", "预算初始化", "是", "否", "16:30前完成所有门店预算调整；出价保持不变。"],
  ],
  [90, 80, 90, 150, 110, 110, 520],
  {
    title: "饿了么点金推广执行总览",
    subtitle: "脚本应按这一页的时间点执行：预算初始化任务只改预算；消耗检查任务只根据实际消耗调整出价。",
    requiredCols: 6,
  }
);

const lunchBudget = workbook.worksheets.add("午餐预算初始化");
writeTable(
  lunchBudget,
  ["启用", "平台", "门店名称", "执行时间", "午餐初始预算", "初始出价动作", "执行要求", "备注"],
  stores.map(([name, lunch]) => ["是", "饿了么", name, "10:30", lunch, "不变", "10:30前保证调整完成", ""]),
  [70, 90, 240, 90, 120, 120, 180, 220],
  {
    title: "午餐 10:30 预算初始化",
    subtitle: "这一页只用于10:30预算调整，不调整出价。",
    requiredCols: 6,
  }
);
lunchBudget.getRange("E4:E43").setNumberFormat("0");

const expected = workbook.worksheets.add("午餐预期消耗表");
writeTable(
  expected,
  ["初始预算", "10:40预算预计使用金额", "10:50预算预计使用金额", "11:00预算预计使用金额", "11:30预算预计使用金额"],
  Object.entries(expectedByBudget).map(([budget, values]) => [
    Number(budget),
    values["10:40"],
    values["10:50"],
    values["11:00"],
    values["11:30"],
  ]),
  [100, 170, 170, 170, 170],
  {
    title: "午餐不同预算的预期消耗",
    subtitle: "脚本读取门店初始预算后，用这一页找到对应时间点的预期使用金额。",
    requiredCols: 5,
  }
);
expected.getRange("A4:E43").setNumberFormat("0");

const lunchChecks = workbook.worksheets.add("午餐检查任务");
const checkRows = [];
for (const [name, lunch] of stores) {
  for (const time of ["10:40", "10:50", "11:00", "11:30"]) {
    checkRows.push([
      "是",
      "饿了么",
      name,
      time,
      lunch,
      expectedByBudget[lunch][time],
      "读取页面实际使用金额",
      "实际 < 预期",
      "+0.1",
      "实际 > 预期",
      "超出预期10%以上且低于20%时 -0.1",
      "实际 >= 预期 * 1.2",
      "0.2",
      "实际低于预期：+0.1；实际超出预期10%以上：-0.1；实际超出预期20%或以上：-0.2",
    ]);
  }
}
writeTable(
  lunchChecks,
  [
    "启用",
    "平台",
    "门店名称",
    "检查时间",
    "午餐初始预算",
    "本时间点预期消耗",
    "实际消耗来源",
    "未达预期判断",
    "未达预期出价调整",
    "超出预期判断",
    "超出预期出价调整",
    "严重超出判断",
    "严重超出调整幅度",
    "备注",
  ],
  checkRows,
  [70, 90, 240, 90, 110, 130, 150, 120, 130, 120, 130, 100, 110, 260],
  {
    title: "午餐消耗检查与出价调整任务",
    subtitle: "10:40、10:50、11:00、11:30分别执行。读取实际使用金额后和预期消耗对比，再调整出价。",
    requiredCols: 13,
  }
);
lunchChecks.getRange("E4:F83").setNumberFormat("0");

const dinnerBudget = workbook.worksheets.add("晚餐预算初始化");
writeTable(
  dinnerBudget,
  ["启用", "平台", "门店名称", "执行时间", "晚餐预算", "出价动作", "执行要求", "备注"],
  stores.map(([name, , dinner]) => ["是", "饿了么", name, "16:30", dinner, "不变", "16:30前保证调整完成", ""]),
  [70, 90, 240, 90, 120, 120, 180, 220],
  {
    title: "晚餐 16:30 预算初始化",
    subtitle: "这一页只用于16:30预算调整，出价保持不变。",
    requiredCols: 6,
  }
);
dinnerBudget.getRange("E4:E43").setNumberFormat("0");

const bidRule = workbook.worksheets.add("出价调整规则");
writeTable(
  bidRule,
  ["规则项", "默认值", "说明", "是否已确认"],
  [
    ["未达预期", "出价增加0.1元", "实际使用金额低于当前时间点预期消耗，只要有差额就执行。", "是"],
    ["轻度超出预期", "出价降低0.1元", "实际使用金额超出当前时间点预期消耗10%以上，但低于20%。", "是"],
    ["严重超出预期", "出价降低0.2元", "实际使用金额超出当前时间点预期消耗20%或以上。", "是"],
    ["10:30预算初始化", "不调整出价", "午餐10:30只调整预算。", "是"],
    ["16:30预算初始化", "不调整出价", "晚餐16:30只调整预算。", "是"],
  ],
  [160, 160, 520, 130],
  {
    title: "出价调整规则",
    subtitle: "出价规则已按差额和超出比例明确：低于预期加价，超出10%降0.1，超出20%或以上降0.2。",
    requiredCols: 4,
  }
);

const guide = workbook.worksheets.add("脚本读取说明");
writeTable(
  guide,
  ["模块", "脚本应该怎么用", "需要你后续确认的内容"],
  [
    ["执行总览", "按时间点触发任务；同一时间点遍历对应门店。", "是否需要提前几分钟启动，比如10:28开始确保10:30完成。"],
    ["午餐预算初始化", "10:30任务读取门店名称和午餐初始预算，只修改预算。", "饿了么后台门店名称是否和表格完全一致。"],
    ["午餐检查任务", "每个检查时间读取实际使用金额，对比本行预期消耗，然后调整出价。", "需要确认实际金额读取的是累计使用金额，还是当前时间段使用金额。"],
    ["晚餐预算初始化", "16:30任务读取门店名称和晚餐预算，只修改预算。", "晚餐是否也需要后续消耗检查和调价。"],
    ["出价调整规则", "作为程序的默认判断规则。", "出价是否有上限、下限，以及调价后是否需要截图记录。"],
  ],
  [160, 480, 420],
  {
    title: "脚本读取说明",
    subtitle: "这一页不是日常操作表，是给后续自动化程序的读取口径。",
    requiredCols: 0,
  }
);

for (const sheet of [summary, lunchBudget, expected, lunchChecks, dinnerBudget, bidRule, guide]) {
  sheet.getRange("A3:Z3").format.rowHeightPx = 38;
}

await fs.mkdir(outputDir, { recursive: true });

for (const sheetName of [
  "执行总览",
  "午餐预算初始化",
  "午餐预期消耗表",
  "午餐检查任务",
  "晚餐预算初始化",
  "出价调整规则",
  "脚本读取说明",
]) {
  await workbook.render({ sheetName, autoCrop: "all", scale: 1, format: "png" });
}

const inspect = await workbook.inspect({
  kind: "table",
  range: "午餐检查任务!A1:N12",
  include: "values",
  tableMaxRows: 12,
  tableMaxCols: 14,
});
console.log(inspect.ndjson);

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 50 },
  summary: "formula error scan",
});
console.log(errors.ndjson);

const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(outputPath);
console.log(outputPath);
