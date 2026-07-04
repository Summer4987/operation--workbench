# Legacy Notification Channels

从 2026-07-04 起，Mac mini 运营自动化的主通知通道统一为企业微信 Webhook。

WorkBuddy 和 Hermes 只保留为历史兼容入口，不再作为默认通知 fallback，也不再用于新 agent 能力接入。

当前规则：

- 新通知只接 `scripts/ops_notify.py` 的企业微信 Webhook。
- `config/ops_notify.json` 不配置 Webhook 时，默认直接报错，不再自动调用 WorkBuddy/Hermes。
- 如需紧急临时回退，必须显式设置 `OPS_NOTIFY_ALLOW_LEGACY_FALLBACK=1`。
- 不删除旧文件和旧脚本，避免历史私人表格、旧业务桥接或未迁移命令突然断开。

清理前置条件：

- 企业微信 Webhook 连续稳定运行至少两周。
- `grep -R "hermes\\|workbuddy"` 确认剩余引用都不是生产通知主链路。
- 私人表格、财务草稿和旧业务桥接有替代入口。
