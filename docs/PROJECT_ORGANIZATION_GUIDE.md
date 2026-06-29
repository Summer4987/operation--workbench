# New project 整理指南

更新时间：2026-06-29

这份文档用于指导 `New project` 后续整理。当前工作区不是单一应用，而是一组围绕熊小小运营、推广、订货、库存、巡检和 AI 业务中心的工具集合。整理目标是让代码、入口、运行数据和生产边界更清楚，而不是一次性大规模挪目录。

## 整理原则

- 先文档化，再移动文件；先确认有效成果，再清理旧产物。
- Mac mini 是唯一生产主机；生产部署只从 GitHub `main` 拉取已验证代码。
- 不移动、不删除浏览器 profile、日志、下载数据、本地数据库和平台导出文件，除非已经确认是可再生垃圾。
- 名字带 ` 2` 的重复文件默认不提交；只有确认与原文件完全相同或无业务价值后才清理。
- 高风险动作相关脚本必须保留预览/模拟和正式执行的边界说明。
- 整理代码、脚本、看板或配置后，验证通过再提交并推送到 GitHub。

## 当前分区

| 区域 | 目录/文件 | 定位 | 整理动作 |
| --- | --- | --- | --- |
| 工作台入口 | `index.html`、`workbench.js`、`workbench.css`、`workbench-data.js` | 本地/云端运营工作台 | 源码保留根目录；生成数据继续忽略 |
| 经营日报 | `business-report-dashboard/` | 报表下载、清洗、经营看板 | 先处理未提交看板改动，再决定是否拆分运行数据 |
| 订货系统 | `daily-order/` | 日配订货、成都门店订货、北京门店订货 | 保持独立模块，生产部署文件留在 `deploy/` |
| 库存系统 | `inventory-board/` | 库存看板、出库单、云端同步 | 保持独立模块，本地数据库不进 Git |
| 巡检系统 | `store-inspection/` | 饿了么/美团余额和页面巡检 | 运行结果和 latest 数据继续忽略 |
| 上午运营 | `morning-ops/` | 上午统一采集入口 | 保留为定时任务聚合层 |
| 推广自动化 | `dianjin-prototype/`、`scripts/*dianjin*`、`scripts/*promo*` | 点金、预算、推广建议/执行 | 先统一“预览、审批、执行”命名 |
| AI 业务中心 | `ai-business-center/`、`config/ai_business_center_tasks.json` | 任务注册、健康监控、业务中心骨架 | 保留状态目录忽略规则 |
| 文档 | `docs/`、`PROJECT_TREE.md`、`SOURCE_DATA_SYNC.md` | 交接、架构、整理说明 | 后续逐步合并重复说明 |
| 临时/运行输出 | `outputs/`、`output/`、`business-report-dashboard/data/`、日志 | 运行产物、截图、证据 | 不提交，按业务价值单独归档或清理 |

## 建议目录边界

短期内不建议为了“好看”强行重排。更稳的边界是：

```text
New project/
├── ai-business-center/              AI 业务中心程序
├── business-report-dashboard/       经营日报和直营日报看板
├── daily-order/                     日配/门店/北京门店订货服务
├── inventory-board/                 库存和出库单系统
├── store-inspection/                余额、评价、平台页面巡检
├── morning-ops/                     上午统一采集入口
├── dianjin-prototype/               饿了么点金原型界面
├── sales-receipt-generator/         销售单据生成工具
├── order-preview/                   订单和异常流程原型
├── scripts/                         跨模块自动化脚本
├── config/                          非敏感配置和配置模板
├── docs/                            文档、交接和整理指南
├── tests/                           自动化测试
├── data/                            轻量源数据和模板
├── outputs/                         本地运行输出，忽略
└── output/                          少量生成文件，逐项确认
```

## 可立即做的整理

1. 更新项目地图
   - 用本文档作为新的整理入口。
   - 后续再把 `PROJECT_TREE.md` 更新为更精简的“模块地图”，避免和 `docs/` 里的细文档重复。

2. 处理当前未提交改动
   - `business-report-dashboard/dashboard/` 和 `business-report-dashboard/direct-dashboard/`：确认是否是最新有效看板。
   - `scripts/build_workbench_data.py`：确认是否是工作台数据生成的有效改动。
   - `scripts/run_eleme_automation.zsh`：确认演练/正式执行边界是否清楚。
   - `output/pdf/store_order_login_sheets.pdf`：确认是否应提交；如果是登录资料或敏感材料，不提交。

3. 清理明显本地垃圾
   - 已清理 `.DS_Store`、`__pycache__`、`.pytest_cache`、临时渲染草稿。
   - `eleme_balance*`、`meituan_balance*`、`meituan_find*`、`meituan_promo_ready*`、`chrome_restore_popup*`、`eleme_account_branch*` 这类自动化调试截图和 OCR 缓存默认无业务保存价值，由 `scripts/cleanup_operation_data.zsh` 即时清理。
   - 下一步只在确认后清理旧截图、旧 PDF 提取物、无价值调试图片。

4. 固化根目录入口
   - 根目录 `.command` 只保留常用生产/交接入口。
   - 模块内 `.command` 保留在各自模块目录。
   - 不在 MacBook 安装正式 `launchd` 定时任务。

## 暂不建议做的整理

- 不把 `business-report-dashboard/chrome-profile/` 移走；这可能影响浏览器登录态。
- 不删 `outputs/`；里面有巡检证据、视觉验证、发布校验和运行结果。
- 不合并所有脚本到单一大入口；当前跨平台和跨业务风险不同，先保持模块边界。
- 不把生产真实配置上传 GitHub；真实账号、Cookie、Token、验证码、私钥仍只保留在本地或服务器环境。

## 后续整理顺序

### 第一阶段：文档和索引

- 新增本整理指南。
- 更新模块地图。
- 列出当前未提交改动的来源和处理建议。

### 第二阶段：有效改动入库

- 验证看板、脚本和配置改动。
- 只暂存本次确认有效的文件。
- 提交并推送到 GitHub。

### 第三阶段：运行产物归档

- 按月份或任务类型归档 `outputs/` 中仍有价值的证据。
- 清理过期截图、重复调试文件和空目录。
- 保留最近一次发布、巡检、预算、订货相关证据。

### 第四阶段：入口瘦身

- 根目录只保留最常用入口。
- 把低频入口迁回模块目录或记录到文档。
- 给每个正式入口标注“预览/正式/生产主机限定”。

### 第五阶段：模块拆分评估

- 如果某个模块已经稳定并独立部署，再考虑拆成单独仓库。
- 拆分前必须确认 Mac mini、云服务器、GitHub Actions 或手动部署路径不会断。

## 提交前检查清单

- `git status --short` 中没有无关文件混入。
- 没有提交浏览器 profile、日志、本地数据库、平台导出、下载结果。
- 没有提交名字带 ` 2` 的重复文件。
- 没有提交真实密钥、Cookie、Token、验证码、私钥。
- 高风险动作仍默认预览或需要人工确认。
- 验证命令已运行，或说明本次只改文档无需运行程序测试。
