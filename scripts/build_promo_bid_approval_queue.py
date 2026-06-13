from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ADVICE_PATH = ROOT / "outputs" / "promo_bid_advice" / "latest.json"
OUTPUT_DIR = ROOT / "outputs" / "promo_bid_approval_queue"
LATEST_PATH = OUTPUT_DIR / "latest.json"


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_latest(payload: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LATEST_PATH.chmod(0o644)


def approval_id(item: dict[str, Any], index: int) -> str:
    raw = "|".join(
        str(item.get(key) or "")
        for key in ("platform", "store", "period", "time", "source", "target_bid")
    )
    slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", raw).strip("-").lower()
    return f"bid-{index + 1:03d}-{slug[:64] or 'unknown'}"


def queue_item(item: dict[str, Any], index: int) -> dict[str, Any]:
    risk = str(item.get("risk") or "").strip()
    status = "manual_review" if risk or not item.get("can_execute") else "waiting_approval"
    return {
        "approval_id": approval_id(item, index),
        "status": status,
        "platform": item.get("platform") or "饿了么",
        "store": item.get("store") or "",
        "period": item.get("period") or "",
        "time": item.get("time") or "",
        "action": item.get("action") or "出价建议",
        "reason": item.get("reason") or "",
        "current_bid": item.get("current_bid"),
        "target_bid": item.get("target_bid"),
        "bid_delta": item.get("bid_delta"),
        "current_spend": item.get("current_spend"),
        "expected_spend": item.get("expected_spend"),
        "current_budget": item.get("current_budget"),
        "budget_usage": item.get("budget_usage") or "",
        "risk": risk,
        "source": item.get("source") or "",
        "source_generated_at": item.get("source_generated_at") or "",
        "decision_options": ["approve", "skip", "manual_review"],
        "operator_checklist": [
            "核对门店、时段和当前出价。",
            "核对当前消耗、预期消耗和预算余额。",
            "确认平台页面、营业状态和预算状态正常。",
            "人工确认后才允许进入真实提交。",
        ],
        "human_action": f"人工确认 {item.get('store') or '未命名门店'} {item.get('period') or item.get('time') or ''} {item.get('action') or '出价建议'}；确认前不自动提交到平台。",
    }


def build_missing(now: str, message: str) -> dict[str, Any]:
    return {
        "generated_at": now,
        "status": "missing_advice",
        "source": "outputs/promo_bid_advice/latest.json",
        "summary": {
            "queue_count": 0,
            "approval_required_count": 0,
            "bid_up_count": 0,
            "bid_down_count": 0,
            "risk_count": 0,
            "stale_preview_count": 0,
        },
        "approval_gate": {
            "status": "manual_required",
            "message": "所有出价调整必须人工审批；本文件不触发提交。",
            "forbidden_actions": ["自动提交出价", "绕过审批", "自动处理风险项"],
        },
        "items": [],
        "message": message,
        "human_action": "先生成推广出价只读建议，再进入审批队列。",
    }


def build_payload() -> dict[str, Any]:
    generated_at = now_text()
    advice = read_json(ADVICE_PATH)
    advice_summary = advice.get("summary") or {}
    if not advice:
        return build_missing(generated_at, "推广出价建议尚未生成，无法生成审批队列。")
    if advice.get("status") == "missing_preview":
        return build_missing(generated_at, advice.get("message") or "尚未找到出价执行预览，无法生成审批队列。")

    source_items = [
        item
        for item in advice.get("items") or []
        if item.get("approval_required") and float(item.get("bid_delta") or 0) != 0
    ]
    items = [queue_item(item, index) for index, item in enumerate(source_items)]
    risk_count = sum(1 for item in items if item.get("status") == "manual_review")
    queue_count = len(items)
    status = "waiting_approval" if queue_count else "no_action"
    summary = {
        "queue_count": queue_count,
        "approval_required_count": queue_count,
        "bid_up_count": sum(1 for item in items if float(item.get("bid_delta") or 0) > 0),
        "bid_down_count": sum(1 for item in items if float(item.get("bid_delta") or 0) < 0),
        "risk_count": risk_count,
        "stale_preview_count": int(advice_summary.get("stale_preview_count") or 0),
        "latest_preview_at": advice_summary.get("latest_preview_at", ""),
        "advice_status": advice.get("status", ""),
        "advice_generated_at": advice.get("generated_at", ""),
    }
    message = (
        f"推广出价审批队列已生成：{queue_count} 项待确认，{risk_count} 项需人工复核。"
        if queue_count
        else "当前没有需要审批的推广出价调整。"
    )
    return {
        "generated_at": generated_at,
        "status": status,
        "source": "outputs/promo_bid_advice/latest.json",
        "summary": summary,
        "approval_gate": {
            "status": "manual_required",
            "message": "所有出价调整必须人工审批；本文件不触发提交。",
            "forbidden_actions": ["自动提交出价", "绕过审批", "自动处理风险项"],
        },
        "items": items,
        "message": message,
        "human_action": f"逐项确认 {queue_count} 条出价建议；风险项必须先人工复核。"
        if queue_count
        else "无需处理出价审批。",
    }


def main() -> int:
    payload = build_payload()
    write_latest(payload)
    print(payload["message"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
