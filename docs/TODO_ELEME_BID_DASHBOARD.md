# 待办（交给 Codex）：运营看板“淘宝闪购调价”页面

老板要求在运营看板推广中心新增“淘宝闪购调价”页，放在“龙虾店长调价预览”旁边，菜单与内页同名。

## 数据来源（已就绪，只读）

- Mac mini 生产目录 `outputs/eleme_bid_fleet/latest.json`：由 `Summer4987/dianjin-mac` 的 `scripts/eleme-fleet.mjs` 每 5 分钟写入。
  字段：`generatedAt`、`day`、`error`、`nextCheckAt`、`stores[]`（`shopId`、`name`、`bid`、`spend`、`platformBudget`、`expected`、`gap`、`action`、`reason`、`before`、`after`、`state`、`message`）。金额单位为分。
- 完整调价记录：Mac mini `~/Library/Application Support/xiong-eleme-fleet/eleme-fleet-events.jsonl`（每行一条，`type` 为 `decision`/`adjusted`/`error`/`skip`/`recalibrate`，含 `at`、`name`、`action`、`reason`、`before`、`after`、`expected`、`actual`）。

## 页面要求

- 每店一行：当前出价、今日花费、此刻计划花费、差距（快/慢多少元）、最近一次调价（时间、从多少到多少、原因）、下次检查时间、状态（正常/阻止/待核对/读取失败）。
- 可按门店展开当天全部调价记录（含“保持”的原因）。
- 顶部显示数据生成时间；超过 15 分钟未更新标“数据过期”，不要显示旧数为当前值。
- 推广时段外显示“非推广时段（10:30–12:30、17:00–20:00）”。
- 按 AGENTS.md：随 `build_workbench_data.py` 打包、data-only 发布；正式入口权限与其他推广页一致；完成后部署并验证线上链接。
