import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = "outputs/diangjin_config_template";
const outputPath = `${outputDir}/点金推广自动化_门店配置表.xlsx`;

const workbook = Workbook.create();

const colors = {
  navy: "#1F4E78",
  blue: "#D9EAF7",
  green: "#E2F0D9",
  yellow: "#FFF2CC",
  gray: "#F2F2F2",
  border: "#D9D9D9",
  text: "#1F1F1F",
};

function title(sheet, range, text, subtitle = "") {
  sheet.mergeCells(range);
  const r = sheet.getRange(range);
  r.values = [[text]];
  r.format.fill = { color: colors.navy };
  r.format.font = { color: "#FFFFFF", bold: true, size: 15 };
  r.format.rowHeightPx = 34;
  if (subtitle) {
    const [start, end] = range.split(":");
    const row = Number(start.match(/\d+/)[0]) + 1;
    const colEnd = end.replace(/\d+/g, "");
    sheet.mergeCells(`A${row}:${colEnd}${row}`);
    const sr = sheet.getRange(`A${row}:${colEnd}${row}`);
    sr.values = [[subtitle]];
    sr.format.fill = { color: colors.blue };
    sr.format.font = { color: colors.text, italic: true };
    sr.format.wrapText = true;
  }
}

function styleHeader(range) {
  range.format.fill = { color: colors.navy };
  range.format.font = { color: "#FFFFFF", bold: true };
  range.format.wrapText = true;
  range.format.borders = { preset: "all", style: "thin", color: colors.border };
  range.format.rowHeightPx = 38;
}

function styleBody(range) {
  range.format.borders = { preset: "all", style: "thin", color: colors.border };
  range.format.wrapText = true;
  range.format.font = { color: colors.text, size: 10 };
}

function setWidths(sheet, widths) {
  widths.forEach((px, i) => {
    sheet.getRangeByIndexes(0, i, 1, 1).format.columnWidthPx = px;
  });
}

function writeSheet(sheet, { headers, rows, widths, titleText, subtitle, requiredCount = 0 }) {
  title(sheet, `A1:${String.fromCharCode(64 + headers.length)}1`, titleText, subtitle);
  sheet.getRangeByIndexes(2, 0, 1, headers.length).values = [headers];
  styleHeader(sheet.getRangeByIndexes(2, 0, 1, headers.length));
  if (rows.length) {
    const normalizedRows = rows.map((row) =>
      Array.from({ length: headers.length }, (_, i) => row[i] ?? "")
    );
    sheet.getRangeByIndexes(3, 0, rows.length, headers.length).values = normalizedRows;
  }
  styleBody(sheet.getRangeByIndexes(3, 0, Math.max(rows.length, 60), headers.length));
  if (requiredCount > 0) {
    sheet.getRangeByIndexes(2, 0, 1, requiredCount).format.fill = { color: "#C00000" };
  }
  setWidths(sheet, widths);
  sheet.freezePanes.freezeRows(3);
  sheet.showGridLines = false;
}

const dict = workbook.worksheets.add("字典");
const dictionaryRows = [
  ["平台", "美团", "饿了么", "全部"],
  ["是否", "是", "否", ""],
  ["执行时段", "午餐", "晚餐", "全天"],
  ["切店方式", "搜索门店名", "下拉选择", "固定入口"],
  ["余额低动作", "跳过并提醒", "关闭推广", "降低预算", "继续执行"],
  ["失败处理", "暂停等待人工", "跳过下一家", "重试一次"],
  ["确认方式", "自动保存", "保存前逐店确认", "只预览不保存"],
  ["匹配严格度", "完全一致", "包含关键词", "人工确认"],
  ["规则组", "默认", "高客单", "低余额", "新店"],
];
writeSheet(dict, {
  headers: ["字段", "选项1", "选项2", "选项3"],
  rows: dictionaryRows,
  widths: [140, 140, 140, 140],
  titleText: "下拉选项字典",
  subtitle: "这里是模板使用的统一选项。后续脚本也可以读取这些选项，保持表格和程序口径一致。",
});

