from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from task_run_state import classify_failure_text, record_task_event


ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / "data" / "finance-inbox"
OUTPUT_DIR = ROOT / "outputs" / "finance_reconciliation_preview"
LATEST_PATH = OUTPUT_DIR / "latest.json"
LEDGER_RULES_PATH = ROOT / "config" / "finance_ledger_rules.json"
TASK_ID = "finance.bill_analysis"


@dataclass
class NormalizedTransaction:
    source: str
    source_name: str
    transaction_time: str
    transaction_date: str
    direction: str
    amount: float
    original_amount: float
    counterparty: str
    description: str
    payment_method: str
    status: str
    transaction_id: str
    merchant_order_id: str
    raw_file: str
    category: str = ""
    channel_id: str = ""
    channel_name: str = ""
    channel_group: str = ""
    channel_rule: str = ""
    ledger_scope: str = ""
    ledger_id: str = ""
    ledger_name: str = ""
    ledger_status: str = ""
    ledger_rule: str = ""
    match_status: str = "unmatched"
    match_id: str = ""
    notes: str = ""


def read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def load_ledger_rules() -> dict[str, Any]:
    return read_json(LEDGER_RULES_PATH, {})


def channel_rules_from_config(config: dict[str, Any]) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    for section in ("income_channels", "expense_channels", "neutral_channels"):
        for rule in config.get(section) or []:
            rules.append(rule)
    return rules


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def money(value: Any) -> float:
    text = str(value or "").strip().replace(",", "").replace("￥", "").replace("¥", "")
    text = text.replace("元", "").replace("\t", "")
    if not text or text in {"/", "nan", "None"}:
        return 0.0
    try:
        return float(Decimal(text))
    except (InvalidOperation, ValueError):
        return 0.0


def signed_amount(amount: float, direction: str) -> float:
    text = str(direction or "")
    if "不计" in text or "中性" in text:
        return 0.0
    if "支" in text or text.lower() in {"expense", "out"}:
        return -abs(amount)
    if "收" in text or text.lower() in {"income", "in"}:
        return abs(amount)
    return amount


def clean_text(value: Any) -> str:
    text = "" if value is None else str(value)
    return re.sub(r"\s+", " ", text.replace("\t", "")).strip()


def classify_channel(item: NormalizedTransaction, rules: list[dict[str, Any]]) -> None:
    haystack = " ".join(
        [
            item.source_name,
            item.direction,
            item.counterparty,
            item.description,
            item.payment_method,
            item.status,
            item.category,
            item.transaction_id,
            item.merchant_order_id,
        ]
    ).lower()
    amount_direction = "income" if item.amount > 0 else "expense" if item.amount < 0 else "neutral"
    for rule in rules:
        rule_direction = rule.get("direction", "")
        if rule_direction and rule_direction != amount_direction:
            continue
        for keyword in rule.get("keywords", []):
            if keyword.lower() in haystack:
                item.channel_id = str(rule["id"])
                item.channel_name = str(rule["name"])
                item.channel_group = str(rule["group"])
                item.channel_rule = f"keyword:{keyword}"
                item.ledger_scope = str(rule.get("default_ledger_scope") or "")
                return

    if item.source == "wechat_pay":
        item.channel_id = "wechat_other"
        item.channel_name = "微信支付其他"
        item.channel_group = "待确认渠道" if item.amount else "退款及中性"
        item.channel_rule = "fallback:source"
        item.ledger_scope = "manual_review"
    elif item.source == "alipay":
        item.channel_id = "alipay_other"
        item.channel_name = "支付宝其他"
        item.channel_group = "待确认渠道" if item.amount else "退款及中性"
        item.channel_rule = "fallback:source"
        item.ledger_scope = "manual_review"
    elif item.source == "bank":
        item.channel_id = "bank_other"
        item.channel_name = "银行其他"
        item.channel_group = "待确认渠道" if item.amount else "退款及中性"
        item.channel_rule = "fallback:source"
        item.ledger_scope = "manual_review"
    else:
        item.channel_id = "unknown"
        item.channel_name = "未知渠道"
        item.channel_group = "待确认渠道"
        item.channel_rule = "fallback:unknown"
        item.ledger_scope = "manual_review"


