from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
QUEUE_PATH = ROOT / "outputs" / "promo_bid_approval_queue" / "latest.json"
SIGNAL_STATUS_PATH = ROOT / "outputs" / "promo_bid_signal_status" / "latest.json"
OUTPUT_DIR = ROOT / "outputs" / "promo_bid_execution_plan"
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


def build_step(item: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "step_id": f"bid-exec-{index + 1:03d}",
        "approval_id": item.get("approval_id", ""),
        "platform": item.get("platform") or "饿了么",
        "store": item.get("store") or "",
        "period": item.get("period") or "",
        "time": item.get("time") or "",
        "action": item.get("action") or "出价调整",
        "current_bid": item.get("current_bid"),
        "target_bid": item.get("target_bid"),
        "bid_delta": item.get("bid_delta"),
        "source": item.get("source") or "",
        "decision_recorded_at": item.get("decision_recorded_at") or "",
        "decision_operator": item.get("decision_operator") or "",
        "preflight_checklist": [
            "重新读取平台当前出价和预算消耗。",
            "确认门店名称、时段和目标出价与审批记录一致。",
            "确认页面未提示出价助手、风险设置或预算异常。",
            "真实保存前保留截图或执行日志。",
        ],
        "execution_mode": "dry_run_plan_only",
        "forbidden_actions": ["自动提交出价", "绕过审批", "自动处理风险项", "自动关闭或调整出价助手"],
    }


def build_payload() -> dict[str, Any]:
    generated_at = now_text()
    queue = read_json(QUEUE_PATH)
    signal_status = read_json(SIGNAL_STATUS_PATH)
    if not queue:
        return {
            "generated_at": generated_at,
            "status": "missing_queue",
            "source": "outputs/promo_bid_approval_queue/latest.json",
            "summary": {"approved_count": 0, "plan_count": 0, "blocked_count": 0},
            "steps": [],
            "message": "尚未生成推广出价审批队列，无法生成执行计划。",
            "human_action": "先生成出价建议和审批队列；确认前不提交平台。",
        }

    approved = [item for item in queue.get("items") or [] if item.get("status") == "approved"]
    steps = [build_step(item, index) for index, item in enumerate(approved)]
    queue_summary = queue.get("summary") or {}
    signal_summary = signal_status.get("summary") or {}
    blocked_count = int(queue_summary.get("queue_count") or 0)
    stale_preview_count = int(queue_summary.get("stale_preview_count") or 0)
    signal_missing_count = int(signal_summary.get("missing_count") or 0)
    signal_partial_count = int(signal_summary.get("partial_count") or 0)
    real_execution_blockers = []
    if blocked_count:
        real_execution_blockers.append(f"仍有 {blocked_count} 项未审批")
    if stale_preview_count:
        real_execution_blockers.append(f"有 {stale_preview_count} 个旧预览")
    if signal_missing_count:
        real_execution_blockers.append(f"有 {signal_missing_count} 项信号缺口")
    if signal_partial_count:
        real_execution_blockers.append(f"有 {signal_partial_count} 项信号半接入")
    status = "ready" if steps else "no_approved"
    message = (
        f"推广出价只读执行计划已生成：{len(steps)} 项已审批，仍有 {blocked_count} 项未审批。"
        if steps
        else f"暂无已审批出价项，仍有 {blocked_count} 项等待审批；不生成真实执行。"
    )
    return {
        "generated_at": generated_at,
        "status": status,
        "source": "outputs/promo_bid_approval_queue/latest.json",
        "safety_gate": {
            "mode": "dry_run_plan_only",
            "requires_manual_execution": True,
            "message": "本计划只描述已审批出价步骤，不自动打开平台、不点击保存、不提交真实出价。",
            "forbidden_actions": ["自动提交出价", "绕过审批", "自动处理风险项", "自动关闭或调整出价助手"],
        },
        "real_execution_gate": {
            "status": "blocked" if real_execution_blockers else "ready_for_manual_preflight",
            "message": "真实执行仍被阻断：" + "；".join(real_execution_blockers)
            if real_execution_blockers
            else "已审批项可进入人工预检；仍需 Mac mini 重新读取平台当前状态并人工确认保存。",
            "blockers": real_execution_blockers,
            "requires": [
                "全部建议完成审批或明确跳过",
                "无旧预览",
                "曝光、进店、下单转化等信号接入完整",
                "Mac mini 生产环境重新读取平台当前状态",
                "真实保存前人工确认",
            ],
        },
        "signal_gate": {
            "status": signal_status.get("status") or "missing",
            "message": signal_status.get("message") or "尚未生成推广出价信号状态。",
            "summary": signal_summary,
            "source": "outputs/promo_bid_signal_status/latest.json",
        },
        "summary": {
            "approved_count": len(approved),
            "plan_count": len(steps),
            "blocked_count": blocked_count,
            "stale_preview_count": stale_preview_count,
            "signal_missing_count": signal_missing_count,
            "signal_partial_count": signal_partial_count,
            "real_execution_blocked": bool(real_execution_blockers),
            "decision_source": queue.get("decision_source") or "data/promo_bid_decisions.json",
            "queue_generated_at": queue.get("generated_at", ""),
        },
        "steps": steps,
        "message": message,
        "human_action": "先完成审批记录；真实执行前在 Mac mini 重新读取平台状态并逐项确认。",
    }


def main() -> int:
    payload = build_payload()
    write_latest(payload)
    print(payload["message"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
