from __future__ import annotations

import argparse
import contextlib
import html
import io
import json
import sys
import urllib.parse
import webbrowser
from collections import Counter
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import finance_inbox  # noqa: E402
from scripts import finance_feishu_sync  # noqa: E402


VALUE_LABELS = {
    "store": "门店端",
    "supply_chain": "供应链端",
    "cash_revenue": "现金收入",
    "cash_expense": "现金支出",
    "accounts_receivable": "应收",
    "accounts_payable": "应付",
    "inventory": "库存",
    "transfer": "内部转账",
    "other": "其他",
    "settled": "已结清",
    "uncollected": "未收",
    "unpaid": "未付",
    "partial": "部分结算",
    "none": "无结算状态",
}


CSS = """
:root {
  color-scheme: light;
  --ink: #1f2933;
  --muted: #64748b;
  --line: #d9e2ec;
  --soft: #f6f8fb;
  --panel: #ffffff;
  --accent: #0f766e;
  --accent-strong: #115e59;
  --warn: #92400e;
  --danger: #b42318;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  color: var(--ink);
  background: #eef2f6;
}
header {
  padding: 18px 28px;
  background: var(--panel);
  border-bottom: 1px solid var(--line);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
h1 { margin: 0; font-size: 22px; font-weight: 700; }
main { max-width: 1320px; margin: 0 auto; padding: 24px; }
.layout { display: grid; grid-template-columns: minmax(360px, 0.82fr) minmax(620px, 1.18fr); gap: 20px; align-items: start; }
.stack { display: grid; gap: 16px; }
section { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 18px; }
h2 { margin: 0 0 14px; font-size: 17px; }
h3 { margin: 0 0 10px; font-size: 15px; }
label { display: block; font-weight: 600; margin: 12px 0 7px; }
textarea, input, select {
  width: 100%;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 10px 12px;
  font: inherit;
  background: white;
}
textarea { min-height: 132px; resize: vertical; }
.checkline { display: flex; align-items: center; gap: 8px; margin-top: 12px; color: var(--muted); font-size: 13px; }
.checkline input { width: auto; }
.row { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.row-3 { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.actions { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
button, .button {
  margin-top: 14px;
  border: 0;
  border-radius: 6px;
  padding: 10px 14px;
  background: var(--accent);
  color: white;
  font-weight: 700;
  cursor: pointer;
  text-decoration: none;
  display: inline-block;
}
.danger { background: var(--danger); }
.secondary { background: #334155; }
.ghost { background: #e2e8f0; color: #263241; }
.muted { color: var(--muted); font-size: 13px; line-height: 1.45; }
.notice { padding: 10px 12px; border-radius: 6px; margin-bottom: 14px; background: #ecfdf5; border: 1px solid #a7f3d0; }
.error { background: #fff1f2; border-color: #fecdd3; color: var(--danger); }
.warning { background: #fffbeb; border-color: #fde68a; color: var(--warn); }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { border-bottom: 1px solid var(--line); padding: 9px 8px; text-align: left; vertical-align: top; overflow-wrap: anywhere; }
th { color: var(--muted); font-weight: 700; background: var(--soft); }
.pill { display: inline-block; border-radius: 999px; padding: 2px 8px; background: #e2e8f0; white-space: nowrap; font-size: 12px; }
.pill.ready { background: #dbeafe; color: #1d4ed8; }
.pill.synced { background: #dcfce7; color: #166534; }
.pill.failed { background: #fee2e2; color: #991b1b; }
.toolbar { display: flex; gap: 10px; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.empty { padding: 24px; text-align: center; color: var(--muted); background: var(--soft); border-radius: 6px; }
.metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-bottom: 16px; }
.metric { background: var(--soft); border: 1px solid var(--line); border-radius: 8px; padding: 12px; }
.metric strong { display: block; font-size: 22px; line-height: 1.1; }
.metric .down { color: var(--danger); }
.metric .up { color: #166534; }
.dashboard { display: grid; gap: 16px; margin: 16px 0 20px; }
.report-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; align-items: start; }
.report-grid-3 { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; align-items: start; }
.mini-table td, .mini-table th { padding: 8px 7px; }
.number { text-align: right; font-variant-numeric: tabular-nums; }
.period-form { display: flex; gap: 10px; align-items: end; flex-wrap: wrap; }
.period-form label { margin: 0; }
.period-form input { width: 180px; }
.record { border: 1px solid var(--line); border-radius: 8px; padding: 14px; margin-bottom: 12px; background: #fff; }
.record-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; margin-bottom: 10px; }
.raw { padding: 10px; background: var(--soft); border-radius: 6px; font-size: 13px; }
.split { display: grid; grid-template-columns: minmax(0, 1fr) minmax(280px, 0.72fr); gap: 16px; align-items: start; }
pre { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; background: #0f172a; color: #e2e8f0; padding: 12px; border-radius: 6px; font-size: 12px; max-height: 320px; overflow: auto; }
code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; }
@media (max-width: 900px) {
  .layout { grid-template-columns: 1fr; }
  .split { grid-template-columns: 1fr; }
  .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .report-grid, .report-grid-3 { grid-template-columns: 1fr; }
  .row, .row-3 { grid-template-columns: 1fr; }
  main { padding: 14px; }
  header { padding: 14px; align-items: flex-start; flex-direction: column; }
}
"""


