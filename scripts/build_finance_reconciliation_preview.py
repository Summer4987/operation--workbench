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
    match_status: str = "unmatched"
    match_id: str = ""
    notes: str = ""


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
    return transactions, source_status


def summarize(transactions: list[NormalizedTransaction]) -> dict[str, Any]:
    by_source: dict[str, dict[str, Any]] = {}
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

    for bucket in list(by_source.values()) + list(daily.values()):
        for key in ("income", "expense", "neutral", "net"):
            if key in bucket:
                bucket[key] = round(bucket[key], 2)
    return {
        "by_source": sorted(by_source.values(), key=lambda item: item["source"]),
        "daily": sorted(daily.values(), key=lambda item: (item["date"], item["source"])),
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
        "match_status": item.match_status,
    }


def build_profit_preview(transactions: list[NormalizedTransaction]) -> dict[str, Any]:
    by_source = summarize(transactions)["by_source"]
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


def build_payload() -> dict[str, Any]:
    transactions, source_status = parse_all_sources()
    summary = summarize(transactions)
    reconciliation = reconcile_bank(transactions)
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
        "daily_summary": summary["daily"],
        "bank_reconciliation": reconciliation,
        "profit_preview": profit_preview,
        "outputs": {
            "latest_json": str(LATEST_PATH.relative_to(ROOT)),
            "normalized_transactions_csv": str((OUTPUT_DIR / "normalized_transactions.csv").relative_to(ROOT)),
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
