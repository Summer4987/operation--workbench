from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from task_run_state import classify_failure_text, record_task_event


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "config" / "finance_bill_schema.json"
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
        "available": bool(channel_count or item_count or source_status not in {"missing", ""}),
        "channel_count": channel_count,
        "item_count": item_count,
        "estimated_cost": round(estimated_cost, 2),
        "payment_confirmation": execution_preview.get("payment_confirmation") or order_lists.get("confirmation") or {},
        "message": execution_preview.get("message") or order_lists.get("message") or "订货自动化暂未生成订单主账输入。",
    }


def build_ledger_design(schema: dict[str, Any], order_feed: dict[str, Any], sources: list[dict[str, Any]]) -> dict[str, Any]:
    source_files = {item["id"]: item.get("file_count", 0) for item in sources}
    procurement_files = source_files.get("procurement_orders", 0) + source_files.get("wechat_orders", 0)
    order_book_ready = bool(procurement_files or order_feed.get("available"))
    bank_ready = bool(source_files.get("bank", 0))
    stores_ready = bool(source_files.get("stores", 0))
    income_ready = bool(source_files.get("platform_income", 0))
    can_start_matching = order_book_ready and bank_ready and stores_ready
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
                "name": "银行流水",
                "owner": "银行账单导入",
                "purpose": "确认付款、到账和退款真实发生。",
                "ready": bank_ready,
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
                "owner": "财务中心生成",
                "purpose": "按月合并收入、成本、费用和利润。",
                "ready": can_start_matching and income_ready,
            },
        ],
        "inputs": {
            "order_book_ready": order_book_ready,
            "bank_ready": bank_ready,
            "stores_ready": stores_ready,
            "income_ready": income_ready,
            "procurement_file_count": procurement_files,
            "order_automation_available": bool(order_feed.get("available")),
        },
        "workflow": [
            "订货自动化或订单导入先生成订单主账，并写入门店、来源、供应商和金额。",
            "银行流水导入后按订单号、金额、日期、供应商关键词和门店规则自动核销。",
            "一对多、合并付款、微信群备注不清等场景进入待确认池。",
            "人工确认结果写入 manual_matches，下次按相同规则自动识别。",
            "外卖收入账单合并后生成每月门店收入、成本、费用和利润。",
        ],
        "policy": matching_policy,
        "message": (
            "订单主账、银行流水和门店基础表到位后，可开始自动付款匹配。"
            if not can_start_matching
            else "订单主账、银行流水和门店基础表已具备，可进入自动付款匹配。"
        ),
    }


def build_payload() -> dict[str, Any]:
    schema = read_json(SCHEMA_PATH, {})
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
    order_feed = load_order_automation_feed()
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
            "订单主账、银行流水和门店基础表已接收",
            "付款匹配可稳定识别门店和费用科目",
            "外卖收入账单已接收并确认报表期间",
        ],
        "report_outputs": [
            "门店利润表",
            "平台费用明细",
            "推广费和佣金异常提醒",
            "无法自动分类流水清单",
        ],
        "message": "先建立订单主账和银行核销，再生成门店利润表和费用异常提醒。"
        if not ready_for_mapping
        else "可进入付款匹配；外卖收入账单到位后生成门店利润表预览。",
    }
    return {
        "generated_at": now_text(),
        "status": status,
        "schema": {
            "path": "config/finance_bill_schema.json",
            "version": schema.get("version"),
            "account_count": len(accounts),
            "accepted_extensions": sorted(accepted_extensions),
        },
        "summary": {
            "source_count": len(sources),
            "sample_file_count": sum(item["file_count"] for item in sources),
            "missing_count": len(missing),
            "account_count": len(accounts),
            "order_source_count": len(schema.get("order_sources") or []),
            "ledger_table_count": len(ledger_design["tables"]),
        },
        "sources": sources,
        "accounts": accounts,
        "order_sources": schema.get("order_sources") or [],
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
            "银行账单样例放入 data/finance-inbox/bank",
            "门店基础表放入 data/finance-inbox/stores",
            "快驴/淘宝/拼多多订单导出放入 data/finance-inbox/procurement-orders，微信群订货记录放入 data/finance-inbox/wechat-orders",
            "美团/饿了么/抖音等平台收入账单放入 data/finance-inbox/platform-income",
        ],
        "message": ledger_design["message"],
    }


def main() -> int:
    record_task_event(TASK_ID, "running", message="财务中心状态检查开始。", step="finance-center-status")
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
        message = f"财务中心状态检查失败：{exc}"
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