def page(title: str, body: str) -> bytes:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>{CSS}</style>
</head>
<body>
  <header>
    <div>
      <h1>熊小小财务系统</h1>
      <div class="muted">录入只生成待确认草稿；人工确认后才进入账本，显式同步后才写飞书。</div>
    </div>
    <div class="muted">数据目录：{html.escape(str(finance_inbox.DATA_DIR))}</div>
  </header>
  <main>{body}</main>
</body>
</html>""".encode("utf-8")


def pending_drafts() -> list[dict[str, Any]]:
    confirmed_ids = finance_inbox.ledger_draft_ids()
    return [
        draft
        for draft in finance_inbox.latest_draft_states().values()
        if draft.get("status") == finance_inbox.DRAFT_PENDING and draft.get("draft_id") not in confirmed_ids
    ]


def ledger_records(status: str | None = None) -> list[dict[str, Any]]:
    records = finance_inbox.read_jsonl(finance_inbox.LEDGER_PATH)
    if status:
        records = [record for record in records if record.get("sync_status") == status]
    return records


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def money(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def signed_money(value: Any) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return str(value)
    prefix = "+" if amount > 0 else ""
    return f"{prefix}{amount:.2f}"


def current_period() -> str:
    return datetime.now().strftime("%Y-%m")


def valid_period(value: str | None) -> str:
    if value and len(value) == 7:
        try:
            datetime.strptime(value, "%Y-%m")
            return value
        except ValueError:
            pass
    return current_period()


def previous_period(period: str) -> str:
    date = datetime.strptime(period + "-01", "%Y-%m-%d")
    if date.month == 1:
        return f"{date.year - 1}-12"
    return f"{date.year}-{date.month - 1:02d}"


def select(name: str, options: list[str], selected: Any) -> str:
    selected_text = "" if selected is None else str(selected)
    items = []
    for option in options:
        marker = " selected" if option == selected_text else ""
        items.append(f'<option value="{esc(option)}"{marker}>{esc(VALUE_LABELS.get(option, option))}</option>')
    return f'<select name="{esc(name)}">{"".join(items)}</select>'


def records_for_period(records: list[dict[str, Any]], period: str) -> list[dict[str, Any]]:
    return [record for record in records if str(record.get("transaction_date") or "").startswith(period)]


def amount_sum(records: list[dict[str, Any]], direction: str | None = None) -> float:
    total = 0.0
    for record in records:
        if direction and record.get("direction") != direction:
            continue
        try:
            total += float(record.get("amount") or 0)
        except (TypeError, ValueError):
            continue
    return round(total, 2)


def grouped_amounts(records: list[dict[str, Any]], key: str) -> list[tuple[str, float, float, float]]:
    buckets: dict[str, dict[str, float]] = {}
    for record in records:
        name = str(record.get(key) or "未填写")
        bucket = buckets.setdefault(name, {"income": 0.0, "expense": 0.0, "transfer": 0.0})
        try:
            amount = float(record.get("amount") or 0)
        except (TypeError, ValueError):
            continue
        direction = str(record.get("direction") or "")
        if direction in bucket:
            bucket[direction] += amount
    rows = []
    for name, values in buckets.items():
        net = round(values["income"] - values["expense"], 2)
        rows.append((name, round(values["income"], 2), round(values["expense"], 2), net))
    return sorted(rows, key=lambda item: abs(item[3]) + item[1] + item[2], reverse=True)


def grouped_business_accounts(records: list[dict[str, Any]]) -> list[tuple[str, float, float, float]]:
    return grouped_amounts(records, "business_account")


def outstanding_amount(records: list[dict[str, Any]], account: str) -> float:
    total = 0.0
    for record in records:
        if record.get("business_account") != account:
            continue
        if record.get("settlement_status") == "settled":
            continue
        try:
            total += float(record.get("amount") or 0)
        except (TypeError, ValueError):
            continue
    return round(total, 2)


def inventory_value(records: list[dict[str, Any]]) -> float:
    total = 0.0
    for record in records:
        if record.get("business_account") != "inventory":
            continue
        quantity = record.get("quantity")
        unit_cost = record.get("unit_cost")
        try:
            if quantity not in {None, ""} and unit_cost not in {None, ""}:
                total += float(quantity) * float(unit_cost)
            else:
                total += float(record.get("amount") or 0)
        except (TypeError, ValueError):
            continue
    return round(total, 2)


def render_operating_side_rows(records: list[dict[str, Any]]) -> str:
    rows = grouped_amounts(records, "ledger_side")
    return render_amount_rows([(VALUE_LABELS.get(name, name), income, expense, net) for name, income, expense, net in rows], "本期暂无分账数据")


def render_business_account_rows(records: list[dict[str, Any]]) -> str:
    rows = grouped_business_accounts(records)
    return render_amount_rows([(VALUE_LABELS.get(name, name), income, expense, net) for name, income, expense, net in rows], "本期暂无业务科目数据")


def render_amount_rows(rows: list[tuple[str, float, float, float]], empty_text: str = "暂无数据") -> str:
    if not rows:
        return f'<div class="empty">{esc(empty_text)}</div>'
    body = []
    for name, income, expense, net in rows[:12]:
        body.append(
            "<tr>"
            f"<td>{esc(name)}</td>"
            f"<td class=\"number\">{esc(money(income))}</td>"
            f"<td class=\"number\">{esc(money(expense))}</td>"
            f"<td class=\"number\">{esc(signed_money(net))}</td>"
            "</tr>"
        )
    return (
        '<table class="mini-table"><thead><tr>'
        "<th>项目</th><th class=\"number\">收入</th><th class=\"number\">支出</th><th class=\"number\">净额</th>"
        "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table>"
    )


def category_expense_rows(records: list[dict[str, Any]]) -> list[tuple[str, float]]:
    buckets: dict[str, float] = {}
    for record in records:
        if record.get("direction") != "expense":
            continue
        category = str(record.get("category") or "未填写")
        try:
            buckets[category] = buckets.get(category, 0.0) + float(record.get("amount") or 0)
        except (TypeError, ValueError):
            continue
    return sorted(((name, round(amount, 2)) for name, amount in buckets.items()), key=lambda item: item[1], reverse=True)


def render_expense_rows(rows: list[tuple[str, float]]) -> str:
    if not rows:
        return '<div class="empty">本期暂无费用</div>'
    total = sum(amount for _, amount in rows) or 1
    body = []
    for category, amount in rows[:12]:
        body.append(
            "<tr>"
            f"<td>{esc(category)}</td>"
            f"<td class=\"number\">{esc(money(amount))}</td>"
            f"<td class=\"number\">{amount / total:.1%}</td>"
            "</tr>"
        )
    return (
        '<table class="mini-table"><thead><tr><th>科目</th><th class="number">金额</th><th class="number">占比</th></tr></thead><tbody>'
        + "".join(body)
        + "</tbody></table>"
    )


def render_finance_dashboard(period: str) -> str:
    all_records = ledger_records()
    records = records_for_period(all_records, period)
    previous = records_for_period(all_records, previous_period(period))
    income = amount_sum(records, "income")
    expense = amount_sum(records, "expense")
    transfer = amount_sum(records, "transfer")
    net = round(income - expense, 2)
    prev_net = round(amount_sum(previous, "income") - amount_sum(previous, "expense"), 2)
    net_delta = round(net - prev_net, 2)
    expense_rate = expense / income if income else 0.0
    pending_count = len(pending_drafts())
    ready_count = len(ledger_records("ready_for_feishu"))
    failed_count = len(ledger_records("sync_failed"))
    missing_store = sum(1 for record in records if not str(record.get("store") or "").strip())
    missing_counterparty = sum(1 for record in records if not str(record.get("counterparty") or "").strip())
    ar_balance = outstanding_amount(all_records, "accounts_receivable")
    ap_balance = outstanding_amount(all_records, "accounts_payable")
    inventory_balance = inventory_value(all_records)
    supply_chain_records = [record for record in records if record.get("ledger_side") == "supply_chain"]
    supply_chain_net = round(amount_sum(supply_chain_records, "income") - amount_sum(supply_chain_records, "expense"), 2)
    period_label = esc(period)
    net_class = "up" if net >= 0 else "down"
    delta_class = "up" if net_delta >= 0 else "down"
    return f"""
