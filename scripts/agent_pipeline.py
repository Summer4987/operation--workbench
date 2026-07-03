from __future__ import annotations

import argparse
import json
import os
import shlex
import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from atomic_io import atomic_write_text
from task_run_state import classify_failure_text, record_task_event


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "agent_pipelines.json"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "agent_pipeline"
EXECUTION_AGENTS = {"execute", "execution"}


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


def resolve_path(value: str) -> Path:
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path


def expand_command(command: list[str]) -> list[str]:
    replacements = {
        "{python}": sys.executable or os.environ.get("PYTHON", "python3"),
        "{root}": str(ROOT),
    }
    return [replacements.get(str(part), str(part).format(root=ROOT, python=replacements["{python}"])) for part in command]


def load_config(path: Path) -> dict[str, Any]:
    payload = read_json(path, {})
    if not isinstance(payload, dict):
        raise SystemExit(f"agent pipeline 配置不是 JSON object：{path}")
    return payload


def find_pipeline(config: dict[str, Any], pipeline_id: str) -> dict[str, Any]:
    for pipeline in config.get("pipelines") or []:
        if isinstance(pipeline, dict) and pipeline.get("id") == pipeline_id:
            return pipeline
    available = ", ".join(str(item.get("id")) for item in config.get("pipelines") or [] if isinstance(item, dict))
    raise SystemExit(f"没有找到 pipeline：{pipeline_id}。可用：{available}")


