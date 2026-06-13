from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TASK_RUNS_PATH = ROOT / "outputs" / "task_runs" / "latest.json"
OUTPUT_DIR = ROOT / "outputs" / "morning_collection_status"
LATEST_PATH = OUTPUT_DIR / "latest.json"
TASK_ID = "ops.morning_collection"

EXPECTED_STEPS = [
    "启动/检查后台 Chrome",
    "双平台评价下载",
    "门店日报采集并发布",
    "推广余额总巡检",
    "同步云端预算配置",
    "推广预算初始化预览",
    "饿了么午餐预算真实提交",
    "美团午餐预算真实提交",
    "饿了么晚餐预算真实提交",
    "美团晚餐预算真实提交",
    "运营总看板数据更新",
    "运营总看板发布腾讯云",
]


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


def latest_start_index(events: list[dict[str, Any]]) -> int:
    for index in range(len(events) - 1, -1, -1):
        event = events[index]
        if event.get("task_id") == TASK_ID and event.get("step") == "start":
            return index
    for index in range(len(events) - 1, -1, -1):
        if events[index].get("task_id") == TASK_ID:
            return index
    return -1


def event_step_status(event: dict[str, Any]) -> str:
    if event.get("status") == "failed":
        return "failed"
    message = str(event.get("message") or "")
    if "完成" in message:
        return "success"
    if event.get("status") == "success":
        return "success"
    if event.get("status") == "skipped":
        return "skipped"
    return "running"


def summarize_steps(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_step: dict[str, dict[str, Any]] = {}
    for event in events:
        step = str(event.get("step") or "")
        if not step or step in {"start", "finish", "exception"}:
            continue
        if step not in EXPECTED_STEPS and not any(step.startswith(prefix) for prefix in ("饿了么", "美团")):
            continue
        by_step[step] = {
            "name": step,
            "status": event_step_status(event),
            "message": event.get("message") or "",
            "failure_type": event.get("failure_type") or "",
            "returncode": event.get("returncode"),
            "log_path": event.get("log_path") or "",
            "updated_at": event.get("created_at") or "",
        }
    return sorted(by_step.values(), key=lambda item: parse_time(item.get("updated_at")) or datetime.min)


def build_payload() -> dict[str, Any]:
    run_state = read_json(TASK_RUNS_PATH, {"tasks": {}, "events": []})
    all_events = [event for event in run_state.get("events", []) if event.get("task_id") == TASK_ID]
    start_index = latest_start_index(run_state.get("events", []))
    session_events = []
    if start_index >= 0:
        session_events = [
            event
            for event in run_state.get("events", [])[start_index:]
            if event.get("task_id") == TASK_ID
        ]
    steps = summarize_steps(session_events)
    task = (run_state.get("tasks") or {}).get(TASK_ID) or {}
    failed_steps = [step for step in steps if step["status"] == "failed"]
    completed_steps = [step for step in steps if step["status"] == "success"]
    running_steps = [step for step in steps if step["status"] == "running"]
    if not all_events:
        status = "missing_run"
        message = "尚未找到上午运营一键采集运行记录。"
    elif failed_steps or task.get("status") == "failed":
        status = "failed"
        message = f"上午运营一键采集有 {len(failed_steps)} 个子步骤失败。"
    elif task.get("status") == "success":
        status = "success"
        message = f"上午运营一键采集完成，{len(completed_steps)} 个子步骤有完成记录。"
    else:
        status = "running" if running_steps else "partial"
        message = f"上午运营一键采集已有 {len(steps)} 个子步骤记录。"
    return {
        "generated_at": now_text(),
        "status": status,
        "task_status": task.get("status", ""),
        "task_message": task.get("message", ""),
        "started_at": task.get("started_at", ""),
        "finished_at": task.get("finished_at", ""),
        "updated_at": task.get("updated_at", ""),
        "summary": {
            "step_count": len(steps),
            "completed_count": len(completed_steps),
            "failed_count": len(failed_steps),
            "running_count": len(running_steps),
            "event_count": len(all_events),
        },
        "steps": steps,
        "failed_steps": failed_steps,
        "message": message,
    }


def main() -> int:
    payload = build_payload()
    write_latest(payload)
    print(payload["message"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