<div class="dashboard">
  <section>
    <div class="toolbar">
      <h2>经营驾驶舱</h2>
      <form class="period-form" method="get" action="/">
        <label for="period">月份</label>
        <input id="period" name="period" type="month" value="{period_label}">
        <button class="ghost" type="submit">切换</button>
      </form>
    </div>
    <div class="metrics">
      <div class="metric"><strong>{esc(money(income))}</strong><span class="muted">{period_label} 收入</span></div>
      <div class="metric"><strong>{esc(money(expense))}</strong><span class="muted">{period_label} 支出</span></div>
      <div class="metric"><strong class="{net_class}">{esc(signed_money(net))}</strong><span class="muted">经营净额</span></div>
      <div class="metric"><strong>{expense_rate:.1%}</strong><span class="muted">费用率</span></div>
    </div>
    <div class="metrics">
      <div class="metric"><strong>{esc(money(ar_balance))}</strong><span class="muted">应收余额</span></div>
      <div class="metric"><strong>{esc(money(ap_balance))}</strong><span class="muted">应付余额</span></div>
      <div class="metric"><strong>{esc(money(inventory_balance))}</strong><span class="muted">库存占用</span></div>
      <div class="metric"><strong>{esc(signed_money(supply_chain_net))}</strong><span class="muted">供应链端本期净额</span></div>
    </div>
    <div class="metrics">
      <div class="metric"><strong>{len(records)}</strong><span class="muted">本期确认记录</span></div>
      <div class="metric"><strong>{esc(money(transfer))}</strong><span class="muted">内部转账流水</span></div>
      <div class="metric"><strong class="{delta_class}">{esc(signed_money(net_delta))}</strong><span class="muted">较上月净额变化</span></div>
      <div class="metric"><strong>{pending_count + ready_count + failed_count}</strong><span class="muted">待办总数</span></div>
    </div>
  </section>
  <div class="report-grid">
    <section>
      <h2>费用科目</h2>
      {render_expense_rows(category_expense_rows(records))}
    </section>
    <section>
      <h2>门店经营</h2>
      {render_amount_rows(grouped_amounts(records, "store"), "本期暂无门店数据")}
    </section>
  </div>
  <div class="report-grid">
    <section>
      <h2>两套账本</h2>
      {render_operating_side_rows(records)}
    </section>
    <section>
      <h2>业务科目</h2>
      {render_business_account_rows(records)}
    </section>
  </div>
  <div class="report-grid">
    <section>
      <h2>资金渠道</h2>
      {render_amount_rows(grouped_amounts(records, "payment_method"), "本期暂无资金渠道数据")}
    </section>
    <section>
      <h2>财务待办</h2>
      <table class="mini-table"><tbody>
        <tr><td>待确认草稿</td><td class="number">{pending_count}</td></tr>
        <tr><td>待同步飞书</td><td class="number">{ready_count}</td></tr>
        <tr><td>同步失败</td><td class="number">{failed_count}</td></tr>
        <tr><td>本期缺门店</td><td class="number">{missing_store}</td></tr>
        <tr><td>本期缺交易对方</td><td class="number">{missing_counterparty}</td></tr>
      </tbody></table>
    </section>
  </div>
