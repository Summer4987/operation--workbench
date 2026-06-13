from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from task_run_state import classify_failure_text, record_task_event


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "tool_warehouse_status"
LATEST_PATH = OUTPUT_DIR / "latest.json"
SALES_PRINT_CHECK_PATH = ROOT / "outputs" / "sales_receipt_print_check" / "latest.json"
SALES_TASK_ID = "tools.sales_receipt"

SALES_RECEIPT_REQUIRED = [
    ("页面", ROOT / "sales-receipt-generator" / "index.html"),
    ("脚本", ROOT / "sales-receipt-generator" / "app.js"),
    ("样式", ROOT / "sales-receipt-generator" / "styles.css"),
    ("默认公章", ROOT / "sales-receipt-generator" / "assets" / "company-seal.png"),
]

FRANCHISE_REQUIRED_FIELDS = [
    "加盟商/公司名称",
    "统一社会信用代码或身份证号",
    "联系人和联系方式",
    "加盟门店名称和地址",
    "加盟期限",
    "加盟费、保证金和付款方式",
    "品牌授权范围",
    "培训和开店支持",
    "违约、解约和续约条款",
    "合同模板版本",
]

FRANCHISE_TEMPLATE_DIR = ROOT / "franchise-contract-generator"
FRANCHISE_ACCEPTED_EXTENSIONS = [".docx", ".pdf", ".pages", ".txt", ".md"]


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def write_latest(payload: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LATEST_PATH.chmod(0o644)


def file_status(label: str, path: Path) -> dict[str, Any]:
    exists = path.exists()
    return {
        "label": label,
        "path": str(path.relative_to(ROOT)),
        "exists": exists,
        "size": path.stat().st_size if exists and path.is_file() else 0,
    }


def read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def sales_receipt_status() -> dict[str, Any]:
    checks = [file_status(label, path) for label, path in SALES_RECEIPT_REQUIRED]
    missing = [item for item in checks if not item["exists"]]
    print_check = read_json(SALES_PRINT_CHECK_PATH, {})
    if missing:
        status = "missing_assets"
    elif print_check.get("status") == "failed":
        status = "print_check_failed"
    elif print_check.get("status") == "ok":
        status = "ready"
    else:
        status = "needs_print_check"
    return {
        "id": "sales_receipt",
        "name": "销售单生成器",
        "status": status,
        "status_text": "已接入" if status == "ready" else "待校验" if status == "needs_print_check" else "版式异常" if status == "print_check_failed" else "缺资源",
        "entrypoint": "sales-receipt-generator/index.html",
        "checks": checks,
        "missing": missing,
        "print_check": print_check,
        "capabilities": [
            "销售日期和单据编号",
            "收货单位",
            "销售项目、数量、单位和可选金额",
            "默认公章或临时上传公章",
            "一页打印或保存 PDF",
        ],
        "message": "销售单生成器资源完整，打印版式校验通过，可从工具仓库打开。"
        if status == "ready"
        else "销售单生成器等待打印版式自动截图校验。"
        if status == "needs_print_check"
        else print_check.get("message", "销售单打印版式校验失败。")
        if status == "print_check_failed"
        else f"销售单生成器缺少 {len(missing)} 个资源。",
    }


def franchise_contract_status() -> dict[str, Any]:
    template_files = sorted(FRANCHISE_TEMPLATE_DIR.glob("*")) if FRANCHISE_TEMPLATE_DIR.exists() else []
    template_files = [
        path
        for path in template_files
        if path.is_file()
        and not path.name.startswith(".")
        and path.suffix.lower() in FRANCHISE_ACCEPTED_EXTENSIONS
    ]
    has_template = bool(template_files)
    intake_message = (
        "把现用加盟合同模板放入 franchise-contract-generator/，"
        f"支持 {'、'.join(FRANCHISE_ACCEPTED_EXTENSIONS)}，"
        f"至少确认：{'、'.join(FRANCHISE_REQUIRED_FIELDS[:6])}等字段。"
    )
    return {
        "id": "franchise_contract",
        "name": "加盟合同生成器",
        "status": "ready_for_mapping" if has_template else "waiting_template",
        "status_text": "待字段映射" if has_template else "待模板",
        "entrypoint": "franchise-contract-generator/",
        "template_files": [str(path.relative_to(ROOT)) for path in template_files if path.is_file()],
        "accepted_extensions": FRANCHISE_ACCEPTED_EXTENSIONS,
        "required_fields": FRANCHISE_REQUIRED_FIELDS,
        "intake_checklist": [
            {
                "label": "模板目录",
                "path": "franchise-contract-generator/",
                "accepted_extensions": FRANCHISE_ACCEPTED_EXTENSIONS,
                "required_fields": FRANCHISE_REQUIRED_FIELDS,
                "message": intake_message,
            }
        ],
        "missing": [] if has_template else ["合同模板文件", "加盟条款字段确认"],
        "message": "已找到合同模板，下一步做字段映射和生成预览。"
        if has_template
        else "加盟合同生成器等待合同模板和关键字段确认。",
    }


def build_payload() -> dict[str, Any]:
    sales = sales_receipt_status()
    contract = franchise_contract_status()
    tools = [sales, contract]
    return {
        "generated_at": now_text(),
        "status": "ready" if sales["status"] == "ready" else "partial",
        "summary": {
            "tool_count": len(tools),
            "ready_count": sum(1 for item in tools if item["status"] == "ready"),
            "waiting_count": sum(1 for item in tools if item["status"] != "ready"),
        },
        "tools": tools,
        "sales_receipt": sales,
        "franchise_contract": contract,
        "message": f"工具仓库状态已生成：{sum(1 for item in tools if item['status'] == 'ready')} 个可用，{sum(1 for item in tools if item['status'] != 'ready')} 个待补齐。",
    }


def main() -> int:
    record_task_event(SALES_TASK_ID, "running", message="工具仓库状态检查开始。", step="tool-warehouse-status")
    try:
        payload = build_payload()
        write_latest(payload)
        sales = payload["sales_receipt"]
        status = "success" if sales["status"] == "ready" else "failed"
        record_task_event(
            SALES_TASK_ID,
            status,
            message=sales["message"],
            step="tool-warehouse-status",
            failure_type="" if status == "success" else classify_failure_text(sales["message"]),
            extra={
                "sales_receipt_status": sales["status"],
                "tool_ready_count": payload["summary"]["ready_count"],
                "tool_waiting_count": payload["summary"]["waiting_count"],
            },
        )
        print(payload["message"])
        return 0 if status == "success" else 1
    except Exception as exc:
        message = f"工具仓库状态检查失败：{exc}"
        record_task_event(
            SALES_TASK_ID,
            "failed",
            message=message,
            step="tool-warehouse-status",
            failure_type=classify_failure_text(message),
        )
        raise


if __name__ == "__main__":
    raise SystemExit(main())
