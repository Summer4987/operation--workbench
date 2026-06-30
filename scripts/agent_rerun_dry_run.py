from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from atomic_io import atomic_write_text


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MONITOR_PATH = ROOT / "outputs" / "agent_task_monitor" / "latest.json"
DEFAULT_OUTPUT_PATH = ROOT / "outputs" / "agent_task_monitor" / "rerun_dry_run_latest.json"
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


def build_dry_run(payload: dict[str, Any]) -> dict[str, Any]:
    tasks_by_id = {
        str(task.get("id")): task
        for task in payload.get("tasks") or []
        if isinstance(task, dict) and task.get("id")
    }
    executable: list[dict[str, Any]] = []
    report_only: list[dict[str, Any]] = []

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
        if entry["auto_allowed"]:
            executable.append(entry)
        else:
            report_only.append(entry)

    return {
        "source_generated_at": payload.get("generated_at", ""),
        "safety": {
            "executes_commands": False,
            "dry_run_only": True,
            "high_risk_policy": "report_only",
        },
        "summary": {
            "total": len(executable) + len(report_only),
            "dry_run_candidates": len(executable),
            "report_only": len(report_only),
        },
        "dry_run_candidates": executable,
        "report_only": report_only,
    }


def format_text(plan: dict[str, Any]) -> str:
    summary = plan["summary"]
    lines = [
        "自动化补跑 dry-run 计划",
        f"候选 {summary['dry_run_candidates']} 个｜只报告 {summary['report_only']} 个｜实际执行 0 个",
    ]
    if plan["dry_run_candidates"]:
        lines.append("")
        lines.append("可进入 dry-run 的低风险/幂等任务：")
        for item in plan["dry_run_candidates"]:
            lines.append(f"- {item['task_name']}：{' '.join(item['command'])}")
    if plan["report_only"]:
        lines.append("")
        lines.append("只报告，不执行：")
        for item in plan["report_only"]:
            blocked = "、".join(item["blocked_by"]) or item["reason"] or "策略未允许"
            lines.append(f"- {item['task_name']}：{blocked}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="读取自动化透明化报告，生成安全补跑 dry-run 计划；不执行命令。")
    parser.add_argument("--monitor", default=str(DEFAULT_MONITOR_PATH), help="agent_task_monitor 生成的 latest.json")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH), help="dry-run 计划输出路径")
    parser.add_argument("--no-write", action="store_true", help="只打印，不写 outputs")
    args = parser.parse_args()

    payload = read_json(Path(args.monitor).expanduser())
    if not payload:
        print("没有可读取的自动化透明化报告，请先运行 scripts/agent_task_monitor.py。", file=sys.stderr)
        return 2

    plan = build_dry_run(payload)
    text = format_text(plan)
    if not args.no_write:
        output = Path(args.output).expanduser()
        atomic_write_text(output, json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