</div>
"""


def render_metrics() -> str:
    drafts = finance_inbox.read_jsonl(finance_inbox.DRAFTS_PATH)
    pending = pending_drafts()
    ledger = ledger_records()
    ledger_status = Counter(str(record.get("sync_status") or "unknown") for record in ledger)
    return f"""
<div class="metrics">
  <div class="metric"><strong>{len(pending)}</strong><span class="muted">待确认草稿</span></div>
  <div class="metric"><strong>{ledger_status.get("local_only", 0)}</strong><span class="muted">本地已入账</span></div>
  <div class="metric"><strong>{ledger_status.get("ready_for_feishu", 0)}</strong><span class="muted">待同步飞书</span></div>
  <div class="metric"><strong>{ledger_status.get("synced", 0)}</strong><span class="muted">已同步飞书</span></div>
</div>
<div class="muted">草稿总数 {len(drafts)}，账本总数 {len(ledger)}。所有动作都有本地记录，网页不会绕过人工确认。</div>
"""


def render_drafts() -> str:
    drafts = pending_drafts()
    if not drafts:
        return '<div class="empty">当前没有待确认财务草稿</div>'
    cards = []
    for draft in drafts:
        warnings = draft.get("parse_warnings") or []
        warning_html = ""
        if warnings:
            warning_html = f'<div class="notice warning">解析提醒：{esc("；".join(str(item) for item in warnings))}</div>'
        cards.append(
            f"""
