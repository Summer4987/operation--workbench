from __future__ import annotations

import argparse
import csv
import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "ai-business-center" / "config" / "finance_schema.json"
DEFAULT_DATA_DIR = ROOT / "data" / "finance-inbox" / "manual-matches"
DATA_DIR = Path(os.environ.get("FINANCE_INBOX_DIR", DEFAULT_DATA_DIR))
DRAFTS_PATH = Path(os.environ.get("FINANCE_DRAFTS_PATH", DATA_DIR / "finance_drafts.jsonl"))
LEDGER_PATH = Path(os.environ.get("FINANCE_LEDGER_PATH", DATA_DIR / "finance_ledger.jsonl"))
LEDGER_CSV_PATH = Path(os.environ.get("FINANCE_LEDGER_CSV_PATH", DATA_DIR / "finance_ledger.csv"))

DRAFT_PENDING = "pending_confirmation"
DRAFT_CONFIRMED = "confirmed_to_ledger"
VALID_DIRECTIONS = {"income", "expense", "transfer", "unknown"}
CONFIRMABLE_DIRECTIONS = {"income", "expense", "transfer"}
VALID_CATEGORIES = {
    "platform_income",
    "procurement",
    "rent",
    "salary",
    "utility",
    "marketing",
    "refund",
    "transfer",
    "other",
    "unknown",
}
CONFIRMABLE_CATEGORIES = VALID_CATEGORIES - {"unknown"}
VALID_PAYMENT_METHODS = {"wechat_pay", "alipay", "bank", "cash", "platform_balance", "unknown"}
LEDGER_FIELD_ORDER = [
    "ledger_id",
    "draft_id",
    "confirmed_at",
    "confirmed_by",
    "transaction_date",
    "direction",
    "amount",
    "currency",
    "store",
    "counterparty",
    "category",
    "payment_method",
    "source_channel",
    "raw_text",
    "note",
    "sync_status",
    "sync_marked_ready_at",
    "sync_marked_ready_by",
    "synced_at",
    "feishu_record_id",
    "sync_error",
]


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_date() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def short_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    path.chmod(0o600)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"无法解析 {path} 第 {line_number} 行：{exc}") from exc
    return records


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)


def parse_amount(text: str) -> tuple[float | None, list[str]]:
    warnings: list[str] = []
    amount_pattern = r"([0-9]+(?:,[0-9]{3})*(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)"
    matches = re.findall(rf"(?:￥|¥|人民币|RMB|rmb)\s*{amount_pattern}", text)
    matches.extend(re.findall(rf"{amount_pattern}\s*(?:元|块|圆)", text))
    if not matches:
        matches = re.findall(rf"(?<![\d./-]){amount_pattern}(?![\d./-])", text)
        if matches:
            warnings.append("金额没有明确币种或单位，默认取识别数字，确认前请核对。")
    amounts: list[float] = []
    seen_amounts: set[float] = set()
    for match in matches:
        try:
            value = float(match.replace(",", ""))
        except ValueError:
            continue
        if value > 0 and value not in seen_amounts:
            amounts.append(value)
            seen_amounts.add(value)
    if not amounts:
        warnings.append("未识别金额，确认前必须手动补充。")
        return None, warnings
    if len(amounts) > 1:
        warnings.append(f"识别到多个金额 {amounts}，默认取第一个，确认前请核对。")
    return amounts[0], warnings


def parse_date(text: str) -> tuple[str | None, list[str]]:
    warnings: list[str] = []
    full = re.search(r"(?<![\d.])(20[0-9]{2})[-/.年](1[0-2]|0?[1-9])[-/.月](3[01]|[12][0-9]|0?[1-9])(?:日|号)?(?![\d.])", text)
    if full:
        year, month, day = full.groups()
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}", warnings
    if "今天" in text:
        return today_date(), warnings
    month_day = re.search(r"(?<![\d.])(1[0-2]|0?[1-9])[-/.月](3[01]|[12][0-9]|0?[1-9])(?:日|号)?(?![\d.])", text)
    if month_day:
        month, day = month_day.groups()
        return f"{datetime.now().year:04d}-{int(month):02d}-{int(day):02d}", warnings
    if "昨日" in text or "昨天" in text:
        warnings.append("文本包含昨天/昨日，MVP 不自动推算跨日日期，请确认业务日期。")
    else:
        warnings.append("未识别业务日期，默认用今天，确认前请核对。")
    return today_date(), warnings


