from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from task_run_state import classify_failure_text, record_task_event


ROOT = Path(__file__).resolve().parents[1]
PREVIEW_DIR = ROOT / "outputs" / "dianjin_automation"
OUTPUT_DIR = ROOT / "outputs" / "promo_bid_advice"
LATEST_PATH = OUTPUT_DIR / "latest.json"
TASK_ID = "growth.promo_bid"
STALE_AFTER = timedelta(days=3)


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:26] if "." in text else text[:19], fmt)
        except ValueError:
            continue
    return None


def write_latest(payload: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LATEST_PATH.chmod(0o644)


def load_previews() -> list[dict[str, Any]]:
    previews = []
    for path in sorted(PREVIEW_DIR.glob("execution_preview_*.json")):
        try:
            payload = read_json(path)
        except Exception:
            continue
        summary = payload.get("summary") or {}
        generated_at = parse_time(summary.get("generatedAt"))
        previews.append(
            {
                "path": str(path.relative_to(ROOT)),
                "generated_at": generated_at,
                "summary": summary,
                "rows": payload.get("rows") or [],
            }
        )
    return sorted(previews, key=lambda item: item.get("generated_at") or datetime.min, reverse=True)


def normalize_item(row: dict[str, Any], preview: dict[str, Any], now: datetime) -> dict[str, Any]:
    generated_at = preview.get("generated_at")
    age_days = (now - generated_at).days if generated_at else None
    bid_delta = float(row.get("bidDelta") or 0)
    risk = row.get("risk") or ""
    return {
        "platform": row.get("platform") or "饿了么",
        "store": row.get("store") or "",
        "period": row.get("period") or "",
        "time": row.get("time") or (preview.get("summary") or {}).get("time") or "",
        "current_bid": row.get("currentBid"),
        "target_bid": row.get("targetBid"),
        "bid_delta": bid_delta,
        "current_spend": row.get("currentSpend"),
        "expected_spend": row.get("expectedSpend"),
        "current_budget": row.get("currentBudget"),
        "budget_usage": row.get("budgetUsage") or "",
        "action": row.get("action") or "",
        "reason": row.get("decisionReason") or row.get("action") or "",
        "risk": risk,
        "can_execute": bool(row.get("canExecute")) and not risk,
        "approval_required": bool(bid_delta),
        "source": preview["path"],
        "source_generated_at": generated_at.strftime("%Y-%m-%d %H:%M:%S") if generated_at else "",
        "source_age_days": age_days,
    }


def build_payload(now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now()
    previews = load_previews()
    if not previews:
        return {
            "generated_at": now_text(),
            "status": "missing_preview",
            "summary": {
                "preview_count": 0,
                "advice_count": 0,
                "approval_required_count": 0,
                "stale_preview_count": 0,
            },
            "items": [],
            "message": "尚未找到出价执行预览，先运行饿了么点金状态读取和只读预览。",
        }

    stale_count = sum(1 for item in previews if not item.get("generated_at") or now - item["generated_at"] > STALE_AFTER)
    items = [
        normalize_item(row, preview, now)
        for preview in previews
        for row in preview.get("rows", [])
        if row.get("type") == "bid-check"
    ]
    items = sorted(items, key=lambda item: (abs(float(item.get("bid_delta") or 0)), item.get("risk") == ""), reverse=True)
    actionable = [item for item in items if item.get("approval_required")]
    risk_count = sum(1 for item in items if item.get("risk") or not item.get("can_execute"))
    latest_generated_at = previews[0].get("generated_at")
    status = "ready"
    if stale_count == len(previews):
        status = "stale"
    elif stale_count:
        status = "partial"
    return {
        "generated_at": now_text(),
        "status": status,
        "source": {
            "preview_dir": "outputs/dianjin_automation",
            "prototype": "dianjin-prototype/",
        },
        "summary": {
            "preview_count": len(previews),
            "stale_preview_count": stale_count,
            "latest_preview_at": latest_generated_at.strftime("%Y-%m-%d %H:%M:%S") if latest_generated_at else "",
            "advice_count": len(items),
            "approval_required_count": len(actionable),
            "bid_up_count": sum(1 for item in actionable if float(item.get("bid_delta") or 0) > 0),
            "bid_down_count": sum(1 for item in actionable if float(item.get("bid_delta") or 0) < 0),
            "risk_count": risk_count,
        },
        "approval": {
            "status": "required" if actionable else "not_required",
            "message": "出价调整只生成建议；任何真实提交前必须人工确认。"
            if actionable
            else "当前没有需要审批的出价调整建议。",
        },
        "items": items[:40],
        "message": f"推广出价只读建议已生成：{len(actionable)} 项需审批，{risk_count} 项有风险或不可执行。"
        if items
        else "已找到执行预览，但没有出价检查行；请先生成 10:40/10:50/11:00 出价检查预览。",
    }


def main() -> int:
    record_task_event(TASK_ID, "running", message="推广出价只读建议生成开始。", step="promo-bid-advice")
    try:
        payload = build_payload()
        write_latest(payload)
        summary = payload.get("summary") or {}
        status = "success" if payload.get("status") in {"ready", "partial", "stale"} else "skipped"
        record_task_event(
            TASK_ID,
            status,
            message=payload["message"],
            step="promo-bid-advice",
            extra={
                "advice_status": payload.get("status", ""),
                "approval_required_count": summary.get("approval_required_count", 0),
                "stale_preview_count": summary.get("stale_preview_count", 0),
                "latest_preview_at": summary.get("latest_preview_at", ""),
            },
        )
        print(payload["message"])
        return 0
    except Exception as exc:
        message = f"推广出价只读建议生成失败：{exc}"
        record_task_event(
            TASK_ID,
            "failed",
            message=message,
            step="promo-bid-advice",
            failure_type=classify_failure_text(message),
        )
        raise


if __name__ == "__main__":
    raise SystemExit(main())