<div class="record">
  <div class="record-head">
    <div>
      <h3>{esc(draft.get("parsed_transaction_date"))} · {esc(money(draft.get("parsed_amount")))} 元</h3>
      <div class="muted"><code>{esc(draft.get("draft_id"))}</code> · {esc(draft.get("created_at"))}</div>
    </div>
    <span class="pill">{esc(draft.get("parsed_direction"))}</span>
  </div>
  <div class="raw">{esc(draft.get("raw_text"))}</div>
  {warning_html}
  <form method="post" action="/confirm">
    <input type="hidden" name="draft_id" value="{esc(draft.get("draft_id"))}">
    <div class="row-3">
      <div><label>业务日期</label><input name="transaction_date" value="{esc(draft.get("parsed_transaction_date"))}" required></div>
      <div><label>金额</label><input name="amount" type="number" min="0.01" step="0.01" value="{esc(money(draft.get("parsed_amount")))}" required></div>
      <div><label>确认人</label><input name="operator" value="{esc(draft.get("created_by") or "summer")}" required></div>
    </div>
    <div class="row-3">
      <div><label>收支方向</label>{select("direction", sorted(finance_inbox.CONFIRMABLE_DIRECTIONS), draft.get("parsed_direction"))}</div>
      <div><label>财务分类</label>{select("category", sorted(finance_inbox.CONFIRMABLE_CATEGORIES), draft.get("parsed_category"))}</div>
      <div><label>收付款方式</label>{select("payment_method", sorted(finance_inbox.VALID_PAYMENT_METHODS), draft.get("parsed_payment_method"))}</div>
    </div>
    <div class="row-3">
      <div><label>账本端</label>{select("ledger_side", sorted(finance_inbox.VALID_LEDGER_SIDES), draft.get("parsed_ledger_side"))}</div>
      <div><label>业务科目</label>{select("business_account", sorted(finance_inbox.VALID_BUSINESS_ACCOUNTS), draft.get("parsed_business_account"))}</div>
      <div><label>结算状态</label>{select("settlement_status", sorted(finance_inbox.VALID_SETTLEMENT_STATUS), draft.get("parsed_settlement_status"))}</div>
    </div>
    <div class="row">
      <div><label>门店</label><input name="store" value="{esc(draft.get("parsed_store"))}"></div>
      <div><label>交易对方</label><input name="counterparty" value="{esc(draft.get("parsed_counterparty"))}"></div>
    </div>
    <div class="row-3">
      <div><label>到期日</label><input name="due_date" placeholder="YYYY-MM-DD" value="{esc(draft.get("parsed_due_date"))}"></div>
      <div><label>库存品项</label><input name="inventory_item" value="{esc(draft.get("parsed_inventory_item"))}"></div>
      <div><label>库存单位</label><input name="unit" placeholder="斤 / 箱 / 袋"></div>
    </div>
    <div class="row">
      <div><label>库存数量</label><input name="quantity" type="number" min="0" step="0.0001"></div>
      <div><label>库存单价</label><input name="unit_cost" type="number" min="0" step="0.0001"></div>
    </div>
    <label>备注</label><input name="note" value="">
    <button type="submit">确认入账</button>
  </form>
