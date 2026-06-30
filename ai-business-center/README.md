# AI 业务中心

这是业务中枢的旁路框架。它先不替换现有自动化，不迁移脚本，不改定时任务；只把现有能力登记成任务，并提供统一健康检查、运行记录和状态页。

## 当前中心

- 运营中心：自动化任务、运营看板、智能提醒、AI 运营建议。
- 推广中心：推广预算、出价调整、投产分析和执行审批。
- 货流中心：订货、库存、销量预测、缺货和滞销提醒。
- 加盟业务中心：合同、资料、流程清单、文档生成。

## 使用方式

在工程根目录运行：

```bash
python3 ai-business-center/center.py list
python3 ai-business-center/center.py health
python3 ai-business-center/center.py dashboard
python3 ai-business-center/center.py agent-status
```

如果要在干净 GitHub 副本中旁路检查生产目录的真实产物，可以指定生产根目录：

```bash
OPERATION_CENTER_ROOT="/Users/summer/Documents/New project" python3 ai-business-center/center.py health
OPERATION_CENTER_ROOT="/Users/summer/Documents/New project" python3 ai-business-center/center.py dashboard
```

这种方式只改变产物和脚本路径的检查根目录；状态文件仍然写入当前 `ai-business-center/state/`，不会写入生产目录。

生成每日守护报告：

```bash
OPERATION_CENTER_ROOT="/Users/summer/Documents/New project" python3 ai-business-center/guardian.py
```

守护器会同时运行系统体检、任务健康检查和状态页生成，并把 Markdown/JSON 报告写入当前 `ai-business-center/state/reports/`。

在 Mac mini 上安装每天 10:25 的守护报告定时任务：

```bash
./scripts/install_ai_center_guardian_launchd.zsh
```

这个定时任务只运行 clean 仓库里的守护器，并旁路读取生产目录；不会替换现有自动化任务。

生成的状态页在：

```text
ai-business-center/dashboard/index.html
```

手动执行单个登记任务：

```bash
python3 ai-business-center/center.py run ops.balance_inspection --timeout 420
```

## Hermes / 微信入口

Hermes 可以先通过只读桥接入口接入业务中心，用来回复微信里的“状态、任务列表、任务详情”这类问题：

```bash
python3 ai-business-center/center.py agent-status
python3 ai-business-center/center.py agent-commands
python3 ai-business-center/center.py agent-task ops.daily_report_publish
```

也可以直接调用独立桥接脚本：

```bash
python3 ai-business-center/agent_bridge.py status
python3 ai-business-center/agent_bridge.py list
python3 ai-business-center/agent_bridge.py task ops.daily_report_publish
python3 ai-business-center/agent_bridge.py commands
```

给 Hermes 配工具调用时，推荐使用固定 shell 入口：

```bash
./scripts/hermes_business_center.zsh status
./scripts/hermes_business_center.zsh 任务列表
./scripts/hermes_business_center.zsh 任务 ops.daily_report_publish
./scripts/hermes_business_center.zsh 命令
```

这个入口默认会刷新健康检查，但只读取文件和产物状态；不会自动执行预算、出价、订货、财务发布或云端发布。需要复用最近一次健康结果时，加 `--no-refresh`。

## 设计原则

- 先旁路监督，再逐步接管。
- 任何平台写操作都必须留日志和产物验证。
- 登录、验证码、安全验证不能伪装成成功。
- 健康检查不只看文件是否存在，还会验证 JSON/CSV/SQLite/HTML/JS 数据是否可解析、是否为空、是否声明失败。
- 预算、出价、订货、发布这类高风险动作，默认先做“建议 + 确认”，再逐步放开自动执行。
- 每个任务必须能回答四件事：今天有没有触发，跑到哪一步，产物是否真的更新，失败是否需要人工处理。

## 后续加注

下一步可以逐步加入：

- 每日定时健康巡检。
- macOS 通知或企业微信通知。
- AI 日报和异常解释。
- 推广预算/出价审批流。
- 库存预测和订货建议。
- 合同模板和加盟流程助手。
