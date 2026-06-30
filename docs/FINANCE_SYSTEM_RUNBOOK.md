# 熊小小财务系统使用说明书

这套系统的目标是把微信里的财务文本变成可追溯的待确认草稿，人工确认后进入本地账本，再安全同步到飞书多维表。系统已经完成真实飞书 API 写入验证。

## 正式入口

统一入口：

```bash
python3 scripts/finance_system.py <命令>
```

Hermes/微信入口：

```bash
./scripts/hermes_business_center.zsh 财务记录 今天 熊小小万象城 微信支付采购原料 128.50 元 供应商:张三冻品
./scripts/hermes_business_center.zsh 财务草稿
./scripts/hermes_business_center.zsh 财务状态
./scripts/hermes_business_center.zsh 财务账本
./scripts/hermes_business_center.zsh 财务同步
./scripts/hermes_business_center.zsh 财务说明
```

## 日常流程

### 1. 录入微信财务记录

微信或 Hermes 里发：

```bash
./scripts/hermes_business_center.zsh 财务记录 今天 熊小小万象城 微信支付采购原料 128.50 元 供应商:张三冻品
```

系统只会生成 `pending_confirmation` 草稿，不会自动入账，也不会写飞书。

### 2. 查看待确认草稿

```bash
python3 scripts/finance_system.py drafts
```

重点看：

- 金额是否正确。
- 业务日期是否正确。
- 收支方向是否正确。
- 财务分类是否正确。
- `warnings` 是否大于 0。

### 3. 人工确认到本地账本

确认前必须核对原始文本。确认命令示例：

```bash
python3 scripts/finance_system.py confirm \
  --draft-id "<草稿ID>" \
  --operator "summer" \
  --category procurement \
  --direction expense \
  --payment-method wechat_pay
```

确认后，本地账本状态默认是 `local_only`。

### 4. 标记可同步飞书

只有确认无误的账本才能标记：

```bash
python3 scripts/finance_system.py ready --ledger-id "<账本ID>" --operator "summer"
```

标记后状态变成 `ready_for_feishu`。

### 5. 飞书同步预检

默认只 dry-run 和导出，不写飞书：

```bash
python3 scripts/finance_system.py sync
```

预检会输出记录数、金额合计、收支方向拆分，并生成：

- `finance_ledger_feishu_upload.csv`
- `finance_ledger_feishu_payload.json`

### 6. 真实写入飞书

只有在飞书环境变量齐全，并且显式传入 `--execute` 时才写入飞书：

```bash
python3 scripts/finance_system.py sync --execute
```

写入成功后，本地账本状态变成 `synced`，并保存飞书记录 ID。

## 状态检查

```bash
python3 scripts/finance_system.py status
```

状态里会显示：

- 待确认草稿数量。
- 本地账本数量。
- `local_only` / `ready_for_feishu` / `synced` / `sync_failed` 数量。
- 飞书配置是否具备真实执行条件。

## 飞书配置

当前飞书表：

- 知识库 token：`S2cjweZDgiF9Ahk1utNct9ALnGb`
- 财务确认账本 table id：`tbl4k7A9bHAqPAuI`
- 开发者后台 App ID：`cli_aac9dcadd1f81cc8`

生产环境变量建议配置在 Mac mini 本地，不提交 GitHub：

```bash
FEISHU_APP_ID="cli_aac9dcadd1f81cc8"
FEISHU_APP_SECRET="..."
FEISHU_FINANCE_WIKI_TOKEN="S2cjweZDgiF9Ahk1utNct9ALnGb"
FEISHU_FINANCE_TABLE_ID="tbl4k7A9bHAqPAuI"
```

## 飞书表字段要求

表名：`财务确认账本`

字段：

- 账本ID：文本
- 来源草稿ID：文本
- 确认时间：文本或日期
- 确认人：文本
- 业务日期：日期
- 收支方向：文本或单选
- 金额：数字或货币；如果是数字字段，格式必须是 `0.00`
- 币种：文本或单选
- 门店：文本
- 交易对方：文本
- 财务分类：文本或单选
- 收付款方式：文本或单选
- 来源渠道：文本或单选
- 原始文本：文本
- 备注：文本
- 飞书同步状态：文本或单选

## 安全边界

系统永远不做这些事：

- 不从微信文本自动确认入账。
- 不自动把草稿写入飞书。
- 不在缺 token 时假装飞书写入成功。
- 不执行付款、预算、出价、订货或财务发布。
- 不上传本地财务运行数据、飞书密钥、Chrome 登录态或截图。

## 异常处理

### 草稿解析不准

用 `confirm` 时手动覆盖：

```bash
python3 scripts/finance_system.py confirm \
  --draft-id "<草稿ID>" \
  --operator "summer" \
  --transaction-date "2026-06-30" \
  --amount 128.50 \
  --category procurement \
  --direction expense \
  --payment-method wechat_pay
```

### 飞书同步失败

查看失败记录：

```bash
python3 scripts/finance_system.py ledger --status sync_failed
```

常见原因：

- 飞书环境变量缺失。
- table id 配错。
- 应用没有多维表编辑权限。
- 飞书字段名被改动。
- 飞书字段类型不兼容。

修复后重新标记或处理失败记录，再同步。

## 今日验收结果

- CSV 手动导入成功。
- 飞书 API 权限、机器人能力、Wiki 节点读取权限已配置。
- 群授权后，真实 API 写入成功。
- 测试账本 ID：`fin-ledger-20260630150943-6bfb52ce`
- 飞书记录 ID：`recvo0BlqjQGoU`
- 金额字段已修正为 2 位小数显示。
