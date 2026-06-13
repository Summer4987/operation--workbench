from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TASKS_PATH = ROOT / "config" / "ai_business_center_tasks.json"
REQUIRED_TASK_FIELDS = {
    "id",
    "name",
    "center",
    "module",
    "status",
    "risk",
    "schedule",
    "entrypoints",
    "outputs",
    "health_checks",
    "human_needed_when",
    "next_integration_step",
}
VALID_RISKS = {"low", "medium", "high"}
VALID_STATUSES = {"running", "running_unstable", "planned", "paused", "retired"}


def main() -> int:
    payload = json.loads(TASKS_PATH.read_text(encoding="utf-8"))
    tasks = payload.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("tasks must be a non-empty list")

    seen_ids: set[str] = set()
    errors: list[str] = []
    for index, task in enumerate(tasks, start=1):
        missing = sorted(REQUIRED_TASK_FIELDS - set(task))
        task_id = task.get("id") or f"#{index}"
        if missing:
            errors.append(f"{task_id}: missing fields {', '.join(missing)}")
        if task_id in seen_ids:
            errors.append(f"{task_id}: duplicate task id")
        seen_ids.add(str(task_id))
        if task.get("risk") not in VALID_RISKS:
            errors.append(f"{task_id}: invalid risk {task.get('risk')!r}")
        if task.get("status") not in VALID_STATUSES:
            errors.append(f"{task_id}: invalid status {task.get('status')!r}")
        for field in ("entrypoints", "outputs", "health_checks", "human_needed_when"):
            if not isinstance(task.get(field), list):
                errors.append(f"{task_id}: {field} must be a list")

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    centers = sorted({task["center"] for task in tasks})
    print(f"任务注册表校验通过：{len(tasks)} 个任务，{len(centers)} 个中心。")
    print("中心：" + "、".join(centers))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
