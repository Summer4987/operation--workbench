#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from atomic_io import atomic_write_text

import agent_task_monitor


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNS_PATH = ROOT / "outputs" / "task_runs" / "latest.json"
DEFAULT_STATE_PATH = ROOT / "outputs" / "agent_task_notifications" / "state.json"
DEFAULT_LOG_PATH = ROOT / "outputs" / "agent_task_notifications" / "latest.log"
DEFAULT_TARGET = "weixin"
TERMINAL_STATUSES = {"success", "failed", "skipped", "warning", "missing"}
STATUS_LABELS = {
    "success": "成功",
    "failed": "失败",
    "skipped": "跳过",
    "warning": "注意",
    "missing": "未记录",
}


def read_json(path: Path, fallback: Any) -> Any:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if payload is not None else fallback
    except Exception:
        return fallback


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def task_signature(task: dict[str, Any]) -> str:
    return "|".join(
        [
            str(task.get("status") or ""),
            str(task.get("finished_at") or task.get("updated_at") or ""),
            str(task.get("message") or ""),
            str(task.get("step") or ""),
        ]
    )


def synthetic_task_from_policy_row(row: dict[str, Any]) -> dict[str, Any] | None:
    status = str(row.get("status") or "")
    if status not in {"attention", "missing", "failed"}:
        return None
    mapped_status = "failed" if status == "failed" else "warning" if status == "attention" else "missing"
    return {
        "status": mapped_status,
        "message": row.get("failure_reason") or row.get("reason") or row.get("status_text") or "",
        "step": row.get("last_run_step") or "",
        "log_path": row.get("evidence") or "",
        "failure_type": row.get("failure_type") or "",
        "updated_at": row.get("last_run_at") or "",
        "finished_at": row.get("last_run_at") or "",
    }


def load_policy_rows() -> dict[str, dict[str, Any]]:
    args = argparse.Namespace(
        config=str(agent_task_monitor.DEFAULT_CONFIG_PATH),
        health=str(agent_task_monitor.DEFAULT_HEALTH_PATH),
        runs=str(agent_task_monitor.DEFAULT_RUNS_PATH),
    )
    payload = agent_task_monitor.build_payload(args)
    return {row["id"]: row for row in payload.get("tasks") or []}


def send_weixin(message: str, target: str, hermes_bin: str) -> tuple[bool, str]:
    result = subprocess.run(
        [hermes_bin, "send", "--to", target, message],
        cwd=str(ROOT),
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=45,
    )
    output = (result.stdout or "").strip()
    return result.returncode == 0, output


def build_message(task_id: str, task: dict[str, Any], row: dict[str, Any]) -> str:
    status = str(task.get("status") or "")
    status_label = STATUS_LABELS.get(status, status or "未知")
    name = row.get("name") or task_id
    updated_at = task.get("finished_at") or task.get("updated_at") or ""
    step = task.get("step") or ""
    message = task.get("message") or ""
    log_path = task.get("log_path") or ""
    failure_type = task.get("failure_type") or ""
    rerun = row.get("rerun") or {}

    lines = [
        f"[{status_label}] Mac mini 自动化任务：{name}",
        f"任务 ID：{task_id}",
    ]
    if updated_at:
        lines.append(f"时间：{updated_at}")
    if step:
        lines.append(f"步骤：{step}")
    if message:
        label = "失败原因" if status == "failed" else "需关注" if status in {"warning", "missing"} else "说明"
        lines.append(f"{label}：{message}")
    if failure_type and status == "failed":
        lines.append(f"失败分类：{failure_type}")
    if log_path:
        lines.append(f"日志/证据：{log_path}")

    if status == "failed":
        if rerun.get("suggested") and rerun.get("auto_allowed"):
            command = " ".join(str(part) for part in rerun.get("command") or [])
            lines.append(f"处理建议：该任务属于低风险/幂等任务，可进入 dry-run 补跑计划：{command}")
        elif rerun.get("suggested"):
            reason = rerun.get("reason") or "该任务只报告，不自动补跑。"
            lines.append(f"处理建议：{reason}")
        else:
            lines.append("处理建议：先查看日志，再决定是否人工补跑。")
    elif status in {"warning", "missing"}:
        if rerun.get("suggested") and rerun.get("auto_allowed"):
            command = " ".join(str(part) for part in rerun.get("command") or [])
            lines.append(f"处理建议：该任务需关注，可进入 dry-run 补跑计划：{command}")
        elif rerun.get("suggested"):
            reason = rerun.get("reason") or "该任务只报告，不自动补跑。"
            lines.append(f"处理建议：{reason}")
        else:
            lines.append("处理建议：先查看日志，再决定是否人工处理。")
    elif status == "success":
        lines.append("处理结果：任务已完成。")
    elif status == "skipped":
        lines.append("处理结果：任务已跳过，请按说明确认是否需要人工处理。")
    return "\n".join(lines)


