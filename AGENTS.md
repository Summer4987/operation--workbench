## GitHub 同步要求

- 后续所有有效代码、脚本、看板和配置改动，完成验证后都必须提交并推送到 GitHub。
- 后续所有修复完成验证并推送到 GitHub `main` 后，必须主动继续执行可触达环境的拉取、部署或安装更新步骤；不要把“再去 Mac mini 拉取/重新安装”留作用户第二步。若受登录态、权限、网络、远端冲突或生产安全边界限制无法自动完成，最终回复必须明确阻塞原因和用户下一步。
- 以后任何代码、脚本、看板或配置改动，最终回复用户“好了/完成/已上线”之前，必须已经完成生产主机部署并验证线上正式链接可用；不能只以“本地验证通过”或“已推送 GitHub”作为完成标准。
- 如果本地存在他人或其他 Mac 产生的改动，提交前先区分本次改动和既有改动；不要回滚他人改动。
- 如果因为登录、权限、网络或远端冲突导致无法推送，最终回复必须明确说明阻塞原因和需要用户处理的下一步。

## Mac mini 生产主机规则

- 这台 Mac mini 是唯一生产主机，负责真实运行自动化任务、正式定时任务、真实平台操作和生产发布。
- Mac mini 只运行 GitHub `main` 分支上的已验证代码；部署时只允许从 GitHub 拉取，不接受手动拷贝文件作为部署来源。
- MacBook/Codex 可以作为开发机进行开发、修改、预览和模拟；开发完成后必须提交并推送到 GitHub，再由 Mac mini 拉取部署。
- Mac mini 的浏览器登录态、Chrome profile、日志、下载数据、运行结果、运行截图、本地数据库和平台导出文件不上传 GitHub。
- 如果 Mac mini 本地出现未提交改动，先不要拉取或覆盖；必须先判断哪些是本机运行产物、哪些是有效代码、哪些是临时文件或重复文件。
- 所有文件名带 ` 2` 的重复文件默认不要提交；必须确认与原文件完全相同或确认无业务价值后，才能清理。
- 正式 `launchd` 定时任务只在 Mac mini 安装；MacBook 不安装正式定时任务，不执行生产预算、出价、订货或发布动作。
- 高风险动作，包括推广预算设置、出价调整、订货、财务发布和云端发布，必须区分预览/模拟与正式执行；没有明确要求时默认只做预览或健康检查。
- 涉及生产登录态、平台后台页面、Chrome/CDP、实时采集复查或恢复的操作必须在 Mac mini 上执行；MacBook/Codex 不得启动本机平台页面代替生产环境验证。

## 客服消息采集完成规则

- 三方群聊属于可选采集项。已确认是三方群聊的会话如遇正文读取、门店归属、历史完整性或附件采集失败，记录原因并跳过，不阻塞门店、客服采集或整个上午运营任务完成，也不因该项失败触发整项补跑。
- 成功读取的三方群聊可以保留；跳过不等于“当天没有消息”。普通顾客单聊、登录态、门店身份和会话列表覆盖校验仍按原规则判断，不能一并忽略。

## 订货链接命名约定

- `http://139.155.148.169/order-submit?token=xiongxiaoxiao-order` 正式名称为“熊小小日配订货”；后续用户说“日配订货”时，默认指这个链接。
- `http://139.155.148.169/daily-order/` 正式名称为“熊小小成都门店订货”；后续用户说“门店订货”时，默认指这个链接。
- `http://139.155.148.169/beijing-order/` 正式名称为“熊小小北京门店订货”；后续用户说“北京门店订货”时，默认指这个链接。

## 企微通知与 AI 值守（2026-11-26 起）

- 企微有两个入口，名称固定：
  - **通知助手**：企微群（原名 agent 群），群机器人 webhook。所有自动化通知都发到这里（`config/ops_notify.json` 的 `channel` 为 `webhook`）。
  - **熊小小工作助手**：企微官方智能机器人，用于老板问答和叫值守；日常问答用 DeepSeek。它自带的“运营异常”推送已关闭（`WECOM_OPS_ALERTS_ENABLED=0`），避免与通知助手重复。