const stores = workbook.worksheets.add("门店配置");
const storeHeaders = [
  "启用",
  "平台",
  "门店编码",
  "门店名称_后台显示",
  "搜索关键词/别名",
  "匹配严格度",
  "美团切店方式",
  "美团切店入口备注",
  "饿了么页面/分组备注",
  "午餐启用",
  "晚餐启用",
  "规则组",
  "午餐目标消耗",
  "晚餐目标消耗",
  "最低余额",
  "余额预警线",
  "余额低动作",
  "默认预算",
  "预算下限",
  "预算上限",
  "默认出价",
  "出价下限",
  "出价上限",
  "允许自动开启",
  "允许自动关闭",
  "保存前确认",
  "失败处理",
  "执行顺序",
  "截图记录",
  "备注",
  "配置状态",
];
const blankStoreRows = Array.from({ length: 80 }, (_, i) => [
  i === 0 ? "是" : "",
  i === 0 ? "美团" : "",
  "",
  i === 0 ? "示例门店A" : "",
  i === 0 ? "示例门店A/示例A" : "",
  i === 0 ? "完全一致" : "",
  i === 0 ? "搜索门店名" : "",
  "",
  "",
  i === 0 ? "是" : "",
  i === 0 ? "是" : "",
  i === 0 ? "默认" : "",
  i === 0 ? 80 : "",
  i === 0 ? 120 : "",
  i === 0 ? 50 : "",
  i === 0 ? 100 : "",
  i === 0 ? "跳过并提醒" : "",
  "",
  "",
  "",
  "",
  "",
  "",
  i === 0 ? "是" : "",
  i === 0 ? "否" : "",
  i === 0 ? "保存前逐店确认" : "",
  i === 0 ? "暂停等待人工" : "",
  i === 0 ? 1 : "",
  i === 0 ? "是" : "",
  i === 0 ? "第一行是示例，可直接覆盖" : "",
  "",
]);
writeSheet(stores, {
  headers: storeHeaders,
  rows: blankStoreRows,
  widths: [
    70, 90, 110, 180, 190, 110, 120, 190, 170, 90, 90, 90, 110, 110, 90, 95, 115,
    90, 90, 90, 90, 90, 90, 105, 105, 125, 125, 80, 90, 220, 120,
  ],
  titleText: "门店配置",
  subtitle: "红色表头为建议必填。美团自动切店最依赖“门店名称_后台显示”“搜索关键词/别名”“匹配严格度”和“美团切店方式”。",
  requiredCount: 12,
});
stores.getRange("AE4:AE83").formulasR1C1 = Array.from({ length: 80 }, () => [
  '=IF(OR(RC[-30]="",RC[-29]="",RC[-27]="",RC[-19]=""),"待补全","可执行")',
]);
stores.getRange("M4:W83").setNumberFormat("0.00");
stores.getRange("AB4:AB83").setNumberFormat("0");
stores.getRange("A4:A83").dataValidation = { rule: { type: "list", values: ["是", "否"] } };
stores.getRange("B4:B83").dataValidation = { rule: { type: "list", values: ["美团", "饿了么"] } };
stores.getRange("F4:F83").dataValidation = { rule: { type: "list", values: ["完全一致", "包含关键词", "人工确认"] } };
stores.getRange("G4:G83").dataValidation = { rule: { type: "list", values: ["搜索门店名", "下拉选择", "固定入口"] } };
stores.getRange("J4:K83").dataValidation = { rule: { type: "list", values: ["是", "否"] } };
stores.getRange("L4:L83").dataValidation = { rule: { type: "list", values: ["默认", "高客单", "低余额", "新店"] } };
stores.getRange("Q4:Q83").dataValidation = { rule: { type: "list", values: ["跳过并提醒", "关闭推广", "降低预算", "继续执行"] } };
stores.getRange("X4:Y83").dataValidation = { rule: { type: "list", values: ["是", "否"] } };
stores.getRange("Z4:Z83").dataValidation = { rule: { type: "list", values: ["自动保存", "保存前逐店确认", "只预览不保存"] } };
stores.getRange("AA4:AA83").dataValidation = { rule: { type: "list", values: ["暂停等待人工", "跳过下一家", "重试一次"] } };
stores.getRange("AC4:AC83").dataValidation = { rule: { type: "list", values: ["是", "否"] } };
stores.getRange("AE4:AE83").conditionalFormats.add("containsText", {
  text: "待补全",
  format: { fill: { color: "#F4CCCC" }, font: { color: "#990000", bold: true } },
});
stores.getRange("AE4:AE83").conditionalFormats.add("containsText", {
  text: "可执行",
  format: { fill: { color: "#D9EAD3" }, font: { color: "#274E13", bold: true } },
});

