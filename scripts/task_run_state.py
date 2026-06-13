from __future__ import annotations

import json
import os
import socket
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUN_STATE_DIR = ROOT / "outputs" / "task_runs"
LATEST_PATH = RUN_STATE_DIR / "latest.json"
MAX_EVENTS = 160

AUTH_BLOCK_PATTERNS = [
    "验证码",
    "安全验证",
    "安全中心",
    "风控",
    "未登录",
    "登录页",
    "请确认日常 Chrome 已登录",
    "请先在本地 Chrome 打开",
    "UNAUTHORIZED",
    "Permission denied",
]


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def runtime_environment() -> dict[str, str]:
    hostname = socket.gethostname()
    normalized = hostname.lower()
    role = os.environ.get("AI_BUSINESS_CENTER_ENV", "").strip().lower()
    if not role:
        if "macbook" in normalized:
            role = "development"
        elif "mini" in normalized:
            role = "production"
        else:
            role = "development"
    return {"role": role, "hostname": hostname}


def read_state() -> dict[str, Any]:
    try:
        payload = json.loads(LATEST_PATH.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload.setdefault("tasks", {})
            payload.setdefault("events", [])
            return payload
    except Exception:
        pass
    return {"generated_at": "", "tasks": {}, "events": []}


def write_state(payload: dict[str, Any]) -> None:
    RUN_STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload["generated_at"] = now_text()
    LATEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LATEST_PATH.chmod(0o644)


def classify_failure_text(text: str | None, returncode: int | None = None) -> str:
    body = str(text or "")
    if returncode == 124 or "超时" in body or "timeout" in body.lower():
        return "timeout"
    if any(pattern in body for pattern in AUTH_BLOCK_PATTERNS):
        return "auth_block"
    if "不在" in body and "允许窗口" in body:
        return "outside_allowed_window"
    if "Permission denied" in body:
        return "permission"
    return "execution_failed"


def record_task_event(
    task_id: str,
    status: str,
    *,
    message: str = "",
    step: str = "",
    log_path: str | Path = "",
    returncode: int | None = None,
    failure_type: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = read_state()
    environment = runtime_environment()
    tasks = payload.setdefault("tasks", {})
    events = deque(payload.setdefault("events", []), maxlen=MAX_EVENTS)
    timestamp = now_text()
    previous = tasks.get(task_id, {}) if isinstance(tasks.get(task_id), dict) else {}
    task = {
        **previous,
        "task_id": task_id,
        "status": status,
        "message": message,
        "step": step,
        "log_path": str(log_path) if log_path else previous.get("log_path", ""),
        "returncode": returncode,
        "failure_type": failure_type,
        "environment": environment,
        "updated_at": timestamp,
    }
    if status == "running":
        task["started_at"] = previous.get("started_at") or timestamp
        task.pop("finished_at", None)
    elif status in {"success", "failed", "skipped"}:
        task["finished_at"] = timestamp
        task.setdefault("started_at", previous.get("started_at") or timestamp)
    if extra:
        task["extra"] = {**previous.get("extra", {}), **extra}
    tasks[task_id] = task
    events.append(
        {
            "task_id": task_id,
            "status": status,
            "message": message,
            "step": step,
            "log_path": str(log_path) if log_path else "",
            "returncode": returncode,
            "failure_type": failure_type,
            "environment": environment,
            "created_at": timestamp,
        }
    )
    payload["events"] = list(events)
    write_state(payload)
    return task