def parse_direction(text: str) -> tuple[str, list[str]]:
    warnings: list[str] = []
    expense_words = ("付款", "支出", "支付", "采购", "房租", "工资", "水电", "扣款", "报销", "转出")
    income_words = ("收入", "收款", "到账", "入账", "回款", "结算", "营业额", "转入")
    transfer_words = ("内部转账", "转账到", "备用金")
    has_expense = any(word in text for word in expense_words)
    has_income = any(word in text for word in income_words)
    has_transfer = any(word in text for word in transfer_words)
    if has_transfer:
        return "transfer", warnings
    if has_expense and not has_income:
        return "expense", warnings
    if has_income and not has_expense:
        return "income", warnings
    warnings.append("未能唯一判断收支方向，请人工确认。")
    return "unknown", warnings


def parse_category(text: str, direction: str) -> str:
    rules = [
        ("platform_income", ("美团", "饿了么", "平台结算", "营业额", "外卖收入")),
        ("procurement", ("采购", "进货", "货款", "快驴", "供应商", "原料")),
        ("rent", ("房租", "租金", "物业")),
        ("salary", ("工资", "薪资", "社保", "个税")),
        ("utility", ("水费", "电费", "燃气", "水电")),
        ("marketing", ("推广", "广告", "点金", "营销")),
        ("refund", ("退款", "退回")),
        ("transfer", ("内部转账", "备用金", "转账到")),
    ]
    for category, keywords in rules:
        if any(keyword in text for keyword in keywords):
            return category
    if direction == "income":
        return "platform_income" if any(word in text for word in ("平台", "结算", "营业")) else "other"
    if direction == "transfer":
        return "transfer"
    return "unknown"


def parse_payment_method(text: str) -> str:
    if any(word in text for word in ("微信", "微信零钱", "微信支付")):
        return "wechat_pay"
    if "支付宝" in text:
        return "alipay"
    if any(word in text for word in ("银行", "对公", "银行卡", "网银")):
        return "bank"
    if "现金" in text:
        return "cash"
    if "平台余额" in text:
        return "platform_balance"
    return "unknown"


def parse_store(text: str) -> str:
    match = re.search(r"(熊小小[^\s，,。；;：:]{0,12}(?:店|中心|城|门店)?)", text)
    return match.group(1).strip() if match else ""