const rules = workbook.worksheets.add("规则参数");
const ruleHeaders = [
  "启用",
  "规则组",
  "平台",
  "执行时段",
  "开始时间",
  "结束时间",
  "目标消耗",
  "消耗低于_加预算",
  "消耗高于_降预算",
  "每次预算调整",
  "预算下限",
  "预算上限",
  "余额低于",
  "余额低动作",
  "出价低于_加价",
  "出价高于_降价",
  "每次出价调整",
  "出价下限",
  "出价上限",
  "是否允许开关推广",
  "备注",
];
const ruleRows = [
  ["是", "默认", "美团", "午餐", "10:30", "13:30", "", "", "", "", "", "", "", "跳过并提醒", "", "", "", "", "", "是", "先填你的午餐判断逻辑"],
  ["是", "默认", "美团", "晚餐", "16:30", "20:30", "", "", "", "", "", "", "", "跳过并提醒", "", "", "", "", "", "是", "先填你的晚餐判断逻辑"],
  ["是", "默认", "饿了么", "午餐", "10:30", "13:30", "", "", "", "", "", "", "", "跳过并提醒", "", "", "", "", "", "是", ""],
  ["是", "默认", "饿了么", "晚餐", "16:30", "20:30", "", "", "", "", "", "", "", "跳过并提醒", "", "", "", "", "", "是", ""],
  ["", "高客单", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""],
  ["", "低余额", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""],
  ["", "新店", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""],
];
writeSheet(rules, {
  headers: ruleHeaders,
  rows: ruleRows,
  widths: [70, 90, 90, 90, 90, 90, 90, 120, 120, 120, 90, 90, 90, 115, 115, 115, 115, 90, 90, 120, 220],
  titleText: "规则参数",
  subtitle: "这里放计算逻辑。第一版可以先填目标、阈值和动作；如果你的规则更复杂，我会再把这些字段改成程序可直接解析的版本。",
  requiredCount: 6,
});
rules.getRange("A4:A63").dataValidation = { rule: { type: "list", values: ["是", "否"] } };
rules.getRange("C4:C63").dataValidation = { rule: { type: "list", values: ["美团", "饿了么", "全部"] } };
rules.getRange("D4:D63").dataValidation = { rule: { type: "list", values: ["午餐", "晚餐", "全天"] } };
rules.getRange("N4:N63").dataValidation = { rule: { type: "list", values: ["跳过并提醒", "关闭推广", "降低预算", "继续执行"] } };
rules.getRange("T4:T63").dataValidation = { rule: { type: "list", values: ["是", "否"] } };
rules.getRange("G4:S63").setNumberFormat("0.00");