def month_key(value: str) -> str:
    date_text = safe_date(value)
    return date_text[:7] if date_text else "unknown"


def ledger_name_map(ledger_rules: dict[str, Any]) -> dict[str, str]:
    ledgers = ledger_rules.get("monthly_ledgers") or []
    return {str(item.get("id") or ""): str(item.get("name") or item.get("id") or "") for item in ledgers}


def assign_ledger(item: NormalizedTransaction, ledger_rules: dict[str, Any]) -> None:
    ledgers = ledger_rules.get("monthly_ledgers") or []
    names = ledger_name_map(ledger_rules)
    haystack = " ".join(
        [
            item.counterparty,
            item.description,
            item.payment_method,
            item.status,
            item.category,
            item.channel_name,
        ]
    ).lower()
    for ledger in ledgers:
        if ledger.get("type") != "store":
            continue
        keywords = [ledger.get("name", ""), ledger.get("id", "")]
        keywords.extend(ledger.get("aliases") or [])
        for keyword in keywords:
            if keyword and str(keyword).lower() in haystack:
                item.ledger_id = str(ledger.get("id") or "")
                item.ledger_name = str(ledger.get("name") or item.ledger_id)
                item.ledger_status = "assigned"
                item.ledger_rule = f"store_keyword:{keyword}"
                return

    scope = item.ledger_scope or "manual_review"
    if scope == "supply_chain_sales":
        item.ledger_id = "supply_chain_sales"
        item.ledger_name = names.get("supply_chain_sales", "供应链销售")
        item.ledger_status = "assigned"
        item.ledger_rule = "scope:supply_chain_sales"
    elif scope == "store":
        item.ledger_id = "store_unassigned"
        item.ledger_name = "门店待分配"
        item.ledger_status = "pending_store_assignment"
        item.ledger_rule = "scope:store_without_store_signal"
    elif scope == "manual_split_store":
        item.ledger_id = "manual_split_store"
        item.ledger_name = "小程序手动拆分"
        item.ledger_status = "manual_split_required"
        item.ledger_rule = "scope:manual_split_store"
    elif scope == "mixed_store_and_sales":
        item.ledger_id = "mixed_store_and_sales"
        item.ledger_name = "供应链采购拆分"
        item.ledger_status = "manual_split_required"
        item.ledger_rule = "scope:mixed_store_and_sales"
    elif scope == "settlement_clearing":
        item.ledger_id = "settlement_clearing"
        item.ledger_name = "代付及往来结算"
        item.ledger_status = "settlement_required"
        item.ledger_rule = "scope:settlement_clearing"
    elif scope in {"neutral", "original_ledger_or_neutral"}:
        item.ledger_id = "neutral"
        item.ledger_name = "退款及中性"
        item.ledger_status = "neutral"
        item.ledger_rule = f"scope:{scope}"
    else:
        item.ledger_id = "manual_review"
        item.ledger_name = "待确认账本"
        item.ledger_status = "manual_review_required"
        item.ledger_rule = f"scope:{scope}"


def safe_date(value: str) -> str:
    text = clean_text(value)
    if not text:
        return ""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:19], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    match = re.search(r"\d{4}-\d{2}-\d{2}", text)
    return match.group(0) if match else ""


def parse_time(value: str) -> datetime | None:
    text = clean_text(value)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    return None


def source_files(folder: str, extensions: set[str]) -> list[Path]:
    path = INBOX / folder
    if not path.exists():
        return []
    return [
        item
        for item in sorted(path.iterdir())
        if item.is_file() and not item.name.startswith(".") and item.suffix.lower() in extensions
    ]


def read_csv_after_header(path: Path, header_token: str, encoding: str = "gb18030") -> list[dict[str, str]]:
    lines = path.read_text(encoding=encoding, errors="replace").splitlines()
    start = None
    for index, line in enumerate(lines):
        if header_token in line:
            start = index
            break
    if start is None:
        return []
    reader = csv.DictReader(lines[start:])
    return [{clean_text(k): clean_text(v) for k, v in row.items() if k is not None} for row in reader]


