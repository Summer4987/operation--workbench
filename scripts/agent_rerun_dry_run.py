from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from atomic_io import atomic_write_text


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MONITOR_PATH = ROOT / "outputs" / "agent_task_monitor" / "latest.json"
DEFAULT_OUTPUT_PATH = ROOT / "outputs" / "agent_task_monitor" / "rerun_dry_run_latest.json"
DEFAULT_EXECUTE_OUTPUT_PATH = ROOT / "outputs" / "agent_task_monitor" / "rerun_execute_latest.json"
HIGH_RISK_BLOCK = "high_risk_task"


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def resolve_command(command: list[Any]) -> list[str]:
    python = sys.executable or os.environ.get("PYTHON", "python3")
    node = os.environ.get("NODE", "node")
    replacements = {"{python}": python, "{node}": node}
    return [replacements.get(str(part), str(part)) for part in command]


def build_dry_run(payload: dict[str, Any], *, execute: bool = False, task_filter: str = "", timeout: int = 1800) -> dict[str, Any]:
    tasks_by_id = {
        str(task.get("id")): task
        for task in payload.get("tasks") or []
        if isinstance(task, dict) and task.get("id")
    }
    executable: list[dict[str, Any]] = []
    report_only: list[dict[str, Any]] = []
    executed: list[dict[str, Any]] = []

    for item in payload.get("rerun_plan") or []:
        if not isinstance(item, dict):
            continue
        task_id = str(item.get("task_id") or "")
        task = tasks_by_id.get(task_id, {})
        risk = str(task.get("risk") or "unknown")
        blocked_by = [str(value) for value in item.get("blocked_by") or []]
        if risk == "high" and HIGH_RISK_BLOCK not in blocked_by:
            blocked_by.append(HIGH_RISK_BLOCK)
        entry = {
            "task_id": task_id,
            "task_name": item.get("task_name") or task.get("name") or task_id,
            "risk": risk,
            "status": task.get("status", ""),
            "auto_allowed": bool(item.get("auto_allowed")) and risk != "high",
            "mode": "dry_run",
            "would_execute": False,
            "command": resolve_command(item.get("command") or []),
            "reason": item.get("reason", ""),
            "blocked_by": blocked_by,
        }
        if task_filter and task_filter not in {task_id, str(entry["task_name"])}:
            continue
        if entry["auto_allowed"]:
            if execute:
                execution = execute_command(entry["command"], timeout=timeout)
                entry.update(execution)
                executed.append(entry)
            executable.append(entry)
        else:
            report_only.append(entry)

    return {
        "source_generated_at": payload.get("generated_at", ""),
        "safety": {
            "executes_commands": bool(execute),
            "dry_run_only": not execute,
            "high_risk_policy": "report_only",
        },
        "summary": {
            "total": len(executable) + len(report_only),
            "dry_run_candidates": len(executable),
            "executed": len(executed),
            "succeeded": sum(1 for item in executed if item.get("returncode") == 0),
            "failed": sum(1 for item in executed if item.get("returncode") not in {0, None}),
            "report_only": len(report_only),
        },
        "dry_run_candidates": executable,
        "executed": executed,
        "report_only": report_only,
    }


def execute_command(command: list[str], *, timeout: int) -> dict[str, Any]:
    if not command:
        return {
            "would_execute": False,
            "executed": False,
            "returncode": None,
            "output": "没有配置补跑命令。",
        }
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    output = (completed.stdout or "").strip()
    return {
        "would_execute": True,
        "executed": True,
        "returncode": completed.returncode,
        "output": output[-4000:],
    }


def format_text(plan: dict[str, Any]) -> str:
    summary = plan["summary"]
    if plan["safety"].get("executes_commands"):
        lines = [
            f"我已经尝试补跑 {summary['executed']} 个低风险任务，成功 {summary['succeeded']} 个，失败 {summary['failed']} 个。",
        ]
        for item in plan.get("executed") or []:
            result = "成功" if item.get("returncode") == 0 else f"失败，退出码 {item.get('returncode')}"
            lines.append(f"{item['task_name']}：{result}。")
    else:
        lines = [
            f"可以补跑 {summary['dry_run_candidates']} 个低风险任务；只报告 {summary['report_only']} 个高风险或需人工确认的任务。",
        ]
        if plan["dry_run_candidates"]:
            names = "、".join(str(item["task_name"]) for item in plan["dry_run_candidates"])
            lines.append(f"可补跑：{names}。你说“执行补跑”时，我只会跑这些。")
    if plan["report_only"]:
        blocked_names = []
        for item in plan["report_only"]:
            blocked_names.append(str(item["task_name"]))
        lines.append(f"不自动补跑：{'、'.join(blocked_names)}。")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="读取自动化透明化报告，生成或执行安全补跑计划。")
    parser.add_argument("--monitor", default=str(DEFAULT_MONITOR_PATH), help="agent_task_monitor 生成的 latest.json")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH), help="dry-run 计划输出路径")
    parser.add_argument("--execute", action="store_true", help="执行 auto_allowed 的低风险补跑命令。")
    parser.add_argument("--task", default="", help="只补跑指定任务 ID 或名称。")
    parser.add_argument("--timeout", type=int, default=1800, help="单个补跑命令超时时间，秒。")
    parser.add_argument("--no-write", action="store_true", help="只打印，不写 outputs")
    args = parser.parse_args()

    payload = read_json(Path(args.monitor).expanduser())
    if not payload:
        print("没有可读取的自动化透明化报告，请先运行 scripts/agent_task_monitor.py。", file=sys.stderr)
        return 2

    plan = build_dry_run(payload, execute=args.execute, task_filter=args.task, timeout=args.timeout)
    text = format_text(plan)
    if not args.no_write:
        output = Path(args.output).expanduser() if not args.execute else DEFAULT_EXECUTE_OUTPUT_PATH
        atomic_write_text(output, json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