const runs = workbook.worksheets.add("执行批次");
const runHeaders = [
  "启用",
  "批次名称",
  "执行日期",
  "执行时段",
  "平台范围",
  "门店范围",
  "执行模式",
  "保存方式",
  "切店后校验门店名",
  "门店不匹配处理",
  "失败重试次数",
  "执行前余额检查",
  "执行后截图",
  "日志文件名",
  "备注",
];
const runRows = [
  ["是", "午餐日常调整", "", "午餐", "全部", "启用门店", "正式执行", "保存前逐店确认", "是", "暂停等待人工", 1, "是", "是", "", ""],
  ["是", "晚餐日常调整", "", "晚餐", "全部", "启用门店", "正式执行", "保存前逐店确认", "是", "暂停等待人工", 1, "是", "是", "", ""],
  ["", "测试预览", "", "午餐", "美团", "前3家", "只预览", "只预览不保存", "是", "暂停等待人工", 0, "是", "是", "", ""],
];
writeSheet(runs, {
  headers: runHeaders,
  rows: runRows,
  widths: [70, 140, 110, 90, 90, 110, 100, 130, 130, 135, 100, 115, 100, 150, 220],
  titleText: "执行批次",
  subtitle: "这里决定当天跑午餐还是晚餐、跑哪个平台、保存前是否确认，以及失败时脚本应该怎么停。",
  requiredCount: 10,
});
runs.getRange("A4:A63").dataValidation = { rule: { type: "list", values: ["是", "否"] } };
runs.getRange("D4:D63").dataValidation = { rule: { type: "list", values: ["午餐", "晚餐", "全天"] } };
runs.getRange("E4:E63").dataValidation = { rule: { type: "list", values: ["美团", "饿了么", "全部"] } };
runs.getRange("G4:G63").dataValidation = { rule: { type: "list", values: ["正式执行", "只预览"] } };
runs.getRange("H4:H63").dataValidation = { rule: { type: "list", values: ["自动保存", "保存前逐店确认", "只预览不保存"] } };
runs.getRange("I4:I63").dataValidation = { rule: { type: "list", values: ["是", "否"] } };
runs.getRange("J4:J63").dataValidation = { rule: { type: "list", values: ["暂停等待人工", "跳过下一家", "重试一次"] } };
runs.getRange("K4:K63").setNumberFormat("0");
runs.getRange("L4:M63").dataValidation = { rule: { type: "list", values: ["是", "否"] } };

const guide = workbook.worksheets.add("填写说明");
const guideRows = [
  ["填写顺序", "1. 先填“门店配置”中红色表头字段；2. 再填“规则参数”；3. 最后按当天需要选择“执行批次”。"],
  ["美团切店", "建议优先使用“搜索门店名”。如果后台搜索结果名字容易混淆，就把“匹配严格度”设为“人工确认”。"],
  ["门店名称_后台显示", "填页面切换后顶部展示的完整门店名。脚本切店后会用它做校验。"],
  ["搜索关键词/别名", "填美团切店搜索框里最容易命中的词。多个别名可用 / 分隔。"],
  ["规则组", "门店配置里的规则组要和规则参数里的规则组一致，比如 默认、高客单、低余额、新店。"],
  ["预算和出价", "如果第一版只调整预算，就可以暂时不填出价相关列；如果要同时调出价，再补齐出价上下限。"],
  ["保存前确认", "第一版建议用“保存前逐店确认”，跑稳后再改为“自动保存”。"],
  ["失败处理", "第一版建议“暂停等待人工”，避免错店、弹窗、余额异常时继续执行。"],
  ["截图记录", "建议开启，后续排查“哪家店改了什么”会方便很多。"],
  ["你可以补充", "如果某家店有特殊规则，直接写在备注里，我会在做自动化时把它变成规则字段。"],
];
writeSheet(guide, {
  headers: ["主题", "说明"],
  rows: guideRows,
  widths: [160, 760],
  titleText: "填写说明",
  subtitle: "这份表是给第一阶段自动化准备的配置底稿：先保证门店能准确切换，再逐步把计算规则程序化。",
  requiredCount: 0,
});

await fs.mkdir(outputDir, { recursive: true });

for (const sheetName of ["填写说明", "门店配置", "规则参数", "执行批次", "字典"]) {
  await workbook.render({ sheetName, autoCrop: "all", scale: 1, format: "png" });
}

const inspect = await workbook.inspect({
  kind: "table",
  range: "门店配置!A1:AE8",
  include: "values,formulas",
  tableMaxRows: 8,
  tableMaxCols: 31,
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
