from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from task_run_state import classify_failure_text


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


def platform_for_step(step: str, message: str = "") -> str:
    text = f"{step} {message}"
    if "饿了么" in text:
        return "饿了么"
    if "美团" in text:
        return "美团"
    if "双平台" in text:
        return "双平台"
    return ""


def module_for_step(step: str) -> str:
    if "评价" in step:
        return "评价下载"
    if "日报" in step:
        return "日报采集"
    if "余额" in step:
        return "推广余额"
    if "预算" in step:
        return "推广预算"
    if "云端" in step or "发布" in step:
        return "云端同步"
    if "Chrome" in step:
        return "浏览器准备"
    if "总看板" in step:
        return "总看板"
    return "上午采集"


def human_action_for(step: str, failure_type: str, platform: str) -> str:
    target = platform or module_for_step(step)
    if failure_type == "auth_block":
        return f"在 Mac mini 的 Chrome 恢复{target}登录或验证码，再重跑上午一键采集。"
    if failure_type == "permission":
        return f"在 Mac mini 系统设置补齐{target}需要的屏幕录制/文件访问权限，再重跑上午一键采集。"
    if failure_type == "manual_browser_setup":
        return f"先在 Mac mini 的 Chrome 打开{target}后台页面并确认登录，再重跑上午一键采集。"
    if failure_type == "page_structure":
        return f"先人工核对{target}后台页面是否改版，再调整对应采集或预算脚本。"
    if failure_type == "timeout":
        return f"先确认{target}后台页面和网络可用；连续超时则重启 Chrome/CDP 后重跑上午一键采集。"
    if failure_type == "store_mapping":
        return f"检查{target}门店映射或门店名称是否变更，再重跑相关子步骤。"
    if "预算" in step:
        return f"先暂停真实预算提交，核对{target}预算页面、门店映射和目标预算后再重跑。"
    if "发布" in step or "云端" in step:
        return "先检查网络和云端发布权限，再重新发布运营总看板。"
    return f"查看{step}日志，确认登录、权限、页面结构和输入数据后重跑。"


def normalize_failure_type(message: str, returncode: int | None, fallback: str = "") -> str:
    if "屏幕录制" in str(message or "") or "could not create image from display" in str(message or ""):
        return "permission"
    return fallback or classify_failure_text(message, returncode)


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
        message = event.get("message") or ""
        failure_type = event.get("failure_type") or ""
        if event.get("status") == "failed" and not failure_type:
            failure_type = normalize_failure_type(message, event.get("returncode"))
        platform = platform_for_step(step, message)
        status = event_step_status(event)
        by_step[step] = {
            "name": step,
            "status": status,
            "module": module_for_step(step),
            "platform": platform,
            "message": message,
            "failure_type": failure_type,
            "human_action": human_action_for(step, failure_type, platform) if status == "failed" else "",
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
    recovery_actions = [
        {
            "step": step["name"],
            "module": step.get("module", ""),
            "platform": step.get("platform", ""),
            "failure_type": step.get("failure_type", ""),
            "message": step.get("message", ""),
            "human_action": step.get("human_action", ""),
            "log_path": step.get("log_path", ""),
        }
        for step in failed_steps
    ]
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
        "recovery_actions": recovery_actions,
        "human_action": "；".join(item["human_action"] for item in recovery_actions[:2] if item.get("human_action")),
        "message": message,
    }


def main() -> int:
    payload = build_payload()
    write_latest(payload)
    print(payload["message"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
