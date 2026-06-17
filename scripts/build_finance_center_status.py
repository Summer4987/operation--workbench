from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from task_run_state import classify_failure_text, record_task_event


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "config" / "finance_bill_schema.json"
LEDGER_RULES_PATH = ROOT / "config" / "finance_ledger_rules.json"
RECONCILIATION_PREVIEW_PATH = ROOT / "outputs" / "finance_reconciliation_preview" / "latest.json"
OUTPUT_DIR = ROOT / "outputs" / "finance_center_status"
LATEST_PATH = OUTPUT_DIR / "latest.json"
TASK_ID = "finance.bill_analysis"


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def write_latest(payload: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LATEST_PATH.chmod(0o644)


def sample_files(path_text: str, accepted_extensions: set[str]) -> list[dict[str, Any]]:
    path = ROOT / path_text
    if not path.exists():
        return []
    files = []
    for child in sorted(path.iterdir()):
        if not child.is_file() or child.name.startswith("."):
            continue
        if child.suffix.lower() not in accepted_extensions:
            continue
        files.append(
            {
                "name": child.name,
                "path": str(child.relative_to(ROOT)),
                "extension": child.suffix.lower(),
                "size": child.stat().st_size,
                "updated_at": datetime.fromtimestamp(child.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
    return files


def template_path_for(source_id: str) -> str:
    return f"data/finance-inbox/templates/{source_id}_template.csv"


def all_schema_sources(schema: dict[str, Any]) -> list[dict[str, Any]]:
    sources = []
    for source in schema.get("required_sources") or []:
        item = dict(source)
        item["required"] = True
        sources.append(item)
    for source in schema.get("optional_sources") or []:
        item = dict(source)
        item["required"] = False
        sources.append(item)
    return sources


def intake_checklist(sources: list[dict[str, Any]], accepted_extensions: set[str]) -> list[dict[str, Any]]:
    checklist = []
    extension_text = "、".join(sorted(accepted_extensions)) or ".csv、.xlsx、.xls、.pdf"
    for source in sources:
        fields = source.get("required_fields") or []
        checklist.append(
            {
                "source": source.get("name", ""),
                "path": source.get("path", ""),
                "template_path": source.get("template_path", ""),
                "accepted_extensions": sorted(accepted_extensions),
                "required_fields": fields,
                "message": f"把{source.get('name', '账单')}样例放入 {source.get('path', '')}，可参考 {source.get('template_path', '')}，支持 {extension_text}，至少包含：{'、'.join(fields[:6])}{'等字段' if len(fields) > 6 else ''}。",
            }
        )
    return checklist


def load_order_automation_feed() -> dict[str, Any]:
    order_lists = read_json(ROOT / "outputs" / "inventory_order_lists" / "latest.json", {})
    execution_preview = read_json(ROOT / "outputs" / "inventory_order_execution_preview" / "latest.json", {})
    source_status = execution_preview.get("status") or order_lists.get("status") or "missing"
    previews = execution_preview.get("channel_previews") or []
    order_groups = order_lists.get("order_lists") or []
    channel_count = len(previews) or len(order_groups)
    item_count = int(
        (execution_preview.get("summary") or {}).get("item_count")
        or (order_lists.get("summary") or {}).get("suggestion_count")
        or 0
    )
    estimated_cost = float(
        (execution_preview.get("summary") or {}).get("estimated_cost")
        or (order_lists.get("summary") or {}).get("estimated_cost")
        or 0
    )
    return {
        "source": "outputs/inventory_order_execution_preview/latest.json",
        "fallback_source": "outputs/inventory_order_lists/latest.json",
        "status": source_status,
        "available": bool(channel_count or item_count),
        "channel_count": channel_count,
        "item_count": item_count,
        "estimated_cost": round(estimated_cost, 2),
        "payment_confirmation": execution_preview.get("payment_confirmation") or order_lists.get("confirmation") or {},
        "message": execution_preview.get("message") or order_lists.get("message") or "订货自动化暂未生成订单主账输入。",
    }


def build_daily_collection_design(schema: dict[str, Any], sources: list[dict[str, Any]]) -> dict[str, Any]:
    source_files = {item["id"]: item.get("file_count", 0) for item in sources}
    payment_sources = schema.get("payment_sources") or []
    rows = []
    ready_count = 0
    for source in payment_sources:
        source_id = source.get("id") or ""
        file_count = int(source_files.get(source_id) or 0)
        ready = file_count > 0
        if ready:
            ready_count += 1
        rows.append(
            {
                "id": source_id,
                "name": source.get("name") or source_id,
                "type": source.get("type") or "",
                "daily_inbox": source.get("daily_inbox") or "",
                "file_count": file_count,
                "ready": ready,
                "match_keys": source.get("match_keys") or [],
                "macmini_collection": source.get("macmini_collection") or "",
            }
        )

    policy = schema.get("daily_collection_policy") or {}
    required_count = len(payment_sources)
    status = "ready_for_reconciliation" if required_count and ready_count == required_count else "waiting_daily_statements"
    return {
        "status": status,
        "status_text": "可核对" if status == "ready_for_reconciliation" else "待流水",
        "ready_count": ready_count,
        "required_count": required_count,
        "sources": rows,
        "policy": policy,
        "message": (
            "微信支付、支付宝和银行流水都到位后，可生成每日支付流水核对和损益表预览。"
            if status != "ready_for_reconciliation"
            else "微信支付、支付宝和银行流水已具备，可进入每日核对预览。"
        ),
    }


def build_ledger_design(schema: dict[str, Any], order_feed: dict[str, Any], sources: list[dict[str, Any]]) -> dict[str, Any]:
    source_files = {item["id"]: item.get("file_count", 0) for item in sources}
    procurement_files = source_files.get("procurement_orders", 0) + source_files.get("wechat_orders", 0)
    order_book_ready = bool(procurement_files or order_feed.get("available"))
    payment_ready = all(source_files.get(source.get("id") or "", 0) for source in schema.get("payment_sources") or [{"id": "bank"}])
    stores_ready = bool(source_files.get("stores", 0))
    income_ready = bool(source_files.get("platform_income", 0))
    can_start_matching = order_book_ready and payment_ready and stores_ready
    matching_policy = schema.get("matching_policy") or {}
    return {
        "status": "ready_for_matching" if can_start_matching else "waiting_foundation",
        "tables": [
            {
                "id": "orders",
                "name": "订货订单主账",
                "owner": "订货自动化 + 快驴/淘宝/拼多多/微信群导入",
                "purpose": "先确定每笔成本属于哪家门店。",
                "ready": order_book_ready,
            },
            {
                "id": "bank_transactions",
                "name": "支付流水池",
                "owner": "微信支付 + 支付宝 + 银行流水",
                "purpose": "确认付款、到账、退款和最终资金核销。",
                "ready": payment_ready,
            },
            {
                "id": "payment_matches",
                "name": "付款匹配关系",
                "owner": "自动匹配 + 人工确认",
                "purpose": "把银行流水核销到订单、门店和科目。",
                "ready": can_start_matching,
            },
            {
                "id": "store_monthly_profit",
                "name": "门店月度利润表",
                "owner": "品牌财务中心生成",
                "purpose": "按月合并收入、成本、费用和利润。",
                "ready": can_start_matching and income_ready,
            },
        ],
        "inputs": {
            "order_book_ready": order_book_ready,
            "payment_ready": payment_ready,
            "stores_ready": stores_ready,
            "income_ready": income_ready,
            "procurement_file_count": procurement_files,
            "order_automation_available": bool(order_feed.get("available")),
        },
        "workflow": [
            "订货自动化或订单导入先生成订单主账，并写入门店、来源、供应商和金额。",
            "微信支付、支付宝和银行流水每日导入后，按交易号、金额、日期、供应商关键词和门店规则自动核对。",
            "一对多、合并付款、跨日到账、手续费差异和微信群备注不清等场景进入待确认池。",
            "人工确认结果写入 manual_matches，下次按相同规则自动识别。",
            "外卖收入账单合并后生成每日核对表和每月门店收入、成本、费用、利润。",
        ],
        "policy": matching_policy,
        "message": (
            "订单主账、支付流水和门店基础表到位后，可开始自动付款匹配。"
            if not can_start_matching
            else "订单主账、支付流水和门店基础表已具备，可进入自动付款匹配。"
        ),
    }


def build_payload() -> dict[str, Any]:
    schema = read_json(SCHEMA_PATH, {})
    ledger_rules = read_json(LEDGER_RULES_PATH, {})
    reconciliation_preview = read_json(RECONCILIATION_PREVIEW_PATH, {})
    accepted_extensions = {str(item).lower() for item in schema.get("accepted_extensions", [])}
    inbox = schema.get("sample_inbox") or {}
    sources = []
    missing = []
    for source in all_schema_sources(schema):
        source_id = source.get("id") or ""
        path_text = inbox.get(source_id) or f"data/finance-inbox/{source_id}"
        files = sample_files(path_text, accepted_extensions)
        template_path = template_path_for(source_id)
        inbox_dir = ROOT / path_text
        if source.get("required") and not files:
            missing.append(f"{source.get('name') or source_id}样例")
        sources.append(
            {
                "id": source_id,
                "name": source.get("name") or source_id,
                "required": bool(source.get("required")),
                "path": path_text,
                "directory_ready": inbox_dir.exists(),
                "template_path": template_path,
                "template_ready": (ROOT / template_path).exists(),
                "file_count": len(files),
                "files": files[:8],
                "required_fields": source.get("required_fields") or [],
            }
        )

    accounts = schema.get("accounts") or []
    monthly_ledgers = ledger_rules.get("monthly_ledgers") or []
    ledger_assignment_policy = ledger_rules.get("ledger_assignment_policy") or {}
    order_feed = load_order_automation_feed()
    daily_collection = build_daily_collection_design(schema, sources)
    ledger_design = build_ledger_design(schema, order_feed, sources)
    ready_for_mapping = ledger_design["status"] == "ready_for_matching" and bool(accounts)
    income_ready = ledger_design["inputs"]["income_ready"]
    status = "ready_for_mapping" if ready_for_mapping else "waiting_samples"
    report_status = "waiting_mapping" if ready_for_mapping and not income_ready else "waiting_samples"
    if ready_for_mapping and income_ready:
        report_status = "ready_for_report_preview"
    report_generation = {
        "id": "finance_report_generation",
        "status": report_status,
        "status_text": "待报表预览" if report_status == "ready_for_report_preview" else ("待映射" if ready_for_mapping else "待样例"),
        "account_count": len(accounts),
        "required_before": [
            "订单主账、微信支付、支付宝、银行流水和门店基础表已接收",
            "付款匹配可稳定识别门店和费用科目",
            "外卖收入账单已接收并确认报表期间",
        ],
        "report_outputs": [
            "门店利润表",
            "平台费用明细",
            "推广费和佣金异常提醒",
            "无法自动分类流水清单",
        ],
        "message": "先建立订单主账和支付流水核销，再生成门店利润表和费用异常提醒。"
        if not ready_for_mapping
        else "可进入付款匹配；外卖收入账单到位后生成门店利润表预览。",
    }
    return {
        "generated_at": now_text(),
        "status": status,
        "schema": {
            "path": "config/finance_bill_schema.json",
            "version": schema.get("version"),
            "ledger_rules_path": "config/finance_ledger_rules.json",
            "ledger_rules_version": ledger_rules.get("version"),
            "account_count": len(accounts),
            "accepted_extensions": sorted(accepted_extensions),
        },
        "summary": {
            "source_count": len(sources),
            "sample_file_count": sum(item["file_count"] for item in sources),
            "missing_count": len(missing),
            "account_count": len(accounts),
            "monthly_ledger_count": len(monthly_ledgers),
            "order_source_count": len(schema.get("order_sources") or []),
            "payment_source_count": len(schema.get("payment_sources") or []),
            "ledger_table_count": len(ledger_design["tables"]),
        },
        "sources": sources,
        "accounts": accounts,
        "monthly_ledgers": monthly_ledgers,
        "ledger_assignment_policy": ledger_assignment_policy,
        "finance_channels": {
            "income_channels": ledger_rules.get("income_channels") or [],
            "expense_channels": ledger_rules.get("expense_channels") or [],
            "neutral_channels": ledger_rules.get("neutral_channels") or [],
        },
        "order_sources": schema.get("order_sources") or [],
        "payment_sources": schema.get("payment_sources") or [],
        "daily_collection": daily_collection,
        "reconciliation_preview": {
            "status": reconciliation_preview.get("status") or "not_generated",
            "generated_at": reconciliation_preview.get("generated_at", ""),
            "mode": reconciliation_preview.get("mode", "preview_only"),
            "reporting_period": reconciliation_preview.get("reporting_period") or {},
            "summary": reconciliation_preview.get("summary") or {},
            "source_summary": reconciliation_preview.get("source_summary") or [],
            "channel_summary": reconciliation_preview.get("channel_summary") or [],
            "channel_review_samples": reconciliation_preview.get("channel_review_samples") or [],
            "ledger_review_samples": reconciliation_preview.get("ledger_review_samples") or [],
            "review_rule_groups": reconciliation_preview.get("review_rule_groups") or [],
            "monthly_ledger_preview": reconciliation_preview.get("monthly_ledger_preview") or {},
            "ledger_rules": reconciliation_preview.get("ledger_rules") or {},
            "profit_preview": reconciliation_preview.get("profit_preview") or {},
            "outputs": reconciliation_preview.get("outputs") or {},
            "message": reconciliation_preview.get("message") or "三方流水核对预览尚未生成。",
        },
        "order_automation_feed": order_feed,
        "ledger_design": ledger_design,
        "report_generation": report_generation,
        "missing": missing,
        "intake_checklist": intake_checklist(sources, accepted_extensions),
        "setup": {
            "init_command": "python3 scripts/init_finance_inbox.py",
            "template_dir": "data/finance-inbox/templates",
            "directories_ready": all(item.get("directory_ready") for item in sources),
            "templates_ready": all(item.get("template_ready") for item in sources),
        },
        "next_input_needed": [
            "微信支付账单样例放入 data/finance-inbox/wechat-pay",
            "支付宝账单样例放入 data/finance-inbox/alipay",
            "银行流水样例放入 data/finance-inbox/bank",
            "门店基础表放入 data/finance-inbox/stores",
            "快驴/淘宝/拼多多订单导出放入 data/finance-inbox/procurement-orders，微信群订货记录放入 data/finance-inbox/wechat-orders",
            "美团/饿了么/抖音等平台收入账单放入 data/finance-inbox/platform-income",
        ],
        "message": ledger_design["message"],
    }


def main() -> int:
    record_task_event(TASK_ID, "running", message="品牌财务中心状态检查开始。", step="finance-center-status")
    try:
        payload = build_payload()
        write_latest(payload)
        status = "success" if payload["status"] == "ready_for_mapping" else "skipped"
        record_task_event(
            TASK_ID,
            status,
            message=payload["message"],
            step="finance-center-status",
            extra={
                "finance_status": payload["status"],
                "sample_file_count": payload["summary"]["sample_file_count"],
                "missing_count": payload["summary"]["missing_count"],
                "account_count": payload["summary"]["account_count"],
            },
        )
        print(payload["message"])
        return 0
    except Exception as exc:
        message = f"品牌财务中心状态检查失败：{exc}"
        record_task_event(
            TASK_ID,
            "failed",
            message=message,
            step="finance-center-status",
            failure_type=classify_failure_text(message),
        )
        raise


if __name__ == "__main__":
    raise SystemExit(main())
