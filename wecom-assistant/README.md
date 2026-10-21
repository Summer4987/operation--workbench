# 熊小小企微工作助手

通过企业微信官方智能机器人长连接，在 Mac mini 上运行独立服务。

支持经营日报查询、日配/成都/北京订货只读查询、粘贴聊天总结、TXT/CSV/XLSX材料分析、Excel附件生成。只在已绑定老板账号的单聊中提供业务数据，不接管微信账号，不收集未发送给机器人的聊天，不执行订货、付款、推广或发布操作。

## 配置与部署

生产代码必须由 Mac mini 从 GitHub main 拉取到独立干净副本。不要覆盖已有生产目录的本地修改。

- Node >=22，`pnpm install --frozen-lockfile --ignore-scripts`。
- 企微凭据：`~/.config/wecom-assistant/.env`，文件权限 600，键 `WECOM_BOT_ID`、`WECOM_BOT_SECRET`。
- 模型复用 `~/.xiong-agent-env` 中的 `AGENT_LLM_API_KEY`、`AGENT_LLM_BASE_URL`、`AGENT_LLM_MODEL`。
- `.env` 使用简单 `KEY=value` 格式，解析器不会执行 shell。
- 可选 `WECOM_DATA_ROOTS` 为JSON路径数组，默认只读现有 production 和 operation-workbench-clean 目录；每种日报按生成时间选择最新数据。
- 云端订货通过现有 `~/.ssh/xiong_operation_cloud_ed25519` 读取固定目录，默认 SSH `ubuntu@139.155.148.169`；SQLite使用mode=ro，不调用写接口。
- `node app.mjs --smoke` 验证企微认证、模型调用、Excel生成和临时素材上传。不要与常驻实例同时运行，避免挤掉连接。
- 只在 Mac mini 上执行 `/bin/zsh install_macmini.zsh` 安装 launchd。
- 健康检查仅监听 `http://127.0.0.1:18769/health`，无公网管理页面。

首次部署后在 Mac mini 运行 `node app.mjs --pair-code` 获取绑定口令，在企微机器人单聊发送完整口令。口令有效期24小时，仅绑定一次，绑定后其他账号和群聊不能读取业务数据。需重新生成过期口令时，在服务停机后由管理员删除未绑定的 access.json 再启动，已绑定账号不要用此法重置。

会话上下文、账号绑定、消息去重、上传文件、Excel及健康状态保存在 `~/.local/share/xiong-wecom-assistant`，不进入GitHub。上下文保留最近12条消息。`清除本次记忆`仅清除当前私聊上下文，不删除上传原件和表格。按业务需要由管理员定期清理私人文件。

模型通过既有配置的API供应商处理用户发送的内容和相关业务查询结果；不发送完整聊天库，最多向模型提供400条查询明细，Excel可保留20000行完整明细。超过范围需缩小查询。

## 验证

`node --test test.mjs` 和 `python3 -m unittest discover -s . -p 'test_*.py'`。

正式交互验收：绑定后分别发送“帮助”“昨天经营概况”“今天北京门店谁未订货”“今天日配明细生成Excel”，并粘贴一段聊天要求提取待办。以真实企微回复及附件为准。

## 响应时间与余额

普通问答单次模型调用最多25秒，整个AI任务最多55秒，超时主动中止并回复重试提示。进度提示区分理解问题、读取数据、整理回答与生成文件；本机健康状态记录最近任务阶段和耗时，不记录消息正文。

老板私聊发送“模型余额”“余额”“模型额度”会直接查询DeepSeek官方余额接口，不额外调用模型。余额属于所配置API Key的账户，同一账户的其他应用也会消耗余额。充值需由用户在开放平台操作，助手不自动付款或充值。

向DeepSeek官方API发送完成业务问答所需经营和订货数据，须取得用户明确授权。当前用户已于2026-10-21在本聊天授权用于业务问答和排障；不包含客户联系方式、凭据或完整聊天库。
