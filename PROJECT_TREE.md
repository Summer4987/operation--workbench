# 项目总览树

更新时间：2026-06-05

这个工作区现在更像一个“小型业务工具箱”，不是单一代码项目。建议以后按业务线理解和推进：经营数据、库存出库、点金推广、采购/订货原型。

## 一、当前项目树

```text
New project/
├── morning-ops/                      上午运营统一采集入口
│   ├── run_morning_ops.py            串联日报、饿了么余额、美团余额
│   ├── run_morning_ops_if_10am.command
│   ├── 上午运营一键采集.command
│   ├── 安装10点上午运营采集.command
│   ├── install_launchd.zsh           安装每天 10:00 自动启动
│   └── logs/                         统一采集日志
│
├── business-report-dashboard/        经营日报看板
│   ├── dashboard/                    生成出来的本地网页看板
│   ├── data/
│   │   ├── raw/                      原始饿了么 / 美团报表
│   │   ├── latest.json               看板当前使用数据
│   │   └── unified_daily.csv         统一后的日报明细
│   ├── logs/                         自动任务日志
│   ├── process_reports.py            报表清洗和看板生成主脚本
│   ├── chrome_cdp_reports.py         通过常用 Chrome 辅助下载报表
│   ├── download_reports.py           早期独立浏览器下载方案
│   ├── run_dashboard.command         双击运行看板
│   ├── run_daily.command             日报自动处理入口
│   └── README.md                     项目说明
│
├── inventory-board/                  库存看板 / 出库单生成系统
│   ├── app/                          后端逻辑
│   │   ├── main.py                   网页接口主入口
│   │   ├── parser.py                 入库 / 出库 Excel 解析
│   │   ├── order_generator.py        微信订货生成出库单
│   │   ├── db.py                     库存数据库逻辑
│   │   └── catalog.json              商品目录
│   ├── static/                       前端页面
│   │   ├── index.html                库存看板首页
│   │   └── order-submit.html         门店提交订货页面
│   ├── data/
│   │   └── inventory.sqlite3         本地库存数据库
│   ├── deploy/                       腾讯云部署文件
│   ├── scripts/                      自动同步 / 自动上传脚本
│   ├── 启动自动上传.command
│   ├── 同步云端出库单到本地.command
│   └── README.md                     项目说明
│
├── dianjin-prototype/                饿了么点金推广自动化原型
│   ├── index.html                    点金任务清单页面
│   ├── app.js / logic.js             页面交互和任务逻辑
│   ├── rules.js                      点金规则数据
│   ├── current_state.js              当前后台状态数据
│   ├── execution_preview.js          执行预览数据
│   ├── automation_config.json        自动化配置
│   ├── 刷新规则数据.command
│   ├── 生成饿了么试运行.command
│   ├── 探测饿了么页面.command
│   ├── 探测饿了么门店.command
│   ├── 演练饿了么执行.command
│   ├── 安装饿了么自动化演练.command
│   ├── 卸载饿了么自动化.command
│   └── 查看饿了么自动化日志.command
│
├── order-preview/                    采购 / 订货后台界面预览
│   ├── dashboard.html                采购后台总览预览
│   ├── form.html                     门店提交表单预览
│   ├── wechat.html                   微信订货相关预览
│   ├── exceptions.html               异常处理页面预览
│   ├── styles.css                    页面样式
│   └── screenshots/                  截图资料
│
├── store-inspection/                 门店线上巡检
│   ├── index.html                    巡检结果页
│   ├── config.json                   巡检时间、平台、阈值配置
│   ├── chrome_config.json            日常 Chrome 巡检模式配置
│   ├── latest.json                   最新巡检结果
│   ├── latest-data.js                可直接打开页面使用的巡检数据
│   ├── inspect_promo_balance.py      饿了么推广余额采集脚本
│   ├── ocr_image.swift               macOS Vision 截图文字识别
│   ├── parse_balance_ocr.py          余额表 OCR 解析
│   ├── screen_tool.swift             屏幕点击 / 滚动辅助
│   ├── one_click_eleme_balance.py    饿了么余额巡检流程
│   ├── one_click_meituan_balance.py  美团逐店余额巡检流程
│   ├── run_all_balances.py           饿了么 + 美团余额总巡检
│   ├── 一键饿了么余额巡检.command
│   ├── 打开一键巡检权限设置.command
│   ├── 启动日常Chrome巡检模式.command
│   ├── 打开饿了么余额页登录.command
│   ├── 用日常Chrome打开饿了么余额页.command
│   ├── 运行饿了么余额巡检.command
│   ├── 安装10点15余额巡检.command
│   ├── install_launchd.zsh
│   ├── app.js                        巡检页面交互
│   └── styles.css                    巡检页面样式
│
├── scripts/                          点金相关生成和自动化脚本
│   ├── build_dianjin_config_template.mjs
│   ├── build_ele_dianjin_rules.mjs
│   ├── build_execution_preview.mjs
│   ├── eleme_dianjin_adapter.mjs
│   ├── enrich_ele_rules_from_probe.mjs
│   ├── export_current_state_for_ui.mjs
│   ├── export_ele_rules_to_json.mjs
│   ├── install_eleme_launchd.zsh
│   ├── run_eleme_automation.zsh
│   └── uninstall_eleme_launchd.zsh
│
├── outputs/                          生成结果 / 探测结果 / 日志
│   ├── ele_dianjin_rules/            点金规则配置表
│   ├── diangjin_config_template/     点金门店配置表
│   └── dianjin_automation/           点金探测、演练、执行预览、日志
│
├── docx_media/                       文档对比时解出的图片资料
├── docx_render/                      文档渲染检查资料
├── pdf_pages/                        PDF 页面图片
├── outputs/pdf_extract/              PDF 提取中间结果
├── docx_extracted.txt                文档提取文本
├── pdf_extracted.txt                 PDF 提取文本
├── pdf_vs_docx_pdf_text.txt          PDF / Word 对比文本
├── index.html                        门店运营工作台首页
├── workbench.css                     工作台样式
├── workbench.js                      工作台交互
├── 上午运营一键采集.command           统一一键入口
├── 安装10点上午运营采集.command       统一定时安装入口
└── PROJECT_TREE.md                   本文件
```