def parse_alipay(path: Path) -> list[NormalizedTransaction]:
    rows = read_csv_after_header(path, "交易时间")
    transactions = []
    for row in rows:
        amount = money(row.get("金额"))
        direction = clean_text(row.get("收/支"))
        signed = signed_amount(amount, direction)
        if not row.get("交易时间"):
            continue
        transactions.append(
            NormalizedTransaction(
                source="alipay",
                source_name="支付宝",
                transaction_time=clean_text(row.get("交易时间")),
                transaction_date=safe_date(row.get("交易时间", "")),
                direction=direction or ("收入" if signed > 0 else "支出" if signed < 0 else "不计收支"),
                amount=round(signed, 2),
                original_amount=round(amount, 2),
                counterparty=clean_text(row.get("交易对方")),
                description=clean_text(row.get("商品说明")),
                payment_method=clean_text(row.get("收/付款方式")),
                status=clean_text(row.get("交易状态")),
                transaction_id=clean_text(row.get("交易订单号")),
                merchant_order_id=clean_text(row.get("商家订单号")),
                raw_file=str(path.relative_to(ROOT)),
                category=clean_text(row.get("交易分类")),
            )
        )
    return transactions


def parse_wechat(path: Path) -> list[NormalizedTransaction]:
    try:
        import pandas as pd
    except Exception as exc:  # pragma: no cover - environment guard
        raise RuntimeError("解析微信 XLSX 需要 pandas/openpyxl。") from exc

    raw = pd.read_excel(path, header=None, dtype=str)
    header_index = None
    for index, row in raw.iterrows():
        values = [clean_text(item) for item in row.tolist()]
        if values and values[0] == "交易时间":
            header_index = index
            break
    if header_index is None:
        return []
    headers = [clean_text(item) for item in raw.iloc[header_index].tolist()]
    data = raw.iloc[header_index + 1 :].copy()
    data.columns = headers
    transactions = []
    for _, row in data.iterrows():
        tx_time = clean_text(row.get("交易时间"))
        if not tx_time:
            continue
        amount = money(row.get("金额(元)"))
        direction = clean_text(row.get("收/支"))
        signed = signed_amount(amount, direction)
        transactions.append(
            NormalizedTransaction(
                source="wechat_pay",
                source_name="微信支付",
                transaction_time=tx_time,
                transaction_date=safe_date(tx_time),
                direction=direction or ("收入" if signed > 0 else "支出" if signed < 0 else "中性"),
                amount=round(signed, 2),
                original_amount=round(amount, 2),
                counterparty=clean_text(row.get("交易对方")),
                description=clean_text(row.get("商品")),
                payment_method=clean_text(row.get("支付方式")),
                status=clean_text(row.get("当前状态")),
                transaction_id=clean_text(row.get("交易单号")),
                merchant_order_id=clean_text(row.get("商户单号")),
                raw_file=str(path.relative_to(ROOT)),
                category=clean_text(row.get("交易类型")),
            )
        )
    return transactions


BANK_LINE_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})\s+CNY\s+(?P<amount>-?[\d,]+\.\d{2})\s+(?P<balance>-?[\d,]+\.\d{2})\s+(?P<rest>.+)$"
)


def split_bank_rest(rest: str) -> tuple[str, str, str]:
    tokens = rest.split()
    if not tokens:
        return "", "", ""
    summary_keywords = [
        "银联无卡自助消费",
        "银联快捷支付",
        "银联代付",
        "网联收款",
        "汇入汇款",
        "转账汇款",
        "快捷支付",
        "退货",
    ]
    for keyword in sorted(summary_keywords, key=len, reverse=True):
        if rest.startswith(keyword):
            return keyword, clean_text(rest[len(keyword) :]), ""
    summary = tokens[0]
    counterparty = " ".join(tokens[1:])
    return summary, counterparty, ""


