from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from task_run_state import classify_failure_text, record_task_event


ROOT = Path(__file__).resolve().parents[1]
EXECUTION_PREVIEW_PATH = ROOT / "outputs" / "inventory_order_execution_preview" / "latest.json"
OUTPUT_DIR = ROOT / "outputs" / "inventory_android_execution_plan"
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


def app_hint(channel: str) -> str:
    text = channel.lower()
    if "美团" in channel or "meituan" in text:
        return "美团供应/采购相关入口"
    if "饿了么" in channel or "ele" in text:
        return "饿了么供应/采购相关入口"
    if "京东" in channel or "jd" in text:
        return "京东/京东到家采购入口"
    return "对应供应渠道 App 或小程序"


def line_instruction(line: dict[str, Any]) -> str:
    name = line.get("name") or line.get("sku") or "未命名商品"
    spec = line.get("spec") or "-"
    quantity = safe_float(line.get("quantity"))
    unit = line.get("unit") or ""
    return f"搜索并核对 {name}（{spec}），录入数量 {quantity:g}{unit}。"


def build_channel_job(preview: dict[str, Any]) -> dict[str, Any]:
    channel = preview.get("channel") or "未配置供应渠道"
    lines = preview.get("lines") or []
    return {
        "channel": channel,
        "target_app": app_hint(channel),
        "status": "只读计划",
        "item_count": len(lines),
        "preflight_checks": [
            "远控安卓手机在线且屏幕已解锁",
            "目标 App 已登录正确账号",
            "收货门店和地址已人工确认",
            "付款确认人在线",
        ],
        "android_steps": [
            "打开目标供应渠道 App 或小程序",
            "进入搜索或采购入口",
            *[line_instruction(line) for line in lines],
            "进入结算页后停止，不自动提交订单",
            "把平台最终金额推送给付款确认人",
        ],
        "stop_before": [
            "提交订单",
            "付款",
            "缺货商品替换",
            "切换收货地址",
        ],
        "manual_handoff": "平台最终金额、缺货项和替代品必须人工确认后再继续。",
    }


def not_ready_payload(preview: dict[str, Any]) -> dict[str, Any]:
    status = preview.get("status") or "missing"
    if status == "not_required":
        message = preview.get("message") or "当前无需订货，不需要安卓执行计划。"
        output_status = "not_required"
    elif status == "payment_confirmed":
        message = "付款确认已完成，但执行预览缺少渠道明细，无法生成安卓执行计划。"
        output_status = "failed"
    else:
        message = "远控安卓执行计划等待付款确认；未确认前不会生成可执行步骤。"
        output_status = "waiting_payment_confirmation"
    return {
        "generated_at": now_text(),
        "status": output_status,
        "source": "outputs/inventory_order_execution_preview/latest.json",
        "summary": {
            "channel_count": 0,
            "item_count": 0,
        },
        "safety": {
            "dry_run": True,
            "requires_human_operator": True,
            "forbidden_actions": ["自动提交订单", "自动付款", "自动替换缺货商品", "自动切换收货地址"],
        },
        "android_jobs": [],
        "message": message,
    }


def build_payload(preview: dict[str, Any], operator: str) -> dict[str, Any]:
    if preview.get("status") != "payment_confirmed":
        return not_ready_payload(preview)

    channel_previews = preview.get("channel_previews") or []
    if not channel_previews:
        return not_ready_payload(preview)

    jobs = [build_channel_job(item) for item in channel_previews]
    return {
        "generated_at": now_text(),
        "status": "ready",
        "source": "outputs/inventory_order_execution_preview/latest.json",
        "summary": {
            "channel_count": len(jobs),
            "item_count": sum(int(item.get("item_count") or 0) for item in jobs),
        },
        "operator": {
            "name": operator,
            "required": True,
            "message": "这是远控安卓执行适配计划，只读预览；真实执行前必须由人工操作员接管。",
        },
        "safety": {
            "dry_run": True,
            "requires_human_operator": True,
            "forbidden_actions": ["自动提交订单", "自动付款", "自动替换缺货商品", "自动切换收货地址"],
        },
        "android_jobs": jobs,
        "message": f"远控安卓执行适配计划已生成：{len(jobs)} 个供应渠道，只读预览。",
    }


def failed_payload(exc: Exception) -> dict[str, Any]:
    message = f"远控安卓执行适配计划生成失败：{exc}"
    return {
        "generated_at": now_text(),
        "status": "failed",
        "source": "outputs/inventory_order_execution_preview/latest.json",
        "message": message,
        "failure_type": classify_failure_text(message),
        "summary": {
            "channel_count": 0,
            "item_count": 0,
        },
        "android_jobs": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="生成远控安卓执行适配层只读计划")
    parser.add_argument("--operator", default="", help="人工操作员名称；只用于执行计划标注")
    parser.add_argument("--strict", action="store_true", help="失败时返回非 0")
    args = parser.parse_args()

    record_task_event(TASK_ID, "running", message="远控安卓执行适配计划生成开始。", step="android-execution-plan")
    try:
        preview = read_json(EXECUTION_PREVIEW_PATH)
        payload = build_payload(preview, args.operator.strip())
        write_latest(payload)
        run_status = "success" if payload["status"] in {"ready", "not_required"} else "skipped"
        record_task_event(
            TASK_ID,
            run_status,
            message=payload["message"],
            step="android-execution-plan",
            log_path=LATEST_PATH,
            extra={
                "android_plan_status": payload["status"],
                "channel_count": payload.get("summary", {}).get("channel_count", 0),
                "operator": payload.get("operator", {}).get("name", ""),
                "dry_run": True,
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
            step="android-execution-plan",
            log_path=LATEST_PATH,
            failure_type=payload["failure_type"],
        )
        print(payload["message"], file=sys.stderr)
        return 1 if args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