def validate_required_outputs(stage: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    for output in stage.get("required_outputs") or []:
        path = resolve_path(str(output))
        if not path.exists():
            issues.append(f"缺少产物：{relpath(path)}")
            continue
        if path.suffix == ".json":
            payload = read_json(path, None)
            if not isinstance(payload, (dict, list)):
                issues.append(f"JSON 产物不可读取：{relpath(path)}")

    for check in stage.get("json_required") or []:
        if not isinstance(check, dict):
            continue
        path = resolve_path(str(check.get("path") or ""))
        payload = read_json(path, {})
        if not isinstance(payload, dict):
            issues.append(f"JSON 产物不是对象：{relpath(path)}")
            continue
        for key in check.get("keys") or []:
            if key not in payload:
                issues.append(f"{relpath(path)} 缺少字段：{key}")
    return issues


def run_command(command: list[str], *, timeout: int | None = None) -> tuple[int, str]:
    expanded = expand_command(command)
    result = subprocess.run(
        expanded,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    return result.returncode, result.stdout or ""


def build_notify_text(pipeline: dict[str, Any], stages: list[dict[str, Any]]) -> str:
    failed = [stage for stage in stages if stage["status"] == "failed"]
    skipped = [stage for stage in stages if stage["status"] == "skipped"]
    ok_count = sum(1 for stage in stages if stage["status"] == "success")
    title = pipeline.get("name") or pipeline.get("id")
    if failed:
        first = failed[0]
        line = f"{title}：有 {len(failed)} 个 agent 失败，先看 {first['name']}。原因：{first.get('message') or '未写明'}。"
    else:
        executed = [
            stage for stage in stages if stage["status"] == "success" and str(stage.get("agent") or "").lower() in EXECUTION_AGENTS
        ]
        if executed:
            line = f"{title}：{ok_count} 个 agent 已完成，执行 Agent 已参与非订货任务。"
        else:
            line = f"{title}：{ok_count} 个 agent 已完成，未触发真实执行动作。"
    if skipped:
        line += f" 跳过 {len(skipped)} 个 agent。"
    return line


def run_stage(stage: dict[str, Any], *, allow_execution: bool, dry_run: bool) -> dict[str, Any]:
    agent_type = str(stage.get("agent") or stage.get("id") or "").lower()
    name = str(stage.get("name") or stage.get("id") or agent_type)
    started_at = now_text()
    record: dict[str, Any] = {
        "id": str(stage.get("id") or agent_type),
        "agent": agent_type,
        "name": name,
        "status": "running",
        "started_at": started_at,
        "finished_at": "",
        "message": "",
        "returncode": None,
        "command": stage.get("command") or [],
        "issues": [],
    }

    if agent_type in EXECUTION_AGENTS and not allow_execution:
        record.update(
            {
                "status": "skipped",
                "finished_at": now_text(),
                "message": "执行 Agent 需要显式 --allow-execution；未启用时只做观察、校验、分析、通知和巡检。",
            }
        )
        return record

    if stage.get("enabled") is False:
        record.update({"status": "skipped", "finished_at": now_text(), "message": "配置中已禁用。"})
        return record

    if dry_run:
        command = stage.get("command") or []
        display = " ".join(shlex.quote(str(part)) for part in expand_command(command)) if command else "无命令"
        record.update({"status": "success", "finished_at": now_text(), "message": f"dry-run：{display}"})
        return record

    command = stage.get("command") or []
    output = ""
    returncode = 0
    try:
        if command:
            returncode, output = run_command(command, timeout=stage.get("timeout_seconds"))
    except subprocess.TimeoutExpired as exc:
        returncode = 124
        output = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        output += f"\n命令超时：{stage.get('timeout_seconds')} 秒"
    except FileNotFoundError as exc:
        returncode = 127
        output = f"任务命令不存在：{exc.filename}"

    issues = validate_required_outputs(stage)
    record["returncode"] = returncode
    record["output_tail"] = output[-4000:]
    record["issues"] = issues
    record["finished_at"] = now_text()
    if returncode == 0 and not issues:
        record["status"] = "success"
        record["message"] = str(stage.get("success_message") or "完成。")
    else:
        record["status"] = "failed"
        failure_parts = []
        if returncode != 0:
            failure_parts.append(f"退出码 {returncode}")
        failure_parts.extend(issues)
        record["message"] = "；".join(failure_parts) or "阶段失败。"
        record["failure_type"] = classify_failure_text(record["message"] + "\n" + output, returncode)
    return record


def run_pipeline(args: argparse.Namespace) -> dict[str, Any]:
    config_path = Path(args.config).expanduser()
    config = load_config(config_path)
    pipeline = find_pipeline(config, args.pipeline)
    task_id = str(pipeline.get("task_id") or f"agents.{pipeline['id']}")
    output_dir = Path(args.output_dir).expanduser() / str(pipeline["id"])
    latest_path = output_dir / "latest.json"
    text_path = output_dir / "latest.txt"

    record_task_event(
        task_id,
        "running",
        message=f"{pipeline.get('name') or pipeline['id']} 开始。",
        step="agent pipeline",
        log_path=latest_path,
        extra={"pipeline_id": pipeline["id"]},
    )

    stage_records: list[dict[str, Any]] = []
    for stage in pipeline.get("stages") or []:
        if not isinstance(stage, dict):
            continue
        stage_record = run_stage(stage, allow_execution=args.allow_execution, dry_run=args.dry_run)
        stage_records.append(stage_record)
        if stage_record["status"] == "failed" and stage.get("continue_on_failure") is not True:
            break

    notify_text = build_notify_text(pipeline, stage_records)
    payload = {
        "generated_at": now_text(),
        "host": socket.gethostname(),
        "config": relpath(config_path),
        "pipeline": {
            "id": pipeline["id"],
            "name": pipeline.get("name") or pipeline["id"],
            "task_id": task_id,
            "risk_policy": pipeline.get("risk_policy") or "no_execution_by_default",
        },
        "safety": {
            "allow_execution": bool(args.allow_execution),
            "dry_run": bool(args.dry_run),
            "execution_agent_enabled": bool(args.allow_execution),
            "ordering_excluded": True,
        },
        "summary": {
            "total": len(stage_records),
            "success": sum(1 for item in stage_records if item["status"] == "success"),
            "failed": sum(1 for item in stage_records if item["status"] == "failed"),
            "skipped": sum(1 for item in stage_records if item["status"] == "skipped"),
        },
        "stages": stage_records,
        "notify_text": notify_text,
    }
    write_json(latest_path, payload)
    atomic_write_text(text_path, notify_text + "\n")

    failed = [stage for stage in stage_records if stage["status"] == "failed"]
    if failed:
        record_task_event(
            task_id,
            "failed",
            message=notify_text,
            step=failed[0]["name"],
            log_path=latest_path,
            returncode=1,
            failure_type=failed[0].get("failure_type") or "execution_failed",
            extra={"pipeline_id": pipeline["id"], "failed_stage": failed[0]["id"]},
        )
    else:
        record_task_event(
            task_id,
            "success",
            message=notify_text,
            step="agent pipeline",
            log_path=latest_path,
            returncode=0,
            extra={"pipeline_id": pipeline["id"], "stage_count": len(stage_records)},
        )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="运行只读优先的多 Agent 编排流程。")
    parser.add_argument("pipeline", nargs="?", default="daily_automation_guard", help="config/agent_pipelines.json 中的 pipeline id")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="pipeline 配置路径")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="运行产物目录")
    parser.add_argument("--dry-run", action="store_true", help="只展示会运行的阶段，不执行命令")
    parser.add_argument("--allow-execution", action="store_true", help="允许 execution agent；默认禁止")
    args = parser.parse_args()

    payload = run_pipeline(args)
    summary = payload["summary"]
    print(
        f"Agent pipeline {payload['pipeline']['id']} 完成："
        f"成功 {summary['success']}，失败 {summary['failed']}，跳过 {summary['skipped']}。"
    )
    print(payload["notify_text"])
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