## 二、项目分组和定位

### 1. 经营日报看板

目录：`business-report-dashboard/`

用途：把饿了么 Excel 和美团 CSV 统一清洗，生成门店经营日报看板。

当前状态：

- 已能处理下载好的报表。
- 已有本地网页看板。
- 已有自动识别最新报表、门店映射、目标门店过滤。
- 正在向“自动登录 / 自动下载 / 定时日报”发展。

建议下一步：

1. 稳定自动下载流程。
2. 给每日任务增加“成功 / 失败提醒”。
3. 把看板从本地 HTML 升级成可长期访问的网页服务。
4. 加历史趋势、门店排名、异常门店提醒。

优先级：高。它直接影响每天经营复盘。

### 2. 库存看板 / 出库单系统

目录：`inventory-board/`

用途：上传入库 / 出库 Excel，自动计算库存；支持微信群订货识别、门店提交链接、生成出库单、云端部署。

当前状态：

- 已有后端接口和前端页面。
- 已支持入库、出库、库存预警。
- 已支持门店提交链接。
- 已有腾讯云部署脚本。
- 已有 Mac 自动上传、云端出库单同步。

建议下一步：

1. 明确“本地版”和“云端版”哪个是主版本。
2. 给商品目录和门店信息做网页维护入口。
3. 加每日库存变动报表。
4. 加低库存自动提醒。
5. 做一次云端备份方案，避免数据库丢失。

优先级：高。它已经接近正式业务系统。

### 3. 门店线上巡检

目录：`store-inspection/`、`morning-ops/`

