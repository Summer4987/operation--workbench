from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from task_run_state import classify_failure_text, record_task_event


ROOT = Path(__file__).resolve().parents[1]
SUGGESTIONS_PATH = ROOT / "outputs" / "inventory_order_suggestions" / "latest.json"
OUTPUT_DIR = ROOT / "outputs" / "inventory_order_lists"
LATEST_PATH = OUTPUT_DIR / "latest.json"
TASK_ID = "flow.auto_ordering"


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_latest(payload: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LATEST_PATH.chmod(0o644)


def safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def normalize_groups(suggestions: dict[str, Any]) -> list[dict[str, Any]]:
    groups = suggestions.get("groups")
    if isinstance(groups, list) and groups:
        return groups

    grouped: dict[str, dict[str, Any]] = {}
    for item in suggestions.get("items") or []:
        channel = str(item.get("warehouse") or "未配置供应渠道")
        group = grouped.setdefault(
            channel,
            {
                "channel": channel,
                "item_count": 0,
                "items": [],
            },
        )
        group["items"].append(item)
        group["item_count"] += 1
    return sorted(grouped.values(), key=lambda item: (-int(item["item_count"]), item["channel"]))


def channel_order_lines(group: dict[str, Any]) -> list[dict[str, Any]]:
    lines = []
    for index, item in enumerate(group.get("items") or [], start=1):
        quantity = safe_float(item.get("suggested_quantity"))
        lines.append(
            {
                "line_no": index,
                "sku": item.get("sku", ""),
                "name": item.get("name", ""),
                "spec": item.get("spec", ""),
                "unit": item.get("unit", ""),
                "quantity": quantity,
                "current_balance": safe_float(item.get("balance")),
                "warning_threshold": safe_float(item.get("warning_threshold")),
                "reason": item.get("reason", ""),
                "manual_note": "",
            }
        )
    return lines


def waiting_payload(suggestions: dict[str, Any]) -> dict[str, Any]:
    summary = suggestions.get("summary") or {}
    return {
        "generated_at": now_text(),
        "status": "waiting_confirmation",
        "source": "outputs/inventory_order_suggestions/latest.json",
        "summary": {
            "suggestion_count": int(summary.get("suggestion_count") or 0),
            "channel_count": int(summary.get("channel_count") or 0),
            "order_list_count": 0,
        },
        "confirmation": {
            "required": True,
            "confirmed_by": "",
            "confirmed_at": "",
            "message": "请先在业务中心人工确认品项、数量和供应渠道，再生成渠道下单清单。",
        },
        "order_lists": [],
        "message": "渠道下单清单等待人工确认。",
    }


def build_payload(suggestions: dict[str, Any], confirmed_by: str) -> dict[str, Any]:
    if suggestions.get("status") != "ready":
        raise ValueError(suggestions.get("message") or "订货建议尚未成功生成。")

    summary = suggestions.get("summary") or {}
    suggestion_count = int(summary.get("suggestion_count") or 0)
    if suggestion_count <= 0:
        return {
            "generated_at": now_text(),
            "status": "not_required",
            "source": "outputs/inventory_order_suggestions/latest.json",
            "summary": {
                "suggestion_count": 0,
                "channel_count": 0,
                "order_list_count": 0,
            },
            "confirmation": {
                "required": False,
                "confirmed_by": "",
                "confirmed_at": "",
                "message": "当前没有低库存订货建议，无需生成渠道下单清单。",
            },
            "order_lists": [],
            "message": "当前无需订货。",
        }

    if not confirmed_by:
        return waiting_payload(suggestions)

    generated_at = now_text()
    order_lists = []
    for group in normalize_groups(suggestions):
        lines = channel_order_lines(group)
        order_lists.append(
            {
                "channel": group.get("channel") or "未配置供应渠道",
                "status": "待下单",
                "item_count": len(lines),
                "next_action": "按此清单在对应供应渠道下单；付款前再次人工核对平台最终金额。",
                "lines": lines,
            }
        )

    return {
        "generated_at": generated_at,
        "status": "ready",
        "source": "outputs/inventory_order_suggestions/latest.json",
        "summary": {
            "suggestion_count": suggestion_count,
            "channel_count": len(order_lists),
            "order_list_count": len(order_lists),
        },
        "confirmation": {
            "required": True,
            "confirmed_by": confirmed_by,
            "confirmed_at": generated_at,
            "message": "订货建议已人工确认，可生成渠道下单清单；仍需付款前人工核对。",
        },
        "order_lists": order_lists,
        "message": f"渠道下单清单已生成：{len(order_lists)} 个供应渠道，{suggestion_count} 项。",
    }


def failed_payload(exc: Exception) -> dict[str, Any]:
    message = f"渠道下单清单生成失败：{exc}"
    return {
        "generated_at": now_text(),
        "status": "failed",
        "source": "outputs/inventory_order_suggestions/latest.json",
        "message": message,
        "failure_type": classify_failure_text(message),
        "summary": {
            "suggestion_count": 0,
            "channel_count": 0,
            "order_list_count": 0,
        },
        "order_lists": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="人工确认后生成渠道下单清单")
    parser.add_argument("--confirmed-by", default="", help="人工确认人；为空时只输出等待确认状态")
    parser.add_argument("--strict", action="store_true", help="失败时返回非 0")
    args = parser.parse_args()

    record_task_event(TASK_ID, "running", message="渠道下单清单生成开始。", step="channel-order-lists")
    try:
        suggestions = read_json(SUGGESTIONS_PATH)
        payload = build_payload(suggestions, args.confirmed_by.strip())
        write_latest(payload)
        run_status = "success" if payload["status"] in {"ready", "not_required"} else "skipped"
        record_task_event(
            TASK_ID,
            run_status,
            message=payload["message"],
            step="channel-order-lists",
            log_path=LATEST_PATH,
            extra={
                "order_list_status": payload["status"],
                "order_list_count": payload.get("summary", {}).get("order_list_count", 0),
                "confirmed_by": payload.get("confirmation", {}).get("confirmed_by", ""),
            },
        )
        print(payload["message"])
        return 0
    except Exception as exc:
        payload = failed_payload(exc)
        write_latest(payload)
        record_task_event(
            TASK_ID,
            "failed",
            message=payload["message"],
            step="channel-order-lists",
            log_path=LATEST_PATH,
            failure_type=payload["failure_type"],
        )
        print(payload["message"], file=sys.stderr)
        return 1 if args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
