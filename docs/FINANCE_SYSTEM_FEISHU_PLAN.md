# 飞书财务系统 MVP 计划

目标：先把微信里的财务文本变成可追溯、可人工确认的本地财务收件箱，再把确认后的记录导出为飞书多维表格可接收的账本结构。

## 当前交付

- `scripts/finance_inbox.py`：命令行财务收件箱。
- `scripts/finance_feishu_sync.py`：飞书确认账本同步/导出脚本，默认 dry-run/export-only。
- `ai-business-center/config/finance_schema.json`：草稿、账本和飞书多维表格字段规划。
- 默认本地数据目录：`data/finance-inbox/manual-matches/`。
- 默认产物：
  - `finance_drafts.jsonl`：待确认草稿。
  - `finance_ledger.jsonl`：人工确认后的本地账本。
  - `finance_ledger.csv`：飞书导入或人工复核用 CSV。
  - `feishu_exports/finance_ledger_feishu_upload.csv`：飞书多维表导入模板。
  - `feishu_exports/finance_ledger_feishu_payload.json`：飞书 API batch_create payload 预览。

这些数据文件属于本地财务运行数据，不应上传 GitHub。

## 安全边界

- 录入微信文本只会生成 `pending_confirmation` 草稿。
- 系统不会自动确认草稿。
- 系统不会自动发布到飞书。
- 确认账本必须显式传入 `--draft-id` 和 `--operator`。
- 金额、日期、收支方向、分类识别不确定时会写入 `parse_warnings`，确认前必须人工复核。
- 当前账本记录的 `sync_status` 固定为 `local_only`。
- 账本必须经人工执行 `mark-ready` 后才会变成 `ready_for_feishu`。
- 飞书同步脚本只读取 `ready_for_feishu`，不会从微信草稿直接写飞书。
- 没有飞书 token 或没有传 `--execute` 时，只导出 CSV/JSON，不会声称写入成功。

## 本地命令

录入一条微信财务文本：

```bash
python3 scripts/finance_inbox.py intake --text "今天 熊小小万象城 微信支付采购原料 128.50 元 供应商:张三冻品" --operator "summer"
```

列出待确认草稿：

```bash
python3 scripts/finance_inbox.py list-drafts
```

人工确认到本地账本：

```bash
python3 scripts/finance_inbox.py confirm --draft-id "<草稿ID>" --operator "summer" --category procurement --direction expense --payment-method wechat_pay
```

导出账本 CSV：

```bash
python3 scripts/finance_inbox.py export --format csv
```

列出本地账本：

```bash
python3 scripts/finance_inbox.py list-ledger
```

人工标记一条已确认账本可同步飞书：

```bash
python3 scripts/finance_inbox.py mark-ready --ledger-id "<账本ID>" --operator "summer"
```

飞书同步 dry-run / 导出模板：

```bash
python3 scripts/finance_feishu_sync.py
```

真实写入飞书必须同时满足：

- 环境变量已在本机配置：`FEISHU_TENANT_ACCESS_TOKEN`、`FEISHU_FINANCE_APP_TOKEN`、`FEISHU_FINANCE_TABLE_ID`。
- 命令显式带 `--execute`。
- 待同步账本已经是 `sync_status=ready_for_feishu`。

```bash
FEISHU_TENANT_ACCESS_TOKEN="..." \
FEISHU_FINANCE_APP_TOKEN="..." \
FEISHU_FINANCE_TABLE_ID="..." \
python3 scripts/finance_feishu_sync.py --execute
```

查看 schema：

```bash
python3 scripts/finance_inbox.py schema
```

Hermes/微信入口：

```bash
./scripts/hermes_business_center.zsh 财务记录 今天 熊小小万象城 微信支付采购原料 128.50 元 供应商:张三冻品
./scripts/hermes_business_center.zsh 财务草稿
```

微信入口只做 `intake` 和 `list-drafts`，不会开放直接确认入账。

本地验证时可以改用临时目录，避免污染真实财务数据：

```bash
FINANCE_INBOX_DIR="$(mktemp -d)" python3 scripts/finance_inbox.py intake --text "今天 收到美团平台结算 299.90 元 熊小小银泰城" --operator "test"
```

## 微信财务录入验收说明

验收目标：证明 Hermes/微信入口只把文本放入待确认草稿，不会确认入账，也不会写飞书。

1. 使用临时目录执行录入，避免污染真实数据：

```bash
tmpdir="$(mktemp -d)"
FINANCE_INBOX_DIR="$tmpdir" ./scripts/hermes_business_center.zsh 财务记录 今天 熊小小万象城 微信支付采购原料 128.50 元 供应商:张三冻品
```