- 所有通知统一经 `scripts/ops_notify.py` 发送，发送前由 `scripts/notify_text.py` 去掉文件路径、任务 ID、命令、报错堆栈和英文代码词；新增通知不要绕开它。通用格式为“结论 / 原因 / 下一步 / 时间”，不写日志路径、补跑命令和错误分类。每条发送记录在 `outputs/ops_notify/<日期>.jsonl`。
- 工作助手主动推送只支持 Markdown（会弹通知但不显示内容）和卡片（显示标题但不弹通知），因此通知不走工作助手；`WECOM_NOTIFY_FORMAT` 保持 `markdown`。
- **AI 值守（Codex）运行在 Mac mini**，命令行在 `~/Library/Application Support/xiong-operation/codex-cli/codex`，只通过本机代理 `127.0.0.1:7897`（launchd `com.summer.codex-proxy`，mihomo）访问 OpenAI；它执行的命令剔除代理变量，美团/饿了么保持国内直连。
  - 上午运营失败后、自动续跑前，由 `scripts/morning_ai_watch.zsh` 唤醒，规则见 `docs/MORNING_AI_WATCH.md`；每天最多 3 次。关闭：创建 `config/morning_ai_watch.disabled`。
  - 老板在工作助手发“值守：…”或由 DeepSeek 调用 `request_ai_watch`，后台运行 `scripts/ai_watch_request.zsh`，规则见 `docs/AI_WATCH_CHAT.md`；结果回到工作助手对话。开关 `WECOM_AI_WATCH_ENABLED`。
  - 两者共用锁 `outputs/ai_watch/lock`，同一时间只有一个 Codex。值守可关弹窗、重启 Chrome、补跑采集类任务；不碰预算、出价、订货、财务，不改配置和代码，不登录、不输验证码。
- 上午运营包装脚本设置 `MEITUAN_ACCOUNT_WAIT_SECONDS=480`：美团同账号排队时等龙虾店长一轮余额巡检结束，而不是 120 秒判失败。龙虾店长照常占用账号做余额巡检，不要为上午运营去限制它。
- 修改 `run_morning_ops.zsh` 的模板在 `scripts/install_macmini_operation_launchd.zsh`；部署时只重新生成该文件，不要为此重装全部 launchd。
- 2026-11-26 清理：10:25 的 `ai-center-guardian` 已退役（检查的是旧目录 `operation-workbench-clean`，报告失真），plist 与脚本归档在 `~/Library/LaunchAgents/retired-20261126/`、`~/Library/Scripts/xiong-operation/archive/retired-20261126/`，不要再用 `install_ai_center_guardian_launchd.zsh` 装回。Mac mini 上 Codex App 6 月建的三个定时自动化（09:00 上午运营、09:30 体检、17:30 晚餐预算）已暂停，它们会与 launchd 重复执行真实预算，不要恢复；定时任务只用 launchd。
- 美团登录约 30 天失效。`com.summer.operation.meituan-login-expiry` 每天 14:30（午晚高峰之间）只读检查各会话 token 到期时间（总部/直营 Chrome 与龙虾店长 16 个门店分区），剩余 ≤10 天时经通知助手提醒老板在 14:30–15:30 主动重新登录；≤5 天或已失效每天提醒。安装：`scripts/install_meituan_login_expiry_launchd.zsh`；结果 `outputs/meituan_login_expiry/latest.json`。
- 推广出价统一规则（2026-11-27 起，美团龙虾店长与淘宝闪购相同）：出价范围 0.30–1.00 元，开场价 0.50 元，常规按 0.10 元一档调整，花费差距大时单次最多 0.30 元。美团由龙虾店长 0.8.26（GitHub `Summer4987/dianjin-mac`，`core/engine.mjs` 的 `largeStep`、`core/runner.mjs` 的 `fleetOpeningBid`）与云端模板 minBid 30 / maxBid 100 执行；不要再用旧的 0.50/0.60/0.20 参数覆盖。
