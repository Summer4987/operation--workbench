from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from task_run_state import classify_failure_text


ROOT = Path(__file__).resolve().parents[1]
REALTIME_DIR = ROOT / "outputs" / "realtime_order_income"
LATEST_PATH = REALTIME_DIR / "latest.json"
FAILED_PATH = REALTIME_DIR / "last_failed.json"
TASK_RUNS_PATH = ROOT / "outputs" / "task_runs" / "latest.json"
OUTPUT_DIR = ROOT / "outputs" / "realtime_order_income_status"
OUTPUT_PATH = OUTPUT_DIR / "latest.json"
TASK_ID = "ops.realtime_order_income"
ACTIVE_STALE_AFTER = timedelta(minutes=95)


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


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


def active_realtime_window(now: datetime) -> bool:
    return 10 <= now.hour < 20


def write_latest(payload: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUTPUT_PATH.chmod(0o644)


def classify_payload_failure(payload: dict[str, Any], task_run: dict[str, Any]) -> str:
    if task_run.get("failure_type"):
        return str(task_run["failure_type"])
    errors = payload.get("errors") or []
    if errors:
        return classify_failure_text("；".join(str(item) for item in errors))
    missing = payload.get("missing") or []
    if missing:
        return "missing_platform_store"
    if payload.get("status") in {"failed", "error"}:
        return classify_failure_text(payload.get("message") or "")
    return ""


def build_payload(now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now()
    latest = read_json(LATEST_PATH, {})
    failed = read_json(FAILED_PATH, {})
    run_state = read_json(TASK_RUNS_PATH, {"tasks": {}})
    task_run = (run_state.get("tasks") or {}).get(TASK_ID) or {}
    latest_time = parse_time(latest.get("generated_at"))
    failed_time = parse_time(failed.get("generated_at"))
    latest_summary = latest.get("summary") or {}
    failed_summary = failed.get("summary") or {}
    latest_success = latest.get("status") in {"ok", "ready", "success"} and int(latest_summary.get("missing_count") or 0) == 0
    failure_type = classify_payload_failure(failed, task_run)
    stale = bool(latest_time and active_realtime_window(now) and now - latest_time > ACTIVE_STALE_AFTER)
    if not latest:
        status = "missing_latest"
        message = "尚未找到实时单量收入最新成功采集。"
    elif stale:
        status = "stale"
        message = f"实时采集最近成功时间偏旧：{latest.get('generated_at')}。"
    elif failed_time and latest_time and failed_time > latest_time:
        status = "failed_after_success"
        message = "最近一次实时采集失败，但仍保留上一份成功数据。"
    elif latest_success:
        status = "ok"
        message = "实时单量收入最近成功采集可用。"
    else:
        status = "partial"
        message = "实时单量收入采集不完整。"
    return {
        "generated_at": now_text(),
        "status": status,
        "message": message,
        "last_success_at": latest.get("generated_at", "") if latest_success else "",
        "last_failure_at": failed.get("generated_at", "") if failed else "",
        "failure_type": failure_type,
        "latest": {
            "status": latest.get("status", ""),
            "summary": latest_summary,
        },
        "last_failed": {
            "status": failed.get("status", ""),
            "summary": failed_summary,
            "errors": failed.get("errors") or [],
            "missing": failed.get("missing") or [],
        },
        "task_run": {
            "status": task_run.get("status", ""),
            "message": task_run.get("message", ""),
            "step": task_run.get("step", ""),
            "updated_at": task_run.get("updated_at", ""),
            "failure_type": task_run.get("failure_type", ""),
        },
        "summary": {
            "platform_store_count": int(latest_summary.get("platform_store_count") or 0),
            "missing_count": int(latest_summary.get("missing_count") or 0),
            "failed_missing_count": int(failed_summary.get("missing_count") or 0),
            "total_orders": int(latest_summary.get("total_orders") or 0),
            "total_income": float(latest_summary.get("total_income") or 0),
        },
    }


def main() -> int:
    payload = build_payload()
    write_latest(payload)
    print(payload["message"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
