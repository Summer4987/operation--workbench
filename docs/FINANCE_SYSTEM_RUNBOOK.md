# 熊小小财务系统使用说明书

这套系统的目标是把微信里的财务文本变成可追溯的财务工作流：先生成待确认草稿，人工确认后进入本地账本，再形成经营驾驶舱、费用科目、门店经营、资金渠道和财务待办，最后安全同步到飞书多维表。系统已经完成真实飞书 API 写入验证。

当前定位是“轻量财务系统”，不是单纯流水账。它已经覆盖日常录入、审核、账本、月度经营汇总、门店/科目/资金渠道分析和飞书同步；暂不覆盖发票、银行回单自动对账、应收应付账龄、税务申报和专业总账凭证。

## 正式入口

日常录入入口：

```bash
./熊小小财务系统.command
```

双击项目根目录里的 `熊小小财务系统.command` 也可以。它会打开本地网页：

```text
http://127.0.0.1:8765/
```

今天的支出、收入、采购、房租、水电等，都从这个网页工作台处理。网页首页先看经营驾驶舱，再处理录入草稿、人工确认入账、标记待同步、飞书预检/同步。

安全边界不变：录入不会自动入账；入账必须点击“确认入账”；写飞书必须先把账本标记为 `ready_for_feishu`，再手动勾选确认并点击“真实写入飞书”。

后台统一入口：

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
./scripts/hermes_business_center.zsh 财务入口
```

## 日常流程

### 1. 打开财务工作台

日常优先用网页：

```bash
./熊小小财务系统.command
```

如果网页没有自动弹出，手动打开：

```text
http://127.0.0.1:8765/
```

页面顶部先看本月经营结果：

- 收入、支出、经营净额、费用率。
- 本期确认记录和内部转账流水。
- 较上月净额变化。
- 费用科目、门店经营、资金渠道。
- 待确认、待同步、同步失败、缺门店、缺交易对方。

### 2. 录入微信财务记录

在网页左侧“录入财务记录”粘贴文本，例如：

```text
今天 熊小小万象城 微信支付采购原料 128.50 元 供应商:张三冻品
```

也可以从 Hermes 里发：

```bash
./scripts/hermes_business_center.zsh 财务记录 今天 熊小小万象城 微信支付采购原料 128.50 元 供应商:张三冻品
```

系统只会生成 `pending_confirmation` 草稿，不会自动入账，也不会写飞书。

### 3. 人工确认入账

网页右侧“待确认草稿”会显示解析出来的日期、金额、收支方向、分类、收付款方式、门店和交易对方。

确认前必须核对：

- 金额是否正确。
- 业务日期是否正确。
- 收支方向是否正确。
- 财务分类是否正确。
- 解析提醒是否需要人工修正。

核对无误后，点击“确认入账”。确认成功后，记录进入下方“确认账本”，状态是 `local_only`。

命令行也可以确认：

```bash
python3 scripts/finance_system.py confirm \
  --draft-id "<草稿ID>" \
  --operator "summer" \
  --category procurement \
  --direction expense \
  --payment-method wechat_pay
```

### 4. 标记可同步飞书

确认账本里，只有 `local_only` 或 `sync_failed` 的记录会显示“标记待同步”。点击后状态变成 `ready_for_feishu`。

命令行也可以标记：

```bash
python3 scripts/finance_system.py ready --ledger-id "<账本ID>" --operator "summer"
```

### 5. 飞书同步预检

网页左侧“飞书同步”点击“预检并导出”，默认只 dry-run 和导出，不写飞书。

```bash
python3 scripts/finance_system.py sync
```

预检会输出记录数、金额合计、收支方向拆分，并生成：

- `finance_ledger_feishu_upload.csv`
- `finance_ledger_feishu_payload.json`

### 6. 真实写入飞书

网页写入飞书必须同时满足：

- 账本记录已经是 `ready_for_feishu`。
- 飞书环境变量齐全。
- 勾选“确认把 ready_for_feishu 记录真实写入飞书”。
- 点击“真实写入飞书”。

命令行写入必须显式传入 `--execute`：

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
