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

要做真正的企业微信对话入口，需要企业微信自建应用回调。当前已新增云端回调入口：

- URL：`http://139.155.148.169/agent-wecom/callback`
- Token：配置到云服务器 `/etc/inventory-board.env` 的 `WECOM_AGENT_CALLBACK_TOKEN`
- EncodingAESKey：配置到云服务器 `/etc/inventory-board.env` 的 `WECOM_AGENT_ENCODING_AES_KEY`
- CorpID：可选；如果要校验接收方，可配置到云服务器 `/etc/inventory-board.env` 的 `WECOM_AGENT_CORP_ID`

回调服务负责企业微信 URL 验证、消息签名校验、AES 解密和被动文本回复。它优先读取云端最新的 `operation-workbench/outputs/agent_mobile/latest.json`，所以能回答“任务正常吗 / 今天哪里失败 / 哪些能补跑 / 执行 Agent 是谁”。

## Mac mini 执行桥接

已新增云端收件箱和 Mac mini 轮询 worker：

- 云端收件箱接口：`/agent-wecom/inbox/pending`、`/agent-wecom/inbox/claim`、`/agent-wecom/inbox/complete`
- 收件箱 Token：配置到云服务器 `/etc/inventory-board.env` 的 `AGENT_INBOX_TOKEN`
- Mac mini 本地 Token：配置到 `~/.xiong-agent-env` 的 `AGENT_INBOX_TOKEN`
- Mac mini worker：`scripts/agent_inbox_worker.py`
- Mac mini launchd 安装脚本：`scripts/install_agent_inbox_worker_launchd.zsh`

企微里以下话术会进入 Mac mini 队列：

- `刷新状态`：刷新 agent 状态和手机入口数据。
- `重跑预算设置`：只跑预算预览/安全计划，不真实提交预算。
- `确认执行预算重跑`：进入真实预算提交流程，但仍受原脚本时间窗口、登录态和安全闸保护。
- `发布手机入口`：发布手机入口和工作台数据。
- `执行非订货恢复`：只执行允许的非订货动作。

当前边界：

- 订货、下单、采购、快驴相关请求继续拦截。
- 普通“重跑预算设置”只做预览；真实预算提交必须说确认语。
- Mac mini 执行结果会通过现有企业微信通知通道回报。

## 智能程度边界

Agent 的回答分两层：

- 本地规则先读取真实状态文件，生成确定性草稿。
- DeepSeek 可用时，只基于草稿和结构化上下文改写成更自然的回答。

DeepSeek 是 advisory-only，不允许单独决定生产动作。模型不可用、超时或置信度低时，会自动退回本地规则答案。