</div>
"""
        )
    return "".join(cards)


def sync_pill(status: Any) -> str:
    status_text = str(status or "unknown")
    class_name = ""
    if status_text == "ready_for_feishu":
        class_name = " ready"
    elif status_text == "synced":
        class_name = " synced"
    elif status_text == "sync_failed":
        class_name = " failed"
    return f'<span class="pill{class_name}">{esc(status_text)}</span>'


def render_ledger() -> str:
    records = ledger_records()
    if not records:
        return '<div class="empty">当前还没有确认账本记录</div>'
    rows = []
    for record in reversed(records[-50:]):
        action = ""
        if record.get("sync_status") in {"local_only", "sync_failed"}:
            action = f"""
<form method="post" action="/ready">
  <input type="hidden" name="ledger_id" value="{esc(record.get("ledger_id"))}">
  <input name="operator" value="{esc(record.get("confirmed_by") or "summer")}" required>
  <button class="secondary" type="submit">标记待同步</button>
</form>
"""
        elif record.get("sync_status") == "ready_for_feishu":
            action = '<div class="muted">等待下方飞书同步</div>'
        elif record.get("sync_status") == "synced":
            action = f'<div class="muted">飞书记录：<code>{esc(record.get("feishu_record_id"))}</code></div>'
        rows.append(
            "<tr>"
            f"<td><code>{esc(record.get('ledger_id'))}</code><div class=\"muted\">草稿 {esc(record.get('draft_id'))}</div></td>"
            f"<td>{esc(record.get('transaction_date'))}</td>"
            f"<td>{esc(record.get('direction'))}</td>"
            f"<td>{esc(money(record.get('amount')))}</td>"
            f"<td>{esc(VALUE_LABELS.get(str(record.get('ledger_side') or 'store'), str(record.get('ledger_side') or 'store')))}<div class=\"muted\">{esc(VALUE_LABELS.get(str(record.get('business_account') or 'other'), str(record.get('business_account') or 'other')))}</div></td>"
            f"<td>{esc(record.get('category'))}<div class=\"muted\">{esc(VALUE_LABELS.get(str(record.get('settlement_status') or ''), str(record.get('settlement_status') or '')))} · {esc(record.get('payment_method'))}</div></td>"
            f"<td>{esc(record.get('store'))}<div class=\"muted\">{esc(record.get('counterparty'))}</div></td>"
            f"<td>{sync_pill(record.get('sync_status'))}<div class=\"muted\">{esc(record.get('sync_error'))}</div></td>"
            f"<td>{action}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr>"
        "<th>账本ID</th><th>业务日期</th><th>方向</th><th>金额</th><th>账本/科目</th><th>分类/结算</th><th>门店/对方</th><th>飞书状态</th><th>动作</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def run_finance_action(action: str, args: argparse.Namespace) -> tuple[int, str]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
        try:
            if action == "confirm":
                code = finance_inbox.command_confirm(args)
            elif action == "ready":
                code = finance_inbox.command_mark_ready(args)
            elif action == "sync":
                code = finance_feishu_sync.command_sync(args)
            else:
                raise SystemExit(f"未知动作：{action}")
        except SystemExit as exc:
            code = int(exc.code) if isinstance(exc.code, int) else 1
            if exc.code and not isinstance(exc.code, int):
                print(exc.code)
    return code, buffer.getvalue().strip()


def render_home(message: str = "", error: str = "", sync_output: str = "", period: str | None = None) -> bytes:
    period = valid_period(period)
    notice = ""
    if message:
        notice = f'<div class="notice">{html.escape(message)}</div>'
    if error:
        notice = f'<div class="notice error">{html.escape(error)}</div>'
    body = f"""
{notice}
{render_finance_dashboard(period)}
{render_metrics()}
<div class="layout">
  <div class="stack">
    <section>
      <h2>录入财务记录</h2>
      <form method="post" action="/intake">
        <label for="raw_text">财务文本</label>
        <textarea id="raw_text" name="raw_text" required placeholder="例如：今天 熊小小万象城 微信支付采购原料 128.50 元 供应商:张三冻品"></textarea>
        <div class="row">
          <div>
            <label for="operator">录入人</label>
            <input id="operator" name="operator" value="finance-web">
          </div>
          <div>
            <label for="hint">状态</label>
            <input id="hint" value="待确认草稿" disabled>
          </div>
        </div>
        <button type="submit">录入草稿</button>
      </form>
    </section>
    <section>
      <div class="toolbar">
        <h2>飞书同步</h2>
        <form method="get" action="/"><button class="ghost" type="submit">刷新</button></form>
      </div>
      <form method="post" action="/sync">
        <label class="checkline"><input type="checkbox" name="confirm_execute" value="yes">确认把 ready_for_feishu 记录真实写入飞书</label>
        <div class="actions">
          <button class="secondary" type="submit" name="mode" value="dry-run">预检并导出</button>
          <button class="danger" type="submit" name="mode" value="execute">真实写入飞书</button>
        </div>
        <p class="muted">真实写入只处理已标记为 ready_for_feishu 的账本；缺少飞书 token 或 API 失败时，会明确报错，不会把本地记录假标为成功。</p>
      </form>
      {f'<pre>{esc(sync_output)}</pre>' if sync_output else ''}
    </section>
  </div>
  <div class="stack">
    <section>
      <div class="toolbar">
        <h2>待确认草稿</h2>
        <a class="button ghost" href="/">刷新</a>
      </div>
      {render_drafts()}
    </section>
    <section>
      <h2>确认账本</h2>
      {render_ledger()}
    </section>
  </div>
