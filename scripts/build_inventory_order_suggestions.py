from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from task_run_state import classify_failure_text, record_task_event


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "inventory_order_suggestions"
LATEST_PATH = OUTPUT_DIR / "latest.json"
DEFAULT_SERVER = "http://139.155.148.169"
TASK_ID = "flow.auto_ordering"


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def write_latest(payload: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LATEST_PATH.chmod(0o644)


def fetch_inventory_summary(server: str, timeout: int) -> dict[str, Any]:
    with urlopen(f"{server.rstrip('/')}/api/summary", timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def build_suggestions(items: list[dict[str, Any]], buffer_units: float) -> list[dict[str, Any]]:
    suggestions = []
    for item in items:
        balance = safe_float(item.get("balance"))
        threshold = safe_float(item.get("warning_threshold"))
        if balance > threshold:
            continue
        target_stock = max(threshold + buffer_units, threshold)
        suggested_quantity = max(1, math.ceil(target_stock - balance))
        unit_cost = safe_float(item.get("unit_cost"))
        suggestions.append(
            {
                "sku": item.get("sku", ""),
                "name": item.get("name", ""),
                "spec": item.get("spec", ""),
                "unit": item.get("unit", ""),
                "warehouse": item.get("warehouse", ""),
                "balance": balance,
                "warning_threshold": threshold,
                "target_stock": target_stock,
                "suggested_quantity": suggested_quantity,
                "estimated_cost": round(suggested_quantity * unit_cost, 2),
                "reason": f"当前库存 {balance:g}，预警线 {threshold:g}，建议补到 {target_stock:g}。",
            }
        )
    return sorted(suggestions, key=lambda item: (item["balance"] - item["warning_threshold"], item["sku"]))


def group_by_channel(suggestions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for item in suggestions:
        channel = str(item.get("warehouse") or "未配置供应渠道")
        group = grouped.setdefault(
            channel,
            {
                "channel": channel,
                "status": "待人工确认",
                "item_count": 0,
                "estimated_cost": 0.0,
                "items": [],
                "next_action": "人工确认品项、数量和供应渠道后，再生成下单清单。",
            },
        )
        group["items"].append(item)
        group["item_count"] += 1
        group["estimated_cost"] = round(float(group["estimated_cost"]) + float(item.get("estimated_cost") or 0), 2)
    return sorted(grouped.values(), key=lambda item: (-int(item["item_count"]), item["channel"]))


def confirmation_checklist(groups: list[dict[str, Any]]) -> list[str]:
    if not groups:
        return []
    return [
        "逐个供应渠道核对品项、规格、数量和预估金额。",
        "确认低库存原因不是盘点延迟或单位录入错误。",
        "确认后运行 `python3 scripts/build_inventory_order_lists.py --confirmed-by \"确认人\"` 生成渠道下单清单。",
    ]


def build_payload(server: str, timeout: int, buffer_units: float) -> dict[str, Any]:
    summary = fetch_inventory_summary(server, timeout)
    items = summary.get("items")
    if not isinstance(items, list):
        raise ValueError("库存 /api/summary 缺少 items 列表。")
    suggestions = build_suggestions(items, buffer_units)
    groups = group_by_channel(suggestions)
    estimated_cost = round(sum(float(item.get("estimated_cost") or 0) for item in suggestions), 2)
    return {
        "generated_at": now_text(),
        "status": "ready",
        "source": "cloud",
        "server": server.rstrip("/"),
        "policy": {
            "method": "低于或等于预警线时补货",
            "buffer_units": buffer_units,
            "requires_human_confirm": True,
            "group_by": "warehouse",
        },
        "confirmation": {
            "status": "pending" if suggestions else "not_required",
            "required_before": ["生成渠道下单清单", "远控安卓下单", "付款"],
            "checklist": confirmation_checklist(groups),
            "confirm_command": 'python3 scripts/build_inventory_order_lists.py --confirmed-by "确认人"',
            "message": "订货建议只用于人工确认；确认前不会自动下单或付款。",
        },
        "summary": {
            "suggestion_count": len(suggestions),
            "channel_count": len(groups),
            "estimated_cost": estimated_cost,
        },
        "groups": groups,
        "items": suggestions,
        "message": f"订货建议已生成：{len(suggestions)} 项，预估金额 {estimated_cost:.2f} 元。",
    }


def failed_payload(server: str, exc: Exception) -> dict[str, Any]:
    message = f"订货建议生成失败：{exc}"
    return {
        "generated_at": now_text(),
        "status": "failed",
        "source": "cloud",
        "server": server.rstrip("/"),
        "message": message,
        "failure_type": classify_failure_text(message),
        "items": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="根据库存预警生成只读订货建议")
    parser.add_argument("--server", default=DEFAULT_SERVER, help="库存云端服务地址")
    parser.add_argument("--timeout", type=int, default=8, help="请求超时秒数")
    parser.add_argument("--buffer-units", type=float, default=2, help="补到预警线以上的缓冲件数")
    parser.add_argument("--strict", action="store_true", help="失败时返回非 0")
    args = parser.parse_args()

    record_task_event(TASK_ID, "running", message="订货建议生成开始。", step="inventory-suggestions")
    try:
        payload = build_payload(args.server, args.timeout, args.buffer_units)
        write_latest(payload)
        record_task_event(
            TASK_ID,
            "success",
            message=payload["message"],
            step="inventory-suggestions",
            log_path=LATEST_PATH,
            extra={
                "suggestion_count": payload["summary"]["suggestion_count"],
                "estimated_cost": payload["summary"]["estimated_cost"],
                "requires_human_confirm": True,
            },
        )
        print(payload["message"])
        return 0
    except Exception as exc:
        payload = failed_payload(args.server, exc)
        write_latest(payload)
        record_task_event(
            TASK_ID,
            "failed",
            message=payload["message"],
            step="inventory-suggestions",
            log_path=LATEST_PATH,
            failure_type=payload["failure_type"],
        )
        print(payload["message"], file=sys.stderr)
        return 1 if args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
