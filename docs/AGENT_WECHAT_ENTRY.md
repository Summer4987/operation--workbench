# Agent 企业微信入口说明

更新日期：2026-07-04

## 当前可用能力

Agent 现在可以把多 Agent 结果集合到企业微信群里：

- `scripts/agent_pipeline.py --notify`：每次运行结束都发送汇总。
- `scripts/agent_pipeline.py --notify-on-failure`：失败或执行 Agent 参与时发送汇总。
- `scripts/agent_command.py "问题" --notify`：把一次自然语言命令的结果发送到企业微信。
- `scripts/agent_notify.py`：统一的 Agent 通知格式入口。

企业微信 Webhook 只负责把消息发进群。当前默认通知通道是 `config/ops_notify.json` 里的企业微信机器人 Webhook；WorkBuddy/Hermes 已标记为 legacy，不再默认兜底。

## 不能直接做到的能力

普通企业微信群机器人 Webhook 不能接收群消息，也不能读取你在群里说的话。所以仅靠 Webhook，不能实现“在企业微信群里直接问 agent，agent 在群里自动回复”。

要做真正的企业微信对话入口，需要新增企业微信应用回调：

- 配置企业微信自建应用或客户联系回调。
- 云端提供 HTTPS 回调地址，用于接收消息、校验 token、解密消息。
- 回调服务把文本转给 `scripts/agent_command.py`。
- 只读问题直接回答；执行类问题仍要求显式确认，并继续拦截订货/下单/采购。

## 智能程度边界

Agent 的回答分两层：

- 本地规则先读取真实状态文件，生成确定性草稿。
- DeepSeek 可用时，只基于草稿和结构化上下文改写成更自然的回答。

DeepSeek 是 advisory-only，不允许单独决定生产动作。模型不可用、超时或置信度低时，会自动退回本地规则答案。

