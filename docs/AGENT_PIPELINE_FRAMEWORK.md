# 多 Agent 自动化框架

本框架把原来的脚本纳入 5 个低风险 agent：采集、校验、业务判断、通知、巡检。执行 Agent 只预留接口，默认禁用，不会自动提交预算、出价、订货、财务发布或云端发布。

## 入口

```bash
python3 scripts/agent_pipeline.py daily_automation_guard
```

只看会跑什么：

```bash
python3 scripts/agent_pipeline.py daily_automation_guard --dry-run
```

运行结果写入：

```text
outputs/agent_pipeline/daily_automation_guard/latest.json
outputs/agent_pipeline/daily_automation_guard/latest.txt
outputs/task_runs/latest.json
```

## 对话入口

可以用 `agent_chat.py` 直接问这些 agent 的运行结果：

```bash
python3 scripts/agent_chat.py "今天哪里有问题？"
python3 scripts/agent_chat.py "哪些任务可以补跑？"
python3 scripts/agent_chat.py "刚刚跳过的执行 Agent 是谁？"
python3 scripts/agent_chat.py --refresh "现在 agent 状态怎么样？"
```

`--refresh` 会先运行安全的 `daily_automation_guard`，但仍然不会启用执行 Agent。

回答会写入：

```text
outputs/agent_chat/latest.json
outputs/agent_chat/latest.txt
```

## Agent 职责

- 采集 Agent：运行只读采集或状态生成命令，把外部和本地运行信号整理成产物。
- 校验 Agent：检查关键 JSON、日志或报告是否存在且可解析，防止拿错数据继续往下走。
- 业务判断 Agent：读取已校验数据，生成异常、关注项、补跑建议和人工处理项。
- 通知 Agent：生成可以直接发送的纯文本通知。
- 巡检 Agent：复查本轮关键产物是否完整，给健康报告留痕。

## 接入新脚本

在 `config/agent_pipelines.json` 里给对应 stage 增加 `command` 和 `required_outputs` 即可。命令支持两个占位符：

- `{python}`：当前 Python 解释器。
- `{root}`：仓库根目录。

高风险动作不要放进默认 pipeline。确实需要执行时，必须单独设计审批、阈值、日志、截图和回查，再显式使用 `--allow-execution`。