def notify(args: argparse.Namespace) -> dict[str, Any]:
    runs_path = Path(args.runs).expanduser()
    state_path = Path(args.state).expanduser()
    runs = read_json(runs_path, {"tasks": {}})
    tasks = runs.get("tasks") if isinstance(runs.get("tasks"), dict) else {}
    previous_state = read_json(state_path, {"sent": {}})
    sent = previous_state.get("sent") if isinstance(previous_state.get("sent"), dict) else {}
    policy_rows = load_policy_rows()
    task_candidates = dict(tasks)
    for task_id, row in policy_rows.items():
        synthetic = synthetic_task_from_policy_row(row)
        if synthetic:
            task_candidates[task_id] = synthetic
    notifications = []
    now_sent = dict(sent)

    for task_id, task in sorted(task_candidates.items()):
        if not isinstance(task, dict):
            continue
        status = str(task.get("status") or "")
        if status not in TERMINAL_STATUSES:
            continue
        signature = task_signature(task)
        if args.seed:
            now_sent[task_id] = signature
            continue
        if sent.get(task_id) == signature:
            continue
        row = policy_rows.get(task_id, {"id": task_id, "name": task_id, "rerun": {}})
        message = build_message(task_id, task, row)
        delivered = False
        delivery_output = "dry-run"
        if not args.dry_run:
            delivered, delivery_output = send_weixin(message, args.target, args.hermes_bin)
        notifications.append(
            {
                "task_id": task_id,
                "status": status,
                "message": message,
                "delivered": delivered,
                "delivery_output": delivery_output,
            }
        )
        if args.dry_run or delivered:
            now_sent[task_id] = signature

    payload = {
        "runs_path": str(runs_path),
        "state_path": str(state_path),
        "seed": bool(args.seed),
        "dry_run": bool(args.dry_run),
        "target": args.target,
        "notification_count": len(notifications),
        "notifications": notifications,
        "sent": now_sent,
    }
    if not args.no_write:
        write_json(state_path, {"sent": now_sent})
        log_path = Path(args.log).expanduser()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(log_path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="按任务完成状态向 Hermes 微信发送自动化结果通知")
    parser.add_argument("--runs", default=str(DEFAULT_RUNS_PATH), help="任务运行状态 JSON")
    parser.add_argument("--state", default=str(DEFAULT_STATE_PATH), help="去重状态文件")
    parser.add_argument("--log", default=str(DEFAULT_LOG_PATH), help="最近一次通知器运行日志")
    parser.add_argument("--target", default=DEFAULT_TARGET, help="Hermes send 目标，默认 weixin home channel")
    parser.add_argument("--hermes-bin", default=str(Path.home() / ".local" / "bin" / "hermes"), help="Hermes CLI 路径")
    parser.add_argument("--seed", action="store_true", help="只记录当前状态，不发送历史通知")
    parser.add_argument("--dry-run", action="store_true", help="只打印将发送的通知，不实际发送")
    parser.add_argument("--no-write", action="store_true", help="不写 state/log 文件")
    args = parser.parse_args()

    payload = notify(args)
    if args.seed:
        print(f"已记录当前任务状态，未发送历史通知：{len(payload['sent'])} 个任务。")
    else:
        print(f"本次新增通知：{payload['notification_count']} 条。")
        for item in payload["notifications"]:
            print(f"- {item['task_id']} {item['status']} delivered={item['delivered']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
