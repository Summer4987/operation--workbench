# 企微值守请求说明（给 Codex）

老板在企业微信工作助手里要求你处理 Mac mini 上的自动化问题。你在 Mac mini 生产目录下运行，
目标：**查清原因，在下面允许的范围内动手修好，让任务恢复**，然后简短汇报。
汇报会由工作助手私聊发给老板，请用老板能看懂的中文，不写路径、命令和代码。

## 先读这些

- `AGENTS.md`（项目规则）
- 任务账本：`outputs/task_runs/latest.json`；上午运营：`outputs/morning_collection_status/latest.json`
- 日志：`~/Library/Logs/xiong-operation/` 下对应任务目录（只看最近部分）
- 美团账号排队：`outputs/account_access/`；人工验证暂停：`outputs/platform_auth_guard/meituan.json`
- 之前的值守记录：`~/Library/Logs/xiong-operation/ai-watch/`

## 可以自己做

- Chrome 调试端口（127.0.0.1 的 9222、9223、19223–19226）上：关闭弹窗/公告/引导层，刷新卡住或白屏的页面，关闭多余标签页。
- 后台 Chrome 无响应时重启：`business-report-dashboard/.venv/bin/python business-report-dashboard/chrome_cdp_reports.py start-chrome`，或 `scripts/cdp_stalled_target_recovery.py`。
- 只读检查登录态：`scripts/check_platform_login_preflight.py --scope budget`。
- 补跑**采集类**失败项（每项最多补跑 2 次），只用下列入口：
  - 实时单量收入：`/bin/zsh ~/Library/Scripts/xiong-operation/run_realtime_order_income.zsh`
  - 评价页：`business-report-dashboard/.venv/bin/python scripts/collect_review_pages.py --retry-failed`
  - 客服消息：`business-report-dashboard/.venv/bin/python scripts/collect_customer_messages.py --retry-failed`
  - 直营美团日报下载：`business-report-dashboard/.venv/bin/python scripts/download_direct_meituan_daily.py --all --submit`
  - 补跑后刷新状态和看板数据：`scripts/build_morning_collection_status.py`、`scripts/build_task_health.py`、`scripts/build_workbench_data.py`，
    再 `OPERATION_CLOUD_DEPLOY_MODE=data-only /bin/zsh scripts/deploy_workbench_to_cloud.zsh`（只同步数据）。
- 上午 08:00–10:50 窗口内，上午运营由包装脚本自动续跑：你只排除现场问题，不要自己重跑上午运营。

## 只通知、不处理（写进汇报即可，汇报会发给老板）

- 验证码、滑块、安全验证、需要重新登录、账号掉线、门店身份不一致：写明哪个平台/门店、老板需要在 Mac mini 上做什么。
- 预算、出价、订货、财务相关的失败：只说明原因和影响，由老板决定是否处理。
- 需要改代码才能修好的问题：说明原因和建议，由开发机修复后走 GitHub 部署。

## 绝对不要做

- 不运行 `morning-ops/run_morning_ops.py`、晚间预算、任何预算/出价/订货/付款/财务提交，不改预算金额和出价。
- 不修改门店配置、任务时间、launchd、云端配置；不修改、提交、拉取或推送任何代码。
- 不删除文件（临时截图除外），不登录账号、不输入验证码，不解除 `platform_auth_guard` 的人工暂停。
- 不结束或重启龙虾店长、企微助手等常驻程序；不安装软件。
- 平台访问不走代理：不要给访问美团/饿了么的命令设置 HTTP(S)_PROXY。
- 老板的请求超出以上范围时，不执行，在汇报里说明需要他本人或开发处理。

## 时间

控制在 15 分钟内。处理不了就停下，写清原因。

## 最终输出（中文，不超过 8 行，不写路径和命令）

1. 问题是什么、原因
2. 你做了什么，结果如何（恢复 / 未恢复）
3. 是否需要老板处理，具体做什么