2. 查看草稿：

```bash
FINANCE_INBOX_DIR="$tmpdir" ./scripts/hermes_business_center.zsh 财务草稿
```

预期结果：

- 输出中有一条 `pending_confirmation` 草稿。
- 草稿包含原始文本、解析金额、解析方向、分类和解析提醒。
- `$tmpdir/finance_ledger.jsonl` 不存在或为空。
- 不出现“飞书写入成功”。

3. 人工确认必须使用命令行显式指定草稿 ID 和确认人：

```bash
FINANCE_INBOX_DIR="$tmpdir" python3 scripts/finance_inbox.py confirm --draft-id "<草稿ID>" --operator "summer" --category procurement --direction expense --payment-method wechat_pay
```

4. 只有确认后的账本才能人工标记可同步：

```bash
FINANCE_INBOX_DIR="$tmpdir" python3 scripts/finance_inbox.py mark-ready --ledger-id "<账本ID>" --operator "summer"
FINANCE_INBOX_DIR="$tmpdir" python3 scripts/finance_feishu_sync.py
```

预期结果：同步脚本只输出预检摘要和本地导出文件；没有 `--execute` 时不会调用飞书 API。

## 飞书多维表格字段

建议建两张表。

### 财务草稿收件箱

用途：接收微信文本和解析结果，只用于人工复核，不作为正式账本。

字段：

- 草稿ID：文本，对应 `draft_id`。
- 录入时间：日期时间，对应 `created_at`。
- 状态：单选，对应 `status`，可选 `pending_confirmation`、`confirmed_to_ledger`、`voided`。
- 来源渠道：单选，对应 `source_channel`。
- 原始文本：多行文本，对应 `raw_text`。
- 解析业务日期：日期，对应 `parsed_transaction_date`。
- 解析收支方向：单选，对应 `parsed_direction`。
- 解析金额：货币，对应 `parsed_amount`。
- 解析门店：文本，对应 `parsed_store`。
- 解析交易对方：文本，对应 `parsed_counterparty`。
- 解析财务分类：单选，对应 `parsed_category`。
- 解析提醒：多行文本，对应 `parse_warnings`。

### 财务确认账本

用途：只接收人工确认后的 ledger 记录。

字段：

- 账本ID：文本，对应 `ledger_id`。
- 来源草稿ID：文本，对应 `draft_id`。
- 确认时间：日期时间，对应 `confirmed_at`。
- 确认人：文本，对应 `confirmed_by`。
- 业务日期：日期，对应 `transaction_date`。
- 收支方向：单选，对应 `direction`，可选 `income`、`expense`、`transfer`。
- 金额：货币，对应 `amount`。
- 币种：单选，对应 `currency`。
- 门店：文本，对应 `store`。
- 交易对方：文本，对应 `counterparty`。
- 财务分类：单选，对应 `category`。
- 收付款方式：单选，对应 `payment_method`。
- 来源渠道：单选，对应 `source_channel`。
- 原始文本：多行文本，对应 `raw_text`。
- 备注：多行文本，对应 `note`。
- 飞书同步状态：单选，对应 `sync_status`，可选 `local_only`、`ready_for_feishu`、`synced`、`sync_failed`。

完整字段定义维护在 `ai-business-center/config/finance_schema.json`。

## 后续飞书接入方式

没有飞书 token 时，保持 `export_only`：只生成本地 JSONL 和 CSV，不声称飞书写入成功。

飞书多维表格接入使用独立同步脚本，不改 `confirm` 的默认行为：

1. 环境变量读取 `FEISHU_TENANT_ACCESS_TOKEN`、`FEISHU_FINANCE_APP_TOKEN`、`FEISHU_FINANCE_TABLE_ID`。
2. 只同步 `sync_status=ready_for_feishu` 的账本记录。
3. 每次同步前打印 dry-run 摘要：记录数、金额合计、收支方向拆分。
4. 需要显式 `--execute` 才调用飞书 API。
5. 写入成功后把本地记录状态更新为 `synced`，失败写 `sync_failed` 和错误摘要。
6. Mac mini 生产部署时只从 GitHub `main` 拉取已验证代码；token 和运行数据只留在 Mac mini 本地。

当前脚本在 token 缺失时会返回 export-only，不会假装飞书写入成功。

## MVP 暂不做

- 不做自动财务分类最终确认。
- 不做自动对账。
- 不做平台账单抓取。
- 不做飞书 API 写入。
- 不做付款、预算或财务发布动作。