用途：每天上午统一启动日报采集和线上巡检，把饿了么、美团推广余额低于 100 元的门店显示在工作台。

当前状态：

- 已有饿了么余额巡检，路径为“立即充值 → 分店账户 → 账户明细及转账”。
- 已有美团逐店余额巡检，路径为“门店推广 → 推广首页 → 我的账户”。
- 已合并成 `run_all_balances.py`，结果统一写入巡检页。
- 已合并到 `morning-ops/`，每天 10:00 与日报一起自启动。

下一步：

1. 补齐饿了么余额页的完整门店导出，减少截图分页遗漏。
2. 增加“活动是否正常”“待处理评价”两项巡检。
3. 给巡检失败增加更醒目的工作台提示。

优先级：高。它直接承担每天上午的异常发现。

### 4. 饿了么点金推广自动化

目录：`dianjin-prototype/`、`scripts/`、`outputs/dianjin_automation/`

用途：根据门店、时段、预算、消耗情况，生成点金推广任务，并尝试做后台探测、演练和自动执行。

当前状态：

- 已有任务清单原型页面。
- 已有规则配置表生成脚本。
- 已有后台页面探测、门店探测、执行预览、演练日志。
- 已有定时任务安装 / 卸载脚本。
- 仍处于“谨慎演练 + 验证选择器稳定性”的阶段。

建议下一步：

1. 固化配置表字段和门店规则。
2. 把“演练模式”和“真实执行模式”严格分开。
3. 给每次执行生成可读报告：做了什么、跳过什么、失败什么。
4. 先只开放单门店、单时段真实执行，再扩大范围。
5. 增加执行前确认和预算上限保护。

优先级：中高。收益明显，但需要安全边界。

### 5. 采购 / 订货后台预览

目录：`order-preview/`

用途：采购、门店提交、异常处理等界面方向的静态预览。

当前状态：

- 目前更像视觉和流程原型。
- 还没有接入真实数据或后端。
- 与 `inventory-board/` 的“门店提交”和“出库单生成”方向有重叠。

建议下一步：

1. 决定是否并入 `inventory-board/`。
2. 如果保留，明确它是“采购系统”还是“库存系统的采购模块”。
3. 把静态预览里最有价值的页面转成真实功能。

优先级：中。适合在库存系统稳定后整合。

## 三、工作台推进方向

当前不按短期 / 中期 / 长期拆，统一按门店运营工作台推进：

```text
运营后台
├── 经营日报
├── 推广
├── 门店巡检
└── 库存看板
```

全部都按紧急任务处理：

1. 门店日报：继续稳定 10:00 自动采集、上传和异常门店展示。
2. 推广：点金自动化继续演练，逐步接入美团切店预算动作。
3. 门店巡检：余额巡检已先合并，下一步补活动状态和待处理评价。
4. 库存看板：保持云端提交和本地同步可用，再补低库存提醒。

## 四、建议整理动作

暂时不建议马上大搬家，因为几个项目之间还有脚本和输出文件互相引用。更稳的整理顺序是：

1. 先保留当前目录结构。
2. 给每个项目补齐 README。
3. 把临时产物统一放入 `outputs/`。
4. 等功能边界稳定后，再迁移成更标准的结构。

未来可以整理成：

```text
New project/
├── apps/
│   ├── business-report-dashboard/
│   ├── inventory-board/
│   ├── dianjin-prototype/
│   └── order-preview/
├── shared/
│   └── store-config/
├── outputs/
├── docs/
│   └── PROJECT_TREE.md
└── archive/
```

## 五、当前最值得推进的方向

如果按投入产出排序，我建议：

1. `inventory-board/`：先变成稳定正式系统。
2. `business-report-dashboard/`：接上稳定自动日报。
3. `dianjin-prototype/`：继续小范围演练，等规则和后台探测都稳定后再真实执行。
4. `order-preview/`：暂时作为设计参考，后面并入库存或采购模块。
