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


def build_payload() -> dict[str, Any]:
    schema = read_json(SCHEMA_PATH, {})
    accepted_extensions = {str(item).lower() for item in schema.get("accepted_extensions", [])}
    inbox = schema.get("sample_inbox") or {}
    sources = []
    missing = []
    for source in schema.get("required_sources", []):
        source_id = source.get("id") or ""
        path_text = inbox.get(source_id) or f"data/finance-inbox/{source_id}"
        files = sample_files(path_text, accepted_extensions)
        template_path = template_path_for(source_id)
        inbox_dir = ROOT / path_text
        if not files:
            missing.append(f"{source.get('name') or source_id}样例")
        sources.append(
            {
                "id": source_id,
                "name": source.get("name") or source_id,
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
    ready_for_mapping = bool(schema and not missing and accounts)
    status = "ready_for_mapping" if ready_for_mapping else "waiting_samples"
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
        },
        "sources": sources,
        "accounts": accounts,
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
            "美团/饿了么平台账单样例放入 data/finance-inbox/platform",
            "确认营业收入、佣金、配送费、推广费、退款、补贴的财务口径",
        ],
        "message": "财务中心字段字典已建立，等待账单样例。"
        if missing
        else "财务中心样例和字段字典已就绪，可进入字段映射。",
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