def parse_bank_pdf(path: Path) -> list[NormalizedTransaction]:
    try:
        import pdfplumber
    except Exception as exc:  # pragma: no cover - environment guard
        raise RuntimeError("解析银行 PDF 需要 pdfplumber。") from exc

    transactions = []
    pending_counterparty = ""
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for raw_line in (page.extract_text() or "").splitlines():
                line = clean_text(raw_line)
                match = BANK_LINE_RE.match(line)
                if not match:
                    if line and not line.startswith(("招商银行", "Transaction", "Date ", "记账日期", "户 名", "Name ", "账户类型", "Account", "申请时间")) and not re.match(r"^\d+/\d+$", line):
                        pending_counterparty = line
                    continue
                summary, inline_counterparty, notes = split_bank_rest(match.group("rest"))
                counterparty = inline_counterparty or pending_counterparty
                pending_counterparty = ""
                amount = money(match.group("amount"))
                direction = "收入" if amount > 0 else "支出" if amount < 0 else "中性"
                transactions.append(
                    NormalizedTransaction(
                        source="bank",
                        source_name="招商银行",
                        transaction_time=match.group("date"),
                        transaction_date=match.group("date"),
                        direction=direction,
                        amount=round(amount, 2),
                        original_amount=round(abs(amount), 2),
                        counterparty=clean_text(counterparty),
                        description=summary,
                        payment_method="招商银行储蓄卡(1415)",
                        status="已记账",
                        transaction_id="",
                        merchant_order_id="",
                        raw_file=str(path.relative_to(ROOT)),
                        category=summary,
                        notes=notes,
                    )
                )
    return transactions


def parse_all_sources() -> tuple[list[NormalizedTransaction], list[dict[str, Any]]]:
    transactions: list[NormalizedTransaction] = []
    source_status = []
    ledger_rules = load_ledger_rules()
    channel_rules = channel_rules_from_config(ledger_rules)
    parsers = [
        ("bank", "银行流水", "bank", {".pdf"}, parse_bank_pdf),
        ("wechat_pay", "微信支付账单", "wechat-pay", {".xlsx", ".xls"}, parse_wechat),
        ("alipay", "支付宝账单", "alipay", {".csv"}, parse_alipay),
    ]
    for source_id, name, folder, extensions, parser in parsers:
        files = source_files(folder, extensions)
        count_before = len(transactions)
        errors = []
        for path in files:
            try:
                transactions.extend(parser(path))
            except Exception as exc:
                errors.append(f"{path.name}: {exc}")
        parsed_count = len(transactions) - count_before
        source_status.append(
            {
                "id": source_id,
                "name": name,
                "folder": f"data/finance-inbox/{folder}",
                "file_count": len(files),
                "parsed_count": parsed_count,
                "status": "ready" if parsed_count else "failed" if errors else "waiting_files",
                "errors": errors,
            }
        )
    for item in transactions:
        classify_channel(item, channel_rules)
        assign_ledger(item, ledger_rules)
    return transactions, source_status


def summarize(transactions: list[NormalizedTransaction]) -> dict[str, Any]:
    by_source: dict[str, dict[str, Any]] = {}
    by_channel: dict[str, dict[str, Any]] = {}
    daily: dict[tuple[str, str], dict[str, Any]] = {}
    for item in transactions:
        source = by_source.setdefault(
            item.source,
            {
                "source": item.source,
                "source_name": item.source_name,
                "count": 0,
                "income": 0.0,
                "expense": 0.0,
                "neutral": 0.0,
                "net": 0.0,
            },
        )
        source["count"] += 1
        if item.amount > 0:
            source["income"] += item.amount
        elif item.amount < 0:
            source["expense"] += abs(item.amount)
        else:
            source["neutral"] += abs(item.original_amount)
        source["net"] += item.amount

        channel_key = item.channel_id or "unknown"
        channel = by_channel.setdefault(
            channel_key,
            {
                "channel_id": channel_key,
                "channel_name": item.channel_name or "未知渠道",
                "channel_group": item.channel_group or "待确认渠道",
                "ledger_scope": item.ledger_scope or "manual_review",
                "count": 0,
                "income": 0.0,
                "expense": 0.0,
                "neutral": 0.0,
                "net": 0.0,
                "sample_counterparties": [],
            },
        )
        channel["count"] += 1
        if item.amount > 0:
            channel["income"] += item.amount
        elif item.amount < 0:
            channel["expense"] += abs(item.amount)
        else:
            channel["neutral"] += abs(item.original_amount)
        channel["net"] += item.amount
        if item.counterparty and item.counterparty not in channel["sample_counterparties"] and len(channel["sample_counterparties"]) < 5:
            channel["sample_counterparties"].append(item.counterparty)

        key = (item.source, item.transaction_date)
        row = daily.setdefault(
            key,
            {
                "source": item.source,
                "source_name": item.source_name,
                "date": item.transaction_date,
                "count": 0,
                "income": 0.0,
                "expense": 0.0,
                "net": 0.0,
            },
        )
        row["count"] += 1
        if item.amount > 0:
            row["income"] += item.amount
        elif item.amount < 0:
            row["expense"] += abs(item.amount)
        else:
            row["neutral"] = round(float(row.get("neutral", 0.0)) + abs(item.original_amount), 2)
        row["net"] += item.amount

    for bucket in list(by_source.values()) + list(by_channel.values()) + list(daily.values()):
        for key in ("income", "expense", "neutral", "net"):
            if key in bucket:
                bucket[key] = round(bucket[key], 2)
    return {
        "by_source": sorted(by_source.values(), key=lambda item: item["source"]),
        "by_channel": sorted(by_channel.values(), key=lambda item: (item["channel_group"], -abs(float(item["net"])), item["channel_name"])),
        "daily": sorted(daily.values(), key=lambda item: (item["date"], item["source"])),
    }