</div>
"""
    return page("熊小小财务系统", body)


class FinanceHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        if parsed_url.path not in {"/", "/index.html"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        query = urllib.parse.parse_qs(parsed_url.query)
        period = (query.get("period") or [""])[0]
        self.respond(render_home(period=period))

    def do_POST(self) -> None:
        parsed_path = urllib.parse.urlparse(self.path).path
        if parsed_path not in {"/intake", "/confirm", "/ready", "/sync"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_length = int(self.headers.get("Content-Length", "0"))
        payload = self.rfile.read(content_length).decode("utf-8")
        form = urllib.parse.parse_qs(payload)
        if parsed_path == "/confirm":
            self.handle_confirm(form)
            return
        if parsed_path == "/ready":
            self.handle_ready(form)
            return
        if parsed_path == "/sync":
            self.handle_sync(form)
            return
        raw_text = (form.get("raw_text") or [""])[0].strip()
        operator = (form.get("operator") or ["finance-web"])[0].strip() or "finance-web"
        if not raw_text:
            self.respond(render_home(error="请输入财务文本。"))
            return
        parsed = finance_inbox.parse_wechat_text(raw_text)
        draft = {
            "draft_id": finance_inbox.short_id("fin-draft"),
            "created_at": finance_inbox.now_text(),
            "created_by": operator,
            "status": finance_inbox.DRAFT_PENDING,
            "source_channel": "manual",
            "raw_text": raw_text,
            **parsed,
            "safety_notice": "本记录来自网页录入口，只是待确认草稿，不会自动写入账本或飞书。",
        }
        finance_inbox.append_jsonl(finance_inbox.DRAFTS_PATH, draft)
        warnings = draft.get("parse_warnings") or []
        message = f"已录入待确认草稿：{draft['draft_id']}。"
        if warnings:
            message += " 解析提醒：" + "；".join(str(item) for item in warnings)
        self.respond(render_home(message=message))

    def handle_confirm(self, form: dict[str, list[str]]) -> None:
        def value(name: str, default: str = "") -> str:
            return (form.get(name) or [default])[0].strip()

        amount_text = value("amount")
        quantity_text = value("quantity")
        unit_cost_text = value("unit_cost")
        try:
            amount = float(amount_text) if amount_text else None
            quantity = float(quantity_text) if quantity_text else None
            unit_cost = float(unit_cost_text) if unit_cost_text else None
            args = argparse.Namespace(
                draft_id=value("draft_id"),
                operator=value("operator"),
                transaction_date=value("transaction_date"),
                direction=value("direction") or None,
                amount=amount,
                category=value("category") or None,
                payment_method=value("payment_method") or None,
                ledger_side=value("ledger_side") or None,
                business_account=value("business_account") or None,
                settlement_status=value("settlement_status") or None,
                due_date=value("due_date"),
                store=value("store"),
                counterparty=value("counterparty"),
                inventory_item=value("inventory_item"),
                quantity=quantity,
                unit=value("unit"),
                unit_cost=unit_cost,
                note=value("note"),
            )
        except ValueError:
            self.respond(render_home(error="金额、库存数量和库存单价必须是数字。"))
            return
        code, output = run_finance_action("confirm", args)
        if code == 0:
            self.respond(render_home(message=output or "已确认入账。"))
        else:
            self.respond(render_home(error=output or "确认入账失败。"))

    def handle_ready(self, form: dict[str, list[str]]) -> None:
        def value(name: str, default: str = "") -> str:
            return (form.get(name) or [default])[0].strip()

        args = argparse.Namespace(ledger_id=value("ledger_id"), operator=value("operator"))
        code, output = run_finance_action("ready", args)
        if code == 0:
            self.respond(render_home(message=output or "已标记待同步。"))
        else:
            self.respond(render_home(error=output or "标记待同步失败。"))

    def handle_sync(self, form: dict[str, list[str]]) -> None:
        mode = (form.get("mode") or ["dry-run"])[0]
        if mode == "execute" and (form.get("confirm_execute") or [""])[0] != "yes":
            self.respond(render_home(error="真实写入飞书前必须先勾选确认框。"))
            return
        args = argparse.Namespace(execute=mode == "execute", csv_path=None, json_path=None)
        code, output = run_finance_action("sync", args)
        if code == 0:
            self.respond(render_home(message="飞书同步流程完成。", sync_output=output))
        elif code == 2:
            self.respond(render_home(message="已完成导出；当前没有执行真实写入。", sync_output=output))
        else:
            self.respond(render_home(error="飞书同步失败，请看输出。", sync_output=output))

    def respond(self, body: bytes) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        print(f"[finance-web] {self.address_string()} - {format % args}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="熊小小财务系统网页录入口。")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-open", action="store_true", help="不自动打开浏览器。")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    server = ThreadingHTTPServer((args.host, args.port), FinanceHandler)
    url = f"http://{args.host}:{args.port}/"
    print(f"熊小小财务系统网页录入口：{url}")
    print("按 Ctrl+C 停止。")
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止财务系统网页录入口。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
