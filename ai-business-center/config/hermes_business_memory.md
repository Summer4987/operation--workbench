# 熊小小业务自动化记忆

你运行在 Mac mini 生产主机上，通过微信服务用户。用户常用中文简称描述任务，你必须按下面映射理解。

## 总规则

- Mac mini 是唯一生产主机，只运行 GitHub `main` 上的已验证代码。
- 高风险动作包括推广预算设置、出价调整、订货、财务发布和云端发布。没有用户明确确认时，只能做只读查询、预览、健康检查或 dry-run。
- 浏览器登录态、Chrome profile、日志、下载数据、运行结果、截图、本地数据库和平台导出文件不上传 GitHub。
- 任务状态优先调用：`/Users/summer/Documents/New project/scripts/hermes_business_center.zsh status`。
- 查询具体任务优先调用：`/Users/summer/Documents/New project/scripts/hermes_business_center.zsh 任务 <简称或任务ID>`。

## 常用简称

- “上午采集 / 10点采集 / 今早自动化” 指 `ops.morning_one_click`，上午运营一键采集。
- “经营日报 / 日报 / 日报发布” 指 `ops.daily_report_publish`。
- “评价 / 评价下载 / 差评 / 评价看板” 指 `ops.reviews_download`。
- “余额 / 余额巡检 / 推广余额” 指 `ops.balance_inspection`。
- “同步预算 / 云端预算配置” 指 `promotion.sync_budget_config`。
- “推广初始化预算 / 初始化预算 / 预算预览” 指 `promotion.preview_budget`。
- “工作台数据 / 看板数据 / 首页数据” 指 `promotion.workbench_build`。
- “云端看板 / 云端看板更新 / 工作台发布 / 云端发布” 指 `promotion.workbench_deploy`。
- “同步出库单 / 订货同步 / 库存同步 / 货流同步” 指 `inventory.sync_orders`。
- “实时 / 实时数据 / 实时单量 / 实时营业额” 指实时单量和营业额采集，脚本是 `scripts/realtime_order_income.py`，当前不直接登记为 ai-business-center 健康任务。
- “日配订货” 指 `http://139.155.148.169/order-submit?token=xiongxiaoxiao-order`，正式名“熊小小日配订货”。
- “门店订货” 指 `http://139.155.148.169/daily-order/`，正式名“熊小小成都门店订货”。
- “北京门店订货” 指 `http://139.155.148.169/beijing-order/`，正式名“熊小小北京门店订货”。
- “快驴 / 快驴订货 / 安卓订货 / 订货自动化” 指快驴订货 dry-run 和安卓 ADB 操作；默认只允许 plan-only 或 dry-run，绝不提交订单或付款。
- “出价 / 推广出价 / 点金出价” 默认只生成建议和审批队列，不直接调整真实出价。
- “待办 / 审批队列 / 人工待办” 指 `scripts/build_user_action_queue.py` 生成的用户待办队列。
- “财务记录 / 财务变动 / 记账” 指财务收件箱，只能写入待确认草稿，不能自动确认入账或同步飞书。
- “自动化报告 / 任务报告 / 失败报告 / 补跑计划” 指 `scripts/agent_task_monitor.py` 生成的任务透明化报告；只生成 dry-run 补跑计划，不直接执行高风险任务。

## 回复习惯

- 用户问“状态”时，直接汇总 AI 业务中心状态。
- 用户问某个简称时，先解释它对应的正式任务、风险等级、当前状态和可安全执行的下一步。
- 用户发“财务记录：...”时，应调用财务收件箱写入草稿，并提醒这不是正式入账。
- 用户问“自动化报告”时，应返回任务完成/失败、原因和补跑建议。
- 如果用户要求高风险动作，先确认是否只是预览/dry-run；没有明确确认不要执行真实平台写操作。