def add_amount(bucket: dict[str, Any], item: NormalizedTransaction) -> None:
    bucket["count"] += 1
    if item.amount > 0:
        bucket["income"] += item.amount
    elif item.amount < 0:
        bucket["expense"] += abs(item.amount)
    else:
        bucket["neutral"] += abs(item.original_amount)
    bucket["net"] += item.amount


def round_money_fields(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for row in rows:
        for key in ("income", "expense", "neutral", "net"):
            row[key] = round(float(row.get(key, 0.0)), 2)
    return rows


def build_monthly_ledger_preview(transactions: list[NormalizedTransaction], ledger_rules: dict[str, Any]) -> dict[str, Any]:
    ledgers = ledger_rules.get("monthly_ledgers") or []
    ledger_names = ledger_name_map(ledger_rules)
    formal_ledger_ids = [str(item.get("id") or "") for item in ledgers if item.get("id")]
    period_rows: dict[tuple[str, str], dict[str, Any]] = {}
    pool_rows: dict[tuple[str, str], dict[str, Any]] = {}

    def base_row(period: str, ledger_id: str, ledger_name: str, ledger_type: str, status: str) -> dict[str, Any]:
        return {
            "period": period,
            "ledger_id": ledger_id,
            "ledger_name": ledger_name,
            "ledger_type": ledger_type,
            "status": status,
            "count": 0,
            "income": 0.0,
            "expense": 0.0,
            "neutral": 0.0,
            "net": 0.0,
            "sample_channels": [],
            "sample_counterparties": [],
        }

    periods = sorted({month_key(item.transaction_date) for item in transactions}) or [datetime.now().strftime("%Y-%m")]
    for period in periods:
        for ledger in ledgers:
            ledger_id = str(ledger.get("id") or "")
            if not ledger_id:
                continue
            period_rows[(period, ledger_id)] = base_row(
                period,
                ledger_id,
                str(ledger.get("name") or ledger_id),
                str(ledger.get("type") or "ledger"),
                "assigned" if ledger_id == "supply_chain_sales" else "waiting_store_mapping",
            )

    for item in transactions:
        period = month_key(item.transaction_date)
        target = item.ledger_id or "manual_review"
        if target in formal_ledger_ids:
            row = period_rows.setdefault(
                (period, target),
                base_row(period, target, ledger_names.get(target, target), "ledger", "assigned"),
            )
            if item.ledger_status == "assigned":
                row["status"] = "assigned"
        else:
            row = pool_rows.setdefault(
                (period, target),
                base_row(period, target, item.ledger_name or target, "work_pool", item.ledger_status or "manual_review_required"),
            )
        add_amount(row, item)
        if item.channel_name and item.channel_name not in row["sample_channels"] and len(row["sample_channels"]) < 5:
            row["sample_channels"].append(item.channel_name)
        if item.counterparty and item.counterparty not in row["sample_counterparties"] and len(row["sample_counterparties"]) < 5:
            row["sample_counterparties"].append(item.counterparty)

    formal_rows = sorted(period_rows.values(), key=lambda item: (item["period"], item["ledger_id"]))
    pool_values = sorted(pool_rows.values(), key=lambda item: (item["period"], item["status"], -abs(float(item["net"])), item["ledger_name"]))
    round_money_fields(formal_rows)
    round_money_fields(pool_values)
    assigned = [row for row in formal_rows if row["count"] and row["status"] == "assigned"]
    formal_with_activity = [row for row in formal_rows if row["count"]]
    pending = [row for row in pool_values if row["count"]]
    return {
        "status": "preview_only_waiting_store_mapping" if pending else "preview_ready",
        "message": "已生成 6 本月度账雏形；门店类流水暂入门店待分配池，等待平台店铺、订单或手动规则归属到具体门店。",
        "formal_ledgers": formal_rows,
        "work_pools": pool_values,
        "summary": {
            "period_count": len(periods),
            "formal_ledger_count": len(formal_ledger_ids),
            "assigned_formal_ledger_count": len(assigned),
            "active_formal_ledger_count": len(formal_with_activity),
            "work_pool_count": len(pending),
            "pending_transaction_count": sum(int(row.get("count") or 0) for row in pending),
            "assigned_income": round(sum(float(row.get("income") or 0) for row in assigned), 2),
            "assigned_expense": round(sum(float(row.get("expense") or 0) for row in assigned), 2),
            "pending_income": round(sum(float(row.get("income") or 0) for row in pending), 2),
            "pending_expense": round(sum(float(row.get("expense") or 0) for row in pending), 2),
        },
    }


def source_needs_bank_match(item: NormalizedTransaction) -> bool:
    if item.source not in {"wechat_pay", "alipay"}:
        return False
    if "招商银行" not in item.payment_method and "1415" not in item.payment_method:
        return False
    if item.amount == 0:
        return False
    if "关闭" in item.status:
        return False
    return True


def reconcile_bank(transactions: list[NormalizedTransaction]) -> dict[str, Any]:
    bank = [item for item in transactions if item.source == "bank"]
    bank_candidates: dict[tuple[str, float], list[int]] = defaultdict(list)
    for index, item in enumerate(bank):
        bank_candidates[(item.transaction_date, round(item.amount, 2))].append(index)

    matched_bank_indexes: set[int] = set()
    matches = []
    unmatched_payment = []
    for item in [tx for tx in transactions if source_needs_bank_match(tx)]:
        tx_date = parse_time(item.transaction_time)
        candidate_indexes = []
        if tx_date:
            for offset in (0, 1, -1):
                date_text = (tx_date + timedelta(days=offset)).strftime("%Y-%m-%d")
                candidate_indexes.extend(bank_candidates.get((date_text, round(item.amount, 2)), []))
        candidate_indexes = [idx for idx in candidate_indexes if idx not in matched_bank_indexes]
        if candidate_indexes:
            index = candidate_indexes[0]
            matched_bank_indexes.add(index)
            bank_item = bank[index]
            match_id = f"{item.source}:{item.transaction_id or item.merchant_order_id}:bank:{index}"
            item.match_status = "matched_bank_amount_date"
            item.match_id = match_id
            bank_item.match_status = "matched_payment_amount_date"
            bank_item.match_id = match_id
            matches.append(
                {
                    "match_id": match_id,
                    "payment_source": item.source_name,
                    "payment_time": item.transaction_time,
                    "payment_amount": item.amount,
                    "payment_counterparty": item.counterparty,
                    "payment_description": item.description,
                    "payment_transaction_id": item.transaction_id,
                    "bank_date": bank_item.transaction_date,
                    "bank_amount": bank_item.amount,
                    "bank_counterparty": bank_item.counterparty,
                    "bank_description": bank_item.description,
                    "match_rule": "same signed amount within 1 day, payment method 招商银行(1415)",
                }
            )
        else:
            unmatched_payment.append(item)

    unmatched_bank = [
        item
        for index, item in enumerate(bank)
        if index not in matched_bank_indexes and item.amount < 0 and ("微信" in item.counterparty or "支付宝" in item.counterparty or "快捷支付" in item.description)
    ]

    return {
        "matched_count": len(matches),
        "unmatched_payment_count": len(unmatched_payment),
        "unmatched_bank_payment_like_count": len(unmatched_bank),
        "matches": matches[:100],
        "unmatched_payment_samples": [public_tx(item) for item in unmatched_payment[:50]],
        "unmatched_bank_samples": [public_tx(item) for item in unmatched_bank[:50]],
    }


def public_tx(item: NormalizedTransaction) -> dict[str, Any]:
    return {
        "source": item.source_name,
        "time": item.transaction_time,
        "direction": item.direction,
        "amount": item.amount,
        "original_amount": item.original_amount,
        "counterparty": item.counterparty,
        "description": item.description,
        "payment_method": item.payment_method,
        "status": item.status,
        "category": item.category,
        "channel_id": item.channel_id,
        "channel_name": item.channel_name,
        "channel_group": item.channel_group,
        "channel_rule": item.channel_rule,
        "ledger_scope": item.ledger_scope,
        "ledger_id": item.ledger_id,
        "ledger_name": item.ledger_name,
        "ledger_status": item.ledger_status,
        "ledger_rule": item.ledger_rule,
        "match_status": item.match_status,
    }


def channel_review_samples(transactions: list[NormalizedTransaction]) -> list[dict[str, Any]]:
    samples = [
        item
        for item in transactions
        if item.channel_group == "待确认渠道" and item.amount != 0
    ]
    samples.sort(key=lambda item: abs(item.amount), reverse=True)
    return [public_tx(item) for item in samples[:80]]


def build_profit_preview(transactions: list[NormalizedTransaction]) -> dict[str, Any]:
    by_source = summarize(transactions)["by_source"]
    by_channel = summarize(transactions)["by_channel"]
    ledger_rules = load_ledger_rules()
    payment_expense = sum(abs(item.amount) for item in transactions if item.source in {"wechat_pay", "alipay"} and item.amount < 0 and "关闭" not in item.status)
    payment_income = sum(item.amount for item in transactions if item.source in {"wechat_pay", "alipay"} and item.amount > 0)
    bank_income = sum(item.amount for item in transactions if item.source == "bank" and item.amount > 0)
    bank_expense = sum(abs(item.amount) for item in transactions if item.source == "bank" and item.amount < 0)
    return {
        "status": "preview_only_waiting_store_and_platform_income",
        "message": "已可汇总支付流水，但缺少门店基础表、外卖平台收入账单和订单主账明细，暂不生成正式门店损益表。",
        "preliminary_totals": {
            "payment_statement_income": round(payment_income, 2),
            "payment_statement_expense": round(payment_expense, 2),
            "bank_income": round(bank_income, 2),
            "bank_expense": round(bank_expense, 2),
        },
        "source_totals": by_source,
        "channel_totals": by_channel,
        "monthly_ledgers": ledger_rules.get("monthly_ledgers") or [],
        "ledger_assignment_policy": ledger_rules.get("ledger_assignment_policy") or {},
        "monthly_ledger_preview": build_monthly_ledger_preview(transactions, ledger_rules),
        "needed_for_store_pnl": [
            "门店基础表：用于把收货地址、店铺名、供应商规则归到门店。",
            "外卖平台收入账单：用于确认每家门店收入、佣金、配送费、退款、补贴。",
            "订货订单主账：用于把微信/支付宝/银行卡支出对应到快驴、淘宝、拼多多、微信群订单。",
        ],
    }


def write_outputs(payload: dict[str, Any], transactions: list[NormalizedTransaction]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LATEST_PATH.chmod(0o644)

    csv_path = OUTPUT_DIR / "normalized_transactions.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        fieldnames = list(asdict(transactions[0]).keys()) if transactions else list(NormalizedTransaction("", "", "", "", "", 0, 0, "", "", "", "", "", "", "").__dict__.keys())
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for item in transactions:
            writer.writerow(asdict(item))
    csv_path.chmod(0o600)

    ledger_csv_path = OUTPUT_DIR / "monthly_ledger_preview.csv"
    ledger_preview = payload.get("monthly_ledger_preview") or {}
    ledger_rows = (ledger_preview.get("formal_ledgers") or []) + (ledger_preview.get("work_pools") or [])
    with ledger_csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        fieldnames = [
            "period",
            "ledger_id",
            "ledger_name",
            "ledger_type",
            "status",
            "count",
            "income",
            "expense",
            "neutral",
            "net",
            "sample_channels",
            "sample_counterparties",
        ]
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in ledger_rows:
            writable = dict(row)
            writable["sample_channels"] = "、".join(writable.get("sample_channels") or [])
            writable["sample_counterparties"] = "、".join(writable.get("sample_counterparties") or [])
            writer.writerow({key: writable.get(key, "") for key in fieldnames})
    ledger_csv_path.chmod(0o600)


def build_payload() -> dict[str, Any]:
    ledger_rules = load_ledger_rules()
    transactions, source_status = parse_all_sources()
    summary = summarize(transactions)
    reconciliation = reconcile_bank(transactions)
    monthly_ledger_preview = build_monthly_ledger_preview(transactions, ledger_rules)
    profit_preview = build_profit_preview(transactions)
    ready_sources = sum(1 for item in source_status if item["status"] == "ready")
    status = "ready_for_manual_review" if ready_sources >= 3 else "waiting_statements"
    return {
        "generated_at": now_text(),
        "status": status,
        "mode": "preview_only",
        "source_status": source_status,
        "summary": {
            "transaction_count": len(transactions),
            "ready_source_count": ready_sources,
            "source_count": len(source_status),
            "matched_bank_payment_count": reconciliation["matched_count"],
            "unmatched_payment_count": reconciliation["unmatched_payment_count"],
            "unmatched_bank_payment_like_count": reconciliation["unmatched_bank_payment_like_count"],
        },
        "source_summary": summary["by_source"],
        "channel_summary": summary["by_channel"],
        "daily_summary": summary["daily"],
        "bank_reconciliation": reconciliation,
        "channel_review_samples": channel_review_samples(transactions),
        "monthly_ledger_preview": monthly_ledger_preview,
        "ledger_rules": {
            "path": str(LEDGER_RULES_PATH.relative_to(ROOT)),
            "version": ledger_rules.get("version"),
            "monthly_ledgers": ledger_rules.get("monthly_ledgers") or [],
            "ledger_assignment_policy": ledger_rules.get("ledger_assignment_policy") or {},
        },
        "profit_preview": profit_preview,
        "outputs": {
            "latest_json": str(LATEST_PATH.relative_to(ROOT)),
            "normalized_transactions_csv": str((OUTPUT_DIR / "normalized_transactions.csv").relative_to(ROOT)),
            "monthly_ledger_preview_csv": str((OUTPUT_DIR / "monthly_ledger_preview.csv").relative_to(ROOT)),
        },
        "blocked_actions": [
            "自动转账",
            "自动付款",
            "自动提交正式财务结果",
            "上传真实流水到 GitHub",
        ],
        "message": "三方支付流水核对预览已生成，等待门店基础表、平台收入账单和订单主账后生成门店损益表。",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="生成微信、支付宝和银行流水的只读核对预览。")
    parser.add_argument("--strict", action="store_true", help="失败时返回非 0。")
    args = parser.parse_args()

    record_task_event(TASK_ID, "running", message="财务三方流水核对预览开始。", step="payment-reconciliation-preview")
    try:
        payload = build_payload()
        transactions, _ = parse_all_sources()
        # Reconcile mutates match fields, so rebuild once for output consistency.
        reconcile_bank(transactions)
        write_outputs(payload, transactions)
        run_status = "success" if payload["status"] == "ready_for_manual_review" else "skipped"
        record_task_event(
            TASK_ID,
            run_status,
            message=payload["message"],
            step="payment-reconciliation-preview",
            log_path=LATEST_PATH,
            extra=payload["summary"],
        )
        print(payload["message"])
        return 0
    except Exception as exc:
        message = f"财务三方流水核对预览失败：{exc}"
        record_task_event(
            TASK_ID,
            "failed",
            message=message,
            step="payment-reconciliation-preview",
            failure_type=classify_failure_text(message),
        )
        print(message, file=sys.stderr)
        return 1 if args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
