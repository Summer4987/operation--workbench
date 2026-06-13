from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ADVICE_PATH = ROOT / "outputs" / "promo_bid_advice" / "latest.json"
OUTPUT_DIR = ROOT / "outputs" / "promo_bid_approval_queue"
LATEST_PATH = OUTPUT_DIR / "latest.json"
DECISIONS_PATH = Path(os.environ.get("PROMO_BID_DECISIONS_PATH", ROOT / "data" / "promo_bid_decisions.json"))


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


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def approval_id(item: dict[str, Any], index: int) -> str:
    raw = "|".join(
        str(item.get(key) or "")
        for key in ("platform", "store", "period", "time", "source", "target_bid")
    )
    slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", raw).strip("-").lower()
    return f"bid-{index + 1:03d}-{slug[:64] or 'unknown'}"


def load_decisions() -> dict[str, dict[str, Any]]:
    payload = read_json(DECISIONS_PATH)
    latest: dict[str, dict[str, Any]] = {}
    for record in payload.get("records") or []:
        approval_id = str(record.get("approval_id") or "").strip()
        decision = str(record.get("decision") or "").strip()
        if not approval_id or decision not in {"approve", "skip", "manual_review"}:
            continue
        latest[approval_id] = record
    return latest


def queue_item(item: dict[str, Any], index: int, decisions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    risk = str(item.get("risk") or "").strip()
    item_id = approval_id(item, index)
    decision = decisions.get(item_id) or {}
    decision_value = str(decision.get("decision") or "").strip()
    if decision_value == "approve":
        status = "approved"
    elif decision_value == "skip":
        status = "skipped"
    elif decision_value == "manual_review":
        status = "manual_review_recorded"
    else:
        status = "manual_review" if risk or not item.get("can_execute") else "waiting_approval"
    return {
        "approval_id": item_id,
        "status": status,
        "decision": decision_value,
        "decision_recorded_at": decision.get("recorded_at", ""),
        "decision_operator": decision.get("operator", ""),
        "decision_note": decision.get("note", ""),
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
        "decision_command": (
            f"python3 scripts/record_promo_bid_decision.py --approval-id {item_id} "
            "--decision approve --operator '<审批人>' --note '<备注>'"
        ),
        "human_action": f"人工确认 {item.get('store') or '未命名门店'} {item.get('period') or item.get('time') or ''} {item.get('action') or '出价建议'}；确认前不自动提交到平台。",
    }


def compact_number(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return str(value)


def approval_line(item: dict[str, Any]) -> str:
    store = item.get("store") or "未命名门店"
    time_text = " ".join(part for part in (item.get("period"), item.get("time")) if part)
    bid_text = f"{compact_number(item.get('current_bid'))}->{compact_number(item.get('target_bid'))}"
    spend_text = ""
    if item.get("current_spend") not in (None, "") and item.get("expected_spend") not in (None, ""):
        spend_text = f"消耗 {compact_number(item.get('current_spend'))}/{compact_number(item.get('expected_spend'))}"
    budget_text = item.get("budget_usage") or ""
    reason = item.get("risk") or item.get("reason") or item.get("human_action") or ""
    details = "，".join(part for part in (time_text, item.get("action"), f"出价 {bid_text}", spend_text, budget_text, reason) if part)
    return f"{store}：{details}"


def build_approval_digest(items: list[dict[str, Any]], summary: dict[str, Any]) -> dict[str, Any]:
    top_items = [approval_line(item) for item in items[:5]]
    stale_count = int(summary.get("stale_preview_count") or 0)
    warnings = []
    if stale_count:
        warnings.append(f"有 {stale_count} 个旧预览，审批前需重新确认平台当前出价和消耗。")
    if int(summary.get("risk_count") or 0):
        warnings.append("风险项必须先人工复核，不进入自动提交。")
    if not warnings:
        warnings.append("确认前不自动提交；审批时逐项核对门店、时段、当前出价、目标出价和预算消耗。")
    return {
        "top_items": top_items,
        "warnings": warnings,
        "checklist": [
            "逐项核对门店、时段、当前出价和目标出价。",
            "核对当前消耗、预期消耗、预算占用和平台营业状态。",
            "旧预览或风险项先重新读取平台状态，不直接批准。",
            "确认前不自动提交到平台。",
        ],
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
            "approved_count": 0,
            "skipped_count": 0,
            "manual_review_recorded_count": 0,
        },
        "decision_source": display_path(DECISIONS_PATH),
        "approval_gate": {
            "status": "manual_required",
            "message": "所有出价调整必须人工审批；本文件不触发提交。",
            "forbidden_actions": ["自动提交出价", "绕过审批", "自动处理风险项"],
        },
        "approval_digest": {
            "top_items": [],
            "warnings": [message],
            "checklist": ["先生成推广出价只读建议。", "确认前不自动提交到平台。"],
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
    decisions = load_decisions()
    items = [queue_item(item, index, decisions) for index, item in enumerate(source_items)]
    pending_items = [item for item in items if item.get("status") in {"waiting_approval", "manual_review"}]
    risk_count = sum(1 for item in pending_items if item.get("status") == "manual_review")
    approved_count = sum(1 for item in items if item.get("status") == "approved")
    skipped_count = sum(1 for item in items if item.get("status") == "skipped")
    manual_review_recorded_count = sum(1 for item in items if item.get("status") == "manual_review_recorded")
    queue_count = len(pending_items)
    status = "waiting_approval" if queue_count else "no_action"
    summary = {
        "queue_count": queue_count,
        "approval_required_count": queue_count,
        "total_suggestion_count": len(items),
        "bid_up_count": sum(1 for item in pending_items if float(item.get("bid_delta") or 0) > 0),
        "bid_down_count": sum(1 for item in pending_items if float(item.get("bid_delta") or 0) < 0),
        "risk_count": risk_count,
        "approved_count": approved_count,
        "skipped_count": skipped_count,
        "manual_review_recorded_count": manual_review_recorded_count,
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
        "decision_source": display_path(DECISIONS_PATH),
        "summary": summary,
        "approval_gate": {
            "status": "manual_required",
            "message": "所有出价调整必须人工审批；本文件不触发提交。",
            "forbidden_actions": ["自动提交出价", "绕过审批", "自动处理风险项"],
            "record_command_template": "python3 scripts/record_promo_bid_decision.py --approval-id <approval_id> --decision approve --operator '<审批人>' --note '<备注>'",
        },
        "approval_digest": build_approval_digest(pending_items, summary),
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
