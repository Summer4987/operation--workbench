#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from atomic_io import atomic_write_text

import agent_task_monitor
import hermes_schedule_status


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNS_PATH = ROOT / "outputs" / "task_runs" / "latest.json"
DEFAULT_STATE_PATH = ROOT / "outputs" / "agent_task_notifications" / "state.json"
DEFAULT_LOG_PATH = ROOT / "outputs" / "agent_task_notifications" / "latest.log"
DEFAULT_TARGET = "weixin"
MAX_BATCH_MESSAGE_CHARS = 3600
MIN_COOLDOWN_SECONDS = 180
ILINK_RATE_LIMIT_MIN_BACKOFF_SECONDS = 1800
ILINK_RATE_LIMIT_MAX_BACKOFF_SECONDS = 21600
COOLDOWN_RE = re.compile(r"cooldown active for\s+([0-9]+(?:\.[0-9]+)?)s", re.IGNORECASE)
TERMINAL_STATUSES = {"success", "failed", "skipped", "warning", "missing"}
STATUS_LABELS = {
    "success": "成功",
    "failed": "失败",
    "skipped": "跳过",
    "warning": "注意",
    "missing": "未记录",
}
STATUS_INTROS = {
    "success": "已经完成",
    "failed": "出问题了",
    "skipped": "这次跳过了",
    "warning": "需要看一下",
    "missing": "还没看到运行记录",
}
DIRECT_TASK_ROWS = {
    "ops.morning_collection": {
        "id": "ops.morning_collection",
        "name": "上午运营一键采集",
        "risk": "high",
        "rerun": {
            "suggested": True,
            "auto_allowed": False,
            "reason": "上午主流程会碰预算、登录态和发布，只报告不自动补跑。",
        },
    },
    "ops.realtime_order_income": {
        "id": "ops.realtime_order_income",
        "name": "实时单量和营业额采集",
        "risk": "low",
        "rerun": {
            "suggested": True,
            "auto_allowed": True,
            "command": ["/bin/zsh", "scripts/run_realtime_order_income.zsh"],
        },
    },
    "growth.promo_budget": {
        "id": "growth.promo_budget",
        "name": "推广预算任务",
        "risk": "high",
        "rerun": {
            "suggested": True,
            "auto_allowed": False,
            "reason": "会真实提交推广预算，只报告不自动补跑。",
        },
    },
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
    rows = {row["id"]: row for row in payload.get("tasks") or []}
    for task_id, row in DIRECT_TASK_ROWS.items():
        rows.setdefault(task_id, row)
    return rows


def load_schedule_issue_tasks() -> dict[str, dict[str, Any]]:
    payload = hermes_schedule_status.collect_status(period="all")
    generated_at = str(payload.get("generated_at") or "")
    generated_day = generated_at[:10]
    issue_tasks: dict[str, dict[str, Any]] = {}
    for row in payload.get("tasks") or []:
        if not isinstance(row, dict):
            continue
        status = str(row.get("status") or "")
        if status not in {"failed", "missing", "warning"}:
            continue
        label = str(row.get("label") or "")
        if not label:
            continue
        task_id = f"schedule.{label}"
        issue_tasks[task_id] = {
            "status": "failed" if status == "failed" else "missing" if status == "missing" else "warning",
            "message": row.get("reason") or "",
            "step": row.get("name") or label,
            "log_path": row.get("evidence") or "",
            "failure_type": "launchd_schedule",
            "updated_at": row.get("last_at") or generated_day,
            "finished_at": row.get("last_at") or generated_day,
            "extra": {
                "launchd_label": label,
                "schedule": row.get("schedule") or "",
                "status_code": row.get("status_code") or "",
            },
        }
    return issue_tasks


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


def cooldown_delay_seconds(output: str, *, minimum: int = MIN_COOLDOWN_SECONDS) -> int:
    match = COOLDOWN_RE.search(str(output or ""))
    if not match:
        return 0
    return max(minimum, int(float(match.group(1))) + 10)


def is_ilink_rate_limited(output: str) -> bool:
    body = str(output or "").lower()
    return "ilink" in body and "rate limited" in body


def delivery_backoff_seconds(output: str, consecutive_failures: int) -> int:
    if is_ilink_rate_limited(output):
        failures = max(1, consecutive_failures)
        return min(
            ILINK_RATE_LIMIT_MAX_BACKOFF_SECONDS,
            ILINK_RATE_LIMIT_MIN_BACKOFF_SECONDS * (2 ** (failures - 1)),
        )
    return cooldown_delay_seconds(output)


def build_batch_message(messages: list[str]) -> str:
    clean_messages = [compact_message(message) for message in messages if compact_message(message)]
    if not clean_messages:
        return ""
    if len(clean_messages) == 1:
        return clean_messages[0]
    header = f"我整理了 {len(clean_messages)} 条 Mac mini 自动化更新："
    body = "；".join(clean_messages)
    text = f"{header} {body}"
    if len(text) <= MAX_BATCH_MESSAGE_CHARS:
        return text
    truncated: list[str] = []
    remaining = MAX_BATCH_MESSAGE_CHARS - len(header) - 20
    for message in clean_messages:
        if remaining <= 0:
            break
        chunk = message[: max(0, remaining)]
        truncated.append(chunk.rstrip())
        remaining -= len(chunk) + 8
    return f"{header} " + "；".join(truncated).rstrip() + "。内容过长，已截断。"


def compact_message(message: str) -> str:
    return " ".join(str(message or "").split())


def build_message(task_id: str, task: dict[str, Any], row: dict[str, Any]) -> str:
    status = str(task.get("status") or "")
    status_intro = STATUS_INTROS.get(status, "有新状态")
    name = row.get("name") or task_id
    updated_at = task.get("finished_at") or task.get("updated_at") or ""
    step = task.get("step") or ""
    message = task.get("message") or ""
    log_path = task.get("log_path") or ""
    failure_type = task.get("failure_type") or ""
    rerun = row.get("rerun") or {}

    lines = [f"{name}{status_intro}。"]
    if message:
        if status == "success":
            lines.append(f"结果：{message}")
        elif status == "failed":
            lines.append(f"问题在这里：{message}")
        elif status in {"warning", "missing"}:
            lines.append(f"需要关注的是：{message}")
        else:
            lines.append(f"说明：{message}")
    if failure_type and status == "failed":
        lines.append(f"失败分类是 {failure_type}。")

    if status == "failed":
        if rerun.get("suggested") and rerun.get("auto_allowed"):
            command = " ".join(str(part) for part in rerun.get("command") or [])
            lines.append(f"我可以先准备 dry-run 补跑计划：{command}")
        elif rerun.get("suggested"):
            reason = rerun.get("reason") or "该任务只报告，不自动补跑。"
            lines.append(f"我不会自动补跑，原因：{reason}")
        else:
            lines.append("我建议先看日志，再决定要不要人工补跑。")
    elif status in {"warning", "missing"}:
        if rerun.get("suggested") and rerun.get("auto_allowed"):
            command = " ".join(str(part) for part in rerun.get("command") or [])
            lines.append(f"如果要处理，我可以先做 dry-run 补跑计划：{command}")
        elif rerun.get("suggested"):
            reason = rerun.get("reason") or "该任务只报告，不自动补跑。"
            lines.append(f"我不会自动处理，原因：{reason}")
        else:
            lines.append("我建议先看日志，再决定是否处理。")
    elif status == "success":
        lines.append("我这边先记为完成。")
    elif status == "skipped":
        lines.append("如果这不是你预期的跳过，我再帮你查原因。")

    details = []
    if updated_at:
        details.append(f"时间 {updated_at}")
    if step:
        details.append(f"步骤 {step}")
    if log_path:
        details.append(f"证据 {log_path}")
    if details:
        lines.append("细节：" + "；".join(details))
    return compact_message(" ".join(lines))


def notify(args: argparse.Namespace) -> dict[str, Any]:
    runs_path = Path(args.runs).expanduser()
    state_path = Path(args.state).expanduser()
    runs = read_json(runs_path, {"tasks": {}})
    tasks = runs.get("tasks") if isinstance(runs.get("tasks"), dict) else {}
    previous_state = read_json(state_path, {"sent": {}})
    sent = previous_state.get("sent") if isinstance(previous_state.get("sent"), dict) else {}
    cooldown_until = float(previous_state.get("cooldown_until") or 0)
    consecutive_failures = int(previous_state.get("consecutive_failures") or 0)
    now = time.time()
    policy_rows = load_policy_rows()
    task_candidates = dict(tasks)
    for task_id, task in load_schedule_issue_tasks().items():
        label = ((task.get("extra") or {}).get("launchd_label") or "") if isinstance(task, dict) else ""
        mapped_task_id = hermes_schedule_status.LABEL_TASK_IDS.get(str(label), "")
        if mapped_task_id and mapped_task_id in tasks:
            continue
        task_candidates[task_id] = task
    notifications = []
    pending_signatures: dict[str, str] = {}
    now_sent = dict(sent)

    for task_id, task in sorted(task_candidates.items()):
        if not isinstance(task, dict):
            continue
        if task_id not in policy_rows and not args.include_unconfigured and not task_id.startswith("schedule."):
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
        row = policy_rows.get(task_id, {"id": task_id, "name": task.get("step") or task_id, "rerun": {}})
        message = build_message(task_id, task, row)
        notifications.append(
            {
                "task_id": task_id,
                "status": status,
                "message": message,
                "delivered": bool(args.dry_run),
                "delivery_output": "dry-run" if args.dry_run else "pending-batch-send",
            }
        )
        pending_signatures[task_id] = signature

    skipped_by_cooldown = bool(not args.seed and not args.dry_run and notifications and cooldown_until > now)
    delivery_output = ""
    if skipped_by_cooldown:
        delivery_output = f"cooldown active until {int(cooldown_until)}"
        for item in notifications:
            item["delivered"] = False
            item["delivery_output"] = delivery_output
    elif notifications and not args.dry_run:
        batch_message = build_batch_message([str(item["message"]) for item in notifications])
        delivered, delivery_output = send_weixin(batch_message, args.target, args.hermes_bin) if batch_message else (False, "empty-message")
        for item in notifications:
            item["delivered"] = delivered
            item["delivery_output"] = delivery_output
        if delivered:
            now_sent.update(pending_signatures)
            cooldown_until = 0
            consecutive_failures = 0
        else:
            consecutive_failures += 1
            delay = delivery_backoff_seconds(delivery_output, consecutive_failures)
            if delay:
                cooldown_until = time.time() + delay
    elif args.dry_run:
        now_sent.update(pending_signatures)

    payload = {
        "runs_path": str(runs_path),
        "state_path": str(state_path),
        "seed": bool(args.seed),
        "dry_run": bool(args.dry_run),
        "target": args.target,
        "notification_count": len(notifications),
        "notifications": notifications,
        "skipped_by_cooldown": skipped_by_cooldown,
        "cooldown_until": cooldown_until,
        "consecutive_failures": consecutive_failures,
        "last_delivery_output": delivery_output,
        "sent": now_sent,
    }
    if not args.no_write:
        write_json(
            state_path,
            {
                "sent": now_sent,
                "cooldown_until": cooldown_until,
                "consecutive_failures": consecutive_failures,
                "last_delivery_output": delivery_output,
            },
        )
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
    parser.add_argument("--include-unconfigured", action="store_true", help="允许未进入通知配置的任务主动推送")
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
