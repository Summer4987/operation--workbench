from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from atomic_io import atomic_write_text


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "agent_pipelines.json"
DEFAULT_OUTPUT_PATH = ROOT / "outputs" / "agent_execution" / "latest.json"

ORDERING_KEYWORDS = (
    "订货",
    "下单",
    "采购",
    "快驴",
    "order",
    "purchase",
    "kuailv",
    "inventory_order",
)


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_json(path: Path, fallback: Any) -> Any:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if payload is not None else fallback
    except Exception:
        return fallback


def write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def relpath(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def expand_command(command: list[Any]) -> list[str]:
    python = sys.executable or os.environ.get("PYTHON", "python3")
    replacements = {"{python}": python, "{root}": str(ROOT)}
    return [replacements.get(str(part), str(part).format(root=ROOT, python=python)) for part in command]


def action_is_ordering(action: dict[str, Any]) -> bool:
    body = " ".join(
        [
            str(action.get("id") or ""),
            str(action.get("name") or ""),
            " ".join(str(part) for part in action.get("command") or []),
        ]
    ).lower()
    return any(keyword.lower() in body for keyword in ORDERING_KEYWORDS)


def configured_actions(config: dict[str, Any], pipeline_id: str) -> list[dict[str, Any]]:
    for pipeline in config.get("pipelines") or []:
        if isinstance(pipeline, dict) and pipeline.get("id") == pipeline_id:
            actions = pipeline.get("execution_actions")
            return [action for action in actions or [] if isinstance(action, dict)]
    return []


def run_action(action: dict[str, Any], *, timeout: int, dry_run: bool) -> dict[str, Any]:
    command = expand_command(action.get("command") or [])
    action_timeout = int(action.get("timeout_seconds") or timeout)
    record = {
        "id": str(action.get("id") or ""),
        "name": str(action.get("name") or action.get("id") or ""),
        "risk": str(action.get("risk") or "medium"),
        "command": command,
        "status": "pending",
        "returncode": None,
        "output_tail": "",
    }
    if action_is_ordering(action):
        record.update({"status": "blocked", "reason": "订货/下单/采购类动作被执行 Agent 排除。"})
        return record
    if not command:
        record.update({"status": "blocked", "reason": "没有配置命令。"})
        return record
    if dry_run:
        record.update({"status": "planned", "reason": "dry-run，仅展示执行计划。"})
        return record

    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=action_timeout,
        )
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        if not isinstance(output, str):
            output = output.decode(errors="replace")
        record.update(
            {
                "status": "failed",
                "returncode": 124,
                "output_tail": (output + f"\n动作超时：{action_timeout} 秒")[-4000:],
            }
        )
        return record
    output = result.stdout or ""
    record.update(
        {
            "status": "success" if result.returncode == 0 else "failed",
            "returncode": result.returncode,
            "output_tail": output[-4000:],
        }
    )
    return record


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    config = read_json(Path(args.config).expanduser(), {})
    actions = configured_actions(config, args.pipeline)
    selected = []
    for action in actions:
        action_id = str(action.get("id") or "")
        if args.action and action_id != args.action:
            continue
        if action.get("enabled") is False:
            selected.append(
                {
                    "id": action_id,
                    "name": action.get("name") or action_id,
                    "status": "skipped",
                    "reason": "配置中已禁用。",
                }
            )
            continue
        selected.append(run_action(action, timeout=args.timeout, dry_run=args.dry_run))

    summary = {
        "total": len(selected),
        "success": sum(1 for item in selected if item.get("status") == "success"),
        "failed": sum(1 for item in selected if item.get("status") == "failed"),
        "blocked": sum(1 for item in selected if item.get("status") == "blocked"),
        "planned": sum(1 for item in selected if item.get("status") == "planned"),
        "skipped": sum(1 for item in selected if item.get("status") == "skipped"),
    }
    return {
        "generated_at": now_text(),
        "pipeline": args.pipeline,
        "safety": {
            "ordering_excluded": True,
            "dry_run": bool(args.dry_run),
            "policy": "执行 Agent 可参与非订货任务；订货、下单、采购类动作一律拦截。",
        },
        "summary": summary,
        "actions": selected,
    }


def format_text(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    if payload["safety"].get("dry_run"):
        lead = f"执行 Agent 计划了 {summary['planned']} 个非订货动作，拦截 {summary['blocked']} 个订货相关动作。"
    else:
        lead = f"执行 Agent 已运行：成功 {summary['success']} 个，失败 {summary['failed']} 个，拦截 {summary['blocked']} 个。"
    details = []
    for action in payload.get("actions") or []:
        name = action.get("name") or action.get("id")
        status = action.get("status")
        reason = action.get("reason") or ("退出码 " + str(action.get("returncode")) if action.get("returncode") not in {None, 0} else "")
        details.append(f"{name}：{status}{'，' + reason.rstrip('。.') if reason else ''}。")
    return lead + ("\n" + "\n".join(details) if details else "") + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="执行 Agent：只参与非订货任务，订货/下单/采购类动作自动拦截。")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="agent pipeline 配置")
    parser.add_argument("--pipeline", default="daily_automation_guard", help="pipeline id")
    parser.add_argument("--action", default="", help="只执行指定 action id")
    parser.add_argument("--timeout", type=int, default=600, help="单个动作超时时间，秒")
    parser.add_argument("--dry-run", action="store_true", help="只生成执行计划，不真正执行")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH), help="输出 JSON 路径")
    args = parser.parse_args()

    payload = build_payload(args)
    write_json(Path(args.output).expanduser(), payload)
    print(format_text(payload), end="")
    return 1 if payload["summary"]["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
