from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from task_run_state import classify_failure_text, record_task_event


ROOT = Path(__file__).resolve().parents[1]
ORDER_LISTS_PATH = ROOT / "outputs" / "inventory_order_lists" / "latest.json"
OUTPUT_DIR = ROOT / "outputs" / "inventory_order_execution_preview"
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


def build_channel_preview(order_list: dict[str, Any]) -> dict[str, Any]:
    lines = order_list.get("lines") or []
    return {
        "channel": order_list.get("channel") or "未配置供应渠道",
        "status": "等待执行确认",
        "item_count": len(lines),
        "estimated_cost": round(sum(safe_float(item.get("estimated_cost")) for item in lines), 2),
        "execution_steps": [
            "打开对应供应渠道下单入口",
            "逐项录入商品、规格和数量",
            "核对平台显示金额和本清单预估金额",
            "提交订单前停止，等待人工确认付款",
        ],
        "manual_confirm_fields": [
            "供应渠道是否正确",
            "商品和规格是否一致",
            "数量是否需要临时调整",
            "平台最终金额是否可接受",
            "是否允许继续到付款",
        ],
        "blocked_actions": [
            "自动付款",
            "跳过金额核对",
            "缺货时自动替换商品",
        ],
        "lines": lines,
    }


def not_required_payload(order_lists: dict[str, Any]) -> dict[str, Any]:
    return {
        "generated_at": now_text(),
        "status": "not_required",
        "source": "outputs/inventory_order_lists/latest.json",
        "summary": {
            "channel_count": 0,
            "item_count": 0,
            "estimated_cost": 0.0,
        },
        "payment_confirmation": {
            "required": False,
            "confirmed_by": "",
            "confirmed_at": "",
            "message": order_lists.get("message") or "当前无需订货，不需要执行预览。",
        },
        "blocked_actions": ["自动付款", "自动提交不可追溯订单"],
        "channel_previews": [],
        "message": "当前无需生成下单执行预览。",
    }


def waiting_payload(order_lists: dict[str, Any]) -> dict[str, Any]:
    summary = order_lists.get("summary") or {}
    return {
        "generated_at": now_text(),
        "status": "waiting_order_lists",
        "source": "outputs/inventory_order_lists/latest.json",
        "summary": {
            "channel_count": int(summary.get("order_list_count") or 0),
            "item_count": int(summary.get("suggestion_count") or 0),
            "estimated_cost": safe_float(summary.get("estimated_cost")),
        },
        "payment_confirmation": {
            "required": True,
            "confirmed_by": "",
            "confirmed_at": "",
            "message": "请先人工确认订货建议并生成渠道下单清单，再生成执行预览。",
        },
        "blocked_actions": ["远控安卓下单", "自动付款", "缺货自动替换"],
        "channel_previews": [],
        "message": "下单执行预览等待渠道下单清单。",
    }


def build_payload(order_lists: dict[str, Any], payment_confirmed_by: str) -> dict[str, Any]:
    status = order_lists.get("status")
    if status == "not_required":
        return not_required_payload(order_lists)
    if status != "ready":
        return waiting_payload(order_lists)

    channel_previews = [build_channel_preview(item) for item in order_lists.get("order_lists") or []]
    item_count = sum(int(item.get("item_count") or 0) for item in channel_previews)
    estimated_cost = round(sum(safe_float(item.get("estimated_cost")) for item in channel_previews), 2)
    generated_at = now_text()
    payment_confirmed = bool(payment_confirmed_by)
    return {
        "generated_at": generated_at,
        "status": "payment_confirmed" if payment_confirmed else "waiting_payment_confirmation",
        "source": "outputs/inventory_order_lists/latest.json",
        "summary": {
            "channel_count": len(channel_previews),
            "item_count": item_count,
            "estimated_cost": estimated_cost,
        },
        "payment_confirmation": {
            "required": True,
            "confirmed_by": payment_confirmed_by,
            "confirmed_at": generated_at if payment_confirmed else "",
            "message": "付款已人工确认，可进入远控安卓执行。" if payment_confirmed else "执行预览已生成；付款前必须人工确认金额和渠道。",
        },
        "blocked_actions": [
            "自动付款",
            "跳过金额核对",
            "缺货自动替换商品",
            "无确认人时远控安卓自动提交订单",
        ],
        "channel_previews": channel_previews,
        "message": (
            f"付款已确认：{len(channel_previews)} 个供应渠道可进入执行。"
            if payment_confirmed
            else f"下单执行预览已生成：{len(channel_previews)} 个供应渠道，等待付款确认。"
        ),
    }


def failed_payload(exc: Exception) -> dict[str, Any]:
    message = f"下单执行预览生成失败：{exc}"
    return {
        "generated_at": now_text(),
        "status": "failed",
        "source": "outputs/inventory_order_lists/latest.json",
        "message": message,
        "failure_type": classify_failure_text(message),
        "summary": {
            "channel_count": 0,
            "item_count": 0,
            "estimated_cost": 0.0,
        },
        "channel_previews": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="生成远控安卓下单前的执行预览和付款确认状态")
    parser.add_argument("--payment-confirmed-by", default="", help="付款确认人；为空时只生成等待付款确认的执行预览")
    parser.add_argument("--strict", action="store_true", help="失败时返回非 0")
    args = parser.parse_args()

    record_task_event(TASK_ID, "running", message="下单执行预览生成开始。", step="order-execution-preview")
    try:
        order_lists = read_json(ORDER_LISTS_PATH)
        payload = build_payload(order_lists, args.payment_confirmed_by.strip())
        write_latest(payload)
        run_status = "success" if payload["status"] in {"payment_confirmed", "not_required"} else "skipped"
        record_task_event(
            TASK_ID,
            run_status,
            message=payload["message"],
            step="order-execution-preview",
            log_path=LATEST_PATH,
            extra={
                "execution_preview_status": payload["status"],
                "channel_count": payload.get("summary", {}).get("channel_count", 0),
                "payment_confirmed_by": payload.get("payment_confirmation", {}).get("confirmed_by", ""),
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
            step="order-execution-preview",
            log_path=LATEST_PATH,
            failure_type=payload["failure_type"],
        )
        print(payload["message"], file=sys.stderr)
        return 1 if args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
