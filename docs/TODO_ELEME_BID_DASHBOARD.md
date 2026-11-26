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

## 实现与发布

- 入口：`/operation-workbench/#eleme-bidding`，沿用正式工作台原有登录权限。
- `scripts/eleme_bid_dashboard.py` 只读投影状态及当天事件（含轮转文件），由 `build_workbench_data.py` 打包进工作台并生成 `outputs/eleme_bid_dashboard/latest.json`。
- `eleme-bidding.js` 每分钟读取已发布数据，每 15 秒重算过期状态。过期/跨日/更新失败只显示快照读数，模拟结果单独标明；事件缺失或损坏明确提示历史不完整。
- `deploy_workbench_to_cloud.zsh` 的 data-only 模式同步独立页面脚本和数据，并校验远端哈希。新路径沿用工作台保护范围，不开放匿名访问。
- Mac mini 拉取已验证 main 后，运行 `scripts/install_workbench_publisher.zsh` 仅更新正式发布包装脚本，再以 `OPERATION_CLOUD_DEPLOY_MODE=data-only` 运行该包装脚本；不重装 launchd，不触发调价执行。
- 验证：`python3 -m unittest discover -s tests -p test_eleme_bid_dashboard.py`、`node tests/test_eleme_bidding_ui.cjs`。
