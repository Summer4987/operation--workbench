# Hermes/Mac mini 自动化任务透明化方案

更新时间：2026-06-30

## 目标

建立一个最小可验证的本地监控/报告 MVP，让 Hermes 或 Mac mini 上的自动化任务结果可以被快速读懂：

- 读取 `outputs/task_health/latest.json` 和 `outputs/task_runs/latest.json`。
- 输出每个任务的完成、失败、失败原因、证据路径、人工动作和是否建议补跑。
- 生成 JSON 报告和微信可读文本。
- 只生成 dry-run 补跑计划，不直接执行生产任务。
- 明确高风险任务只报告，不自动补跑。

## 文件边界

- 脚本：`scripts/agent_task_monitor.py`
- 策略配置：`ai-business-center/config/notification_tasks.json`
- 本地输出：`outputs/agent_task_monitor/latest.json` 和 `outputs/agent_task_monitor/latest.txt`

`outputs/` 已被 Git 忽略，适合保留 Mac mini 本地运行结果、日志和通知文本，不上传 GitHub。

## 安全策略

补跑分三类：

- `auto_allowed: true`：只读或幂等任务，允许进入 dry-run 补跑计划。
- `auto_allowed: false` + `mode: report_only`：只报告，不执行。
- `risk: high`：无论配置如何，脚本都会强制只报告，不自动补跑。

当前允许进入 dry-run 补跑计划的任务：

- `ops.realtime_order_income`：实时单量和营业额采集，采集和工作台数据生成可重复执行。
- `growth.promo_balance`：推广余额巡检，只读采集，不充值。
- `flow.inventory`：库存云端健康检查，只读探测。
- `tools.sales_receipt`：销售单工具本地校验，不触碰平台。

当前只报告、不自动补跑的任务：

- `ops.morning_collection`：上午一键采集串联推广预算和发布，高风险。
- `ops.daily_report`：涉及平台下载和看板发布，需人工确认登录态和发布时间。
- `growth.promo_budget`：可能保存推广预算，高风险。
- `growth.promo_bid`：出价调整必须审批，高风险。
- `flow.auto_ordering`：订货可能产生下单或付款风险，高风险。
- `tools.franchise_contract`：合同条款需要人工确认。

## 输出格式

JSON 报告包含：

- `summary`：总数、完成、失败、关注、未记录、补跑建议数量。
- `tasks`：每个任务的状态、失败原因、证据、人工动作和补跑判断。
- `rerun_plan`：建议补跑任务列表，全部为 dry-run plan。
- `wechat_text`：可直接发送到微信的文本。

微信文本重点展示：

- 总体完成/失败/关注数量。
- 失败或需关注任务。
- 失败原因和人工动作。
- 哪些任务可以补跑，哪些只能报告。

## 本地验证

生成报告：

```bash
python3 scripts/agent_task_monitor.py
```

只打印摘要、不写文件：

```bash
python3 scripts/agent_task_monitor.py --no-write
```

查看微信文本：

```bash
sed -n '1,120p' outputs/agent_task_monitor/latest.txt
```

Hermes/微信入口：

```bash
./scripts/hermes_business_center.zsh 自动化报告
./scripts/hermes_business_center.zsh 任务报告
```

入口会刷新 `outputs/agent_task_monitor/latest.json` 和 `latest.txt`，然后返回微信可读文本。

生成补跑 dry-run 计划：

```bash
python3 scripts/agent_rerun_dry_run.py
```

这个执行器只读取 `rerun_plan` 并输出“如果补跑会执行什么”，不会真正执行命令；高风险任务会被强制归入只报告。

## 任务结束后调用方式

新接入的 Mac mini 自动化任务建议通过通用包装器运行：

```bash
python3 scripts/agent_task_wrapper.py ops.realtime_order_income -- /bin/zsh scripts/run_realtime_order_income.zsh
```

包装器会：

- 在任务开始时写入 `outputs/task_runs/latest.json` 的 `running` 状态。
- 任务退出后按退出码写入 `success` 或 `failed`，失败时记录退出码和失败分类。
- 任务结束后刷新 `outputs/task_health/latest.json` 和 `outputs/agent_task_monitor/latest.json` / `latest.txt`。
- 不安装 launchd，不执行额外生产动作；正式定时任务仍只在 Mac mini 从 GitHub `main` 拉取后配置。

已有任务若已经手写了状态记录，也可以只在结束后调用：

```bash
python3 scripts/build_task_health.py
python3 scripts/agent_task_monitor.py
python3 scripts/agent_rerun_dry_run.py
```

## 后续接入建议

1. Mac mini 定时任务结束后调用 `python3 scripts/agent_task_monitor.py`，刷新本地报告。
2. Hermes 读取 `outputs/agent_task_monitor/latest.txt` 作为微信通知正文。
3. 若要做真实补跑，必须另建独立执行器读取 `rerun_plan`，并继续保留高风险任务人工确认闸；当前 `agent_rerun_dry_run.py` 不执行任何命令。
4. 对 `report_only` 任务只发送失败原因、证据路径和人工处理建议。