def parse_counterparty(text: str) -> str:
    patterns = [
        r"(?:供应商|付款给|收款方|对方|商户|户名)[:： ]+([^\s，,。；;]+)",
        r"向([^\s，,。；;]+)(?:付款|支付|转账)",
        r"收到([^\s，,。；;]+)(?:付款|转账|回款)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return ""


def parse_wechat_text(text: str) -> dict[str, Any]:
    warnings: list[str] = []
    amount, amount_warnings = parse_amount(text)
    transaction_date, date_warnings = parse_date(text)
    direction, direction_warnings = parse_direction(text)
    warnings.extend(amount_warnings)
    warnings.extend(date_warnings)
    warnings.extend(direction_warnings)
    category = parse_category(text, direction)
    if category == "unknown":
        warnings.append("未识别财务分类，确认前必须手动选择。")
    payment_method = parse_payment_method(text)
    if payment_method == "unknown":
        warnings.append("未识别收付款方式，确认前建议补充。")
    return {
        "parsed_transaction_date": transaction_date,
        "parsed_direction": direction,
        "parsed_amount": amount,
        "parsed_currency": "CNY",
        "parsed_store": parse_store(text),
        "parsed_counterparty": parse_counterparty(text),
        "parsed_category": category,
        "parsed_payment_method": payment_method,
        "parse_warnings": warnings,
    }


def latest_draft_states() -> dict[str, dict[str, Any]]:
    states: dict[str, dict[str, Any]] = {}
    for record in read_jsonl(DRAFTS_PATH):
        draft_id = str(record.get("draft_id") or "")
        if draft_id:
            states[draft_id] = record
    return states


def ledger_draft_ids() -> set[str]:
    return {str(record.get("draft_id") or "") for record in read_jsonl(LEDGER_PATH) if record.get("draft_id")}


def replace_ledger(updated: dict[str, Any]) -> None:
    records = read_jsonl(LEDGER_PATH)
    found = False
    for index, record in enumerate(records):
        if record.get("ledger_id") == updated.get("ledger_id"):
            records[index] = updated
            found = True
            break
    if not found:
        raise SystemExit(f"未找到账本记录：{updated.get('ledger_id')}")
    write_jsonl(LEDGER_PATH, records)
    export_ledger_csv()


def replace_draft(updated: dict[str, Any]) -> None:
    records = read_jsonl(DRAFTS_PATH)
    found = False
    for index, record in enumerate(records):
        if record.get("draft_id") == updated.get("draft_id"):
            records[index] = updated
            found = True
            break
    if not found:
        records.append(updated)
    write_jsonl(DRAFTS_PATH, records)


def require_choice(value: str, valid: set[str], label: str) -> str:
    clean = value.strip()
    if clean not in valid:
        raise SystemExit(f"{label} 无效：{clean}。可选：{', '.join(sorted(valid))}")
    return clean


def require_amount(value: Any) -> float:
    try:
        amount = float(value)
    except (TypeError, ValueError) as exc:
        raise SystemExit("金额缺失或无法解析；请用 --amount 手动指定。") from exc
    if amount <= 0:
        raise SystemExit("金额必须大于 0。")
    return round(amount, 2)


def export_ledger_csv(path: Path = LEDGER_CSV_PATH) -> None:
    records = read_jsonl(LEDGER_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LEDGER_FIELD_ORDER, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    path.chmod(0o600)


def command_intake(args: argparse.Namespace) -> int:
    raw_text = args.text.strip()
    if not raw_text:
        raise SystemExit("请输入非空微信财务文本。")
    parsed = parse_wechat_text(raw_text)
    draft = {
        "draft_id": short_id("fin-draft"),
        "created_at": now_text(),
        "created_by": args.operator.strip(),
        "status": DRAFT_PENDING,
        "source_channel": "wechat_text",
        "raw_text": raw_text,
        **parsed,
        "safety_notice": "本记录只是待确认草稿，不会自动写入账本或飞书。",
    }
    append_jsonl(DRAFTS_PATH, draft)
    print(f"已录入财务草稿：{draft['draft_id']}")
    print(f"状态：{DRAFT_PENDING}，不会自动确认或发布。")
    if draft["parse_warnings"]:
        print("解析提醒：" + "；".join(draft["parse_warnings"]))
    print(f"草稿文件：{DRAFTS_PATH}")
    return 0


def command_list_drafts(args: argparse.Namespace) -> int:
    drafts = list(latest_draft_states().values())
    confirmed_ids = ledger_draft_ids()
    pending = [
        draft
        for draft in drafts
        if draft.get("status") == DRAFT_PENDING and draft.get("draft_id") not in confirmed_ids
    ]
    items = pending if args.pending_only else drafts
    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return 0
    if not items:
        print("没有财务草稿。")
        return 0
    for draft in items:
        amount = draft.get("parsed_amount")
        amount_text = "" if amount is None else f"{amount:g}"
        warnings = draft.get("parse_warnings") or []
        print(
            " | ".join(
                [
                    str(draft.get("draft_id") or ""),
                    str(draft.get("status") or ""),
                    str(draft.get("parsed_transaction_date") or ""),
                    str(draft.get("parsed_direction") or ""),
                    amount_text,
                    str(draft.get("parsed_category") or ""),
                    str(draft.get("parsed_store") or ""),
                    f"warnings={len(warnings)}",
                ]
            )
        )
    return 0


def command_confirm(args: argparse.Namespace) -> int:
    draft_id = args.draft_id.strip()
    drafts = latest_draft_states()
    draft = drafts.get(draft_id)
    if not draft:
        raise SystemExit(f"未找到草稿：{draft_id}")
    if draft.get("status") != DRAFT_PENDING:
        raise SystemExit(f"草稿不是待确认状态：{draft.get('status')}")
    if draft_id in ledger_draft_ids():
        raise SystemExit(f"草稿已经进入账本：{draft_id}")
    operator = args.operator.strip()
    if not operator:
        raise SystemExit("确认账本必须提供 --operator。")

    transaction_date = (args.transaction_date or draft.get("parsed_transaction_date") or "").strip()
    if not re.fullmatch(r"20[0-9]{2}-[01][0-9]-[0-3][0-9]", transaction_date):
        raise SystemExit("业务日期必须是 YYYY-MM-DD；可用 --transaction-date 指定。")
    direction = require_choice(args.direction or draft.get("parsed_direction") or "", CONFIRMABLE_DIRECTIONS, "收支方向")
    category = require_choice(args.category or draft.get("parsed_category") or "", CONFIRMABLE_CATEGORIES, "财务分类")
    payment_method = require_choice(args.payment_method or draft.get("parsed_payment_method") or "unknown", VALID_PAYMENT_METHODS, "收付款方式")
    amount = require_amount(args.amount if args.amount is not None else draft.get("parsed_amount"))
    ledger = {
        "ledger_id": short_id("fin-ledger"),
        "draft_id": draft_id,
        "confirmed_at": now_text(),
        "confirmed_by": operator,
        "transaction_date": transaction_date,
        "direction": direction,
        "amount": amount,
        "currency": "CNY",
        "store": (args.store if args.store is not None else draft.get("parsed_store") or "").strip(),
        "counterparty": (args.counterparty if args.counterparty is not None else draft.get("parsed_counterparty") or "").strip(),
        "category": category,
        "payment_method": payment_method,
        "source_channel": draft.get("source_channel") or "wechat_text",
        "raw_text": draft.get("raw_text") or "",
        "note": args.note.strip(),
        "sync_status": "local_only",
    }
    append_jsonl(LEDGER_PATH, ledger)
    export_ledger_csv()

    updated_draft = dict(draft)
    updated_draft["status"] = DRAFT_CONFIRMED
    updated_draft["confirmed_at"] = ledger["confirmed_at"]
    updated_draft["ledger_id"] = ledger["ledger_id"]
    updated_draft["confirmed_by"] = operator
    replace_draft(updated_draft)

    print(f"已确认到本地账本：{ledger['ledger_id']}")
    print("飞书同步状态：local_only。未自动发布到飞书。")
    print(f"账本 JSONL：{LEDGER_PATH}")
    print(f"账本 CSV：{LEDGER_CSV_PATH}")
    return 0


def command_export(args: argparse.Namespace) -> int:
    if args.format == "csv":
        export_ledger_csv()
        print(f"已导出 CSV：{LEDGER_CSV_PATH}")
    else:
        print(json.dumps(read_jsonl(LEDGER_PATH), ensure_ascii=False, indent=2))
    return 0


def command_list_ledger(args: argparse.Namespace) -> int:
    records = read_jsonl(LEDGER_PATH)
    if args.status:
        records = [record for record in records if record.get("sync_status") == args.status]
    if args.json:
        print(json.dumps(records, ensure_ascii=False, indent=2))
        return 0
    if not records:
        print("没有账本记录。")
        return 0
    for record in records:
        print(
            " | ".join(
                [
                    str(record.get("ledger_id") or ""),
                    str(record.get("transaction_date") or ""),
                    str(record.get("direction") or ""),
                    f"{float(record.get('amount') or 0):.2f}",
                    str(record.get("category") or ""),
                    str(record.get("store") or ""),
                    str(record.get("sync_status") or ""),
                ]
            )
        )
    return 0


def command_mark_ready(args: argparse.Namespace) -> int:
    ledger_id = args.ledger_id.strip()
    operator = args.operator.strip()
    if not operator:
        raise SystemExit("标记飞书待同步必须提供 --operator。")
    records = read_jsonl(LEDGER_PATH)
    ledger = next((record for record in records if record.get("ledger_id") == ledger_id), None)
    if not ledger:
        raise SystemExit(f"未找到账本记录：{ledger_id}")
    if ledger.get("sync_status") == "synced":
        raise SystemExit(f"账本记录已经同步，不能重新标记：{ledger_id}")
    ledger = dict(ledger)
    ledger["sync_status"] = "ready_for_feishu"
    ledger["sync_marked_ready_at"] = now_text()
    ledger["sync_marked_ready_by"] = operator
    ledger.pop("sync_error", None)
    replace_ledger(ledger)
    print(f"已标记为飞书待同步：{ledger_id}")
    print("仍未写入飞书；需另行运行 scripts/finance_feishu_sync.py，并在 token 齐全时显式传入 --execute。")
    return 0


def command_schema(_: argparse.Namespace) -> int:
    print(SCHEMA_PATH.read_text(encoding="utf-8"))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="飞书财务系统 MVP：本地财务草稿收件箱和确认账本，不自动发布。")
    subparsers = parser.add_subparsers(dest="command", required=True)

    intake = subparsers.add_parser("intake", help="录入一条微信财务文本为待确认草稿。")
    intake.add_argument("--text", required=True, help="微信里的财务文本。")
    intake.add_argument("--operator", default="", help="录入人，可选。")
    intake.set_defaults(func=command_intake)

    list_drafts = subparsers.add_parser("list-drafts", help="列出财务草稿。")
    list_drafts.add_argument("--all", dest="pending_only", action="store_false", help="显示全部草稿，包括已确认。")
    list_drafts.add_argument("--json", action="store_true", help="输出 JSON。")
    list_drafts.set_defaults(func=command_list_drafts, pending_only=True)

    confirm = subparsers.add_parser("confirm", help="人工确认草稿并追加到本地账本。")
    confirm.add_argument("--draft-id", required=True, help="待确认草稿 ID。")
    confirm.add_argument("--operator", required=True, help="确认人，必填。")
    confirm.add_argument("--transaction-date", help="覆盖业务日期，格式 YYYY-MM-DD。")
    confirm.add_argument("--direction", choices=sorted(CONFIRMABLE_DIRECTIONS), help="覆盖收支方向。")
    confirm.add_argument("--amount", type=float, help="覆盖金额。")
    confirm.add_argument("--category", choices=sorted(CONFIRMABLE_CATEGORIES), help="覆盖财务分类。")
    confirm.add_argument("--payment-method", choices=sorted(VALID_PAYMENT_METHODS), help="覆盖收付款方式。")
    confirm.add_argument("--store", help="覆盖门店。")
    confirm.add_argument("--counterparty", help="覆盖交易对方。")
    confirm.add_argument("--note", default="", help="确认备注。")
    confirm.set_defaults(func=command_confirm)

    export = subparsers.add_parser("export", help="导出本地账本。")
    export.add_argument("--format", choices=["csv", "jsonl"], default="csv")
    export.set_defaults(func=command_export)

    list_ledger = subparsers.add_parser("list-ledger", help="列出本地确认账本。")
    list_ledger.add_argument("--status", choices=["local_only", "ready_for_feishu", "synced", "sync_failed"], help="按飞书同步状态过滤。")
    list_ledger.add_argument("--json", action="store_true", help="输出 JSON。")
    list_ledger.set_defaults(func=command_list_ledger)

    mark_ready = subparsers.add_parser("mark-ready", help="人工标记一条本地账本为 ready_for_feishu。")
    mark_ready.add_argument("--ledger-id", required=True, help="账本 ID。")
    mark_ready.add_argument("--operator", required=True, help="标记人，必填。")
    mark_ready.set_defaults(func=command_mark_ready)

    schema = subparsers.add_parser("schema", help="打印财务 schema 和飞书字段规划。")
    schema.set_defaults(func=command_schema)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
