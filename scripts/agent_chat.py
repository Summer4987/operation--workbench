from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from atomic_io import atomic_write_text


ROOT = Path(__file__).resolve().parents[1]
PIPELINE_ID = "daily_automation_guard"
PIPELINE_PATH = ROOT / "outputs" / "agent_pipeline" / PIPELINE_ID / "latest.json"
MONITOR_PATH = ROOT / "outputs" / "agent_task_monitor" / "latest.json"
TASK_RUNS_PATH = ROOT / "outputs" / "task_runs" / "latest.json"
OUTPUT_DIR = ROOT / "outputs" / "agent_chat"


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


def run_refresh() -> dict[str, Any]:
    command = [sys.executable or "python3", str(ROOT / "scripts" / "agent_pipeline.py"), PIPELINE_ID]
    result = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return {
        "command": command,
        "returncode": result.returncode,
        "output_tail": (result.stdout or "")[-4000:],
    }


def compact_reason(value: Any, fallback: str = "没有写明原因") -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    return text.replace("\n", " ")[:180].rstrip("。.")


def skipped_execution_agents(pipeline: dict[str, Any]) -> list[dict[str, Any]]:
    stages = pipeline.get("stages") if isinstance(pipeline.get("stages"), list) else []
    return [
        stage
        for stage in stages
        if isinstance(stage, dict)
        and str(stage.get("agent") or "").lower() in {"execute", "execution"}
        and stage.get("status") == "skipped"
    ]


def failed_pipeline_stages(pipeline: dict[str, Any]) -> list[dict[str, Any]]:
    stages = pipeline.get("stages") if isinstance(pipeline.get("stages"), list) else []
    return [stage for stage in stages if isinstance(stage, dict) and stage.get("status") == "failed"]


def attention_tasks(monitor: dict[str, Any]) -> list[dict[str, Any]]:
    rows = monitor.get("tasks") if isinstance(monitor.get("tasks"), list) else []
    return [
        row
        for row in rows
        if isinstance(row, dict) and row.get("status") in {"failed", "attention", "missing", "running"}
    ]


def rerun_candidates(monitor: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    plan = monitor.get("rerun_plan") if isinstance(monitor.get("rerun_plan"), list) else []
    allowed = [item for item in plan if isinstance(item, dict) and item.get("auto_allowed")]
    manual = [item for item in plan if isinstance(item, dict) and not item.get("auto_allowed")]
    return allowed, manual


def build_status_answer(pipeline: dict[str, Any], monitor: dict[str, Any]) -> str:
    summary = pipeline.get("summary") if isinstance(pipeline.get("summary"), dict) else {}
    monitor_summary = monitor.get("summary") if isinstance(monitor.get("summary"), dict) else {}
    line = (
        f"现在这组 agent 最近一次运行是 {pipeline.get('generated_at') or '未知时间'}："
        f"成功 {summary.get('success', 0)} 个，失败 {summary.get('failed', 0)} 个，"
        f"跳过 {summary.get('skipped', 0)} 个。"
    )
    if monitor_summary:
        line += (
            f" 透明化报告里完成 {monitor_summary.get('completed', 0)} 个，"
            f"失败 {monitor_summary.get('failed', 0)} 个，需关注 {monitor_summary.get('attention', 0)} 个。"
        )
    skipped = skipped_execution_agents(pipeline)
    if skipped:
        names = "、".join(str(stage.get("name") or stage.get("id")) for stage in skipped)
        line += f" 被跳过的是：{names}。它默认禁用，避免触发真实执行动作。"
    return line


def build_problem_answer(pipeline: dict[str, Any], monitor: dict[str, Any]) -> str:
    failed_stages = failed_pipeline_stages(pipeline)
    if failed_stages:
        first = failed_stages[0]
        return f"agent 流程本身有失败：{first.get('name')}。原因：{compact_reason(first.get('message'))}。"

    rows = attention_tasks(monitor)
    if not rows:
        return "这组 agent 本身没有失败项。当前没有从透明化报告里读到失败或需关注任务。"

    parts = []
    for row in rows[:5]:
        name = row.get("name") or row.get("id")
        status = row.get("status_text") or row.get("status")
        reason = compact_reason(row.get("failure_reason") or row.get("message"))
        parts.append(f"{name}：{status}，{reason}")
    extra = "" if len(rows) <= 5 else f" 另外还有 {len(rows) - 5} 项，建议看 outputs/agent_task_monitor/latest.json。"
    return "现在主要问题是：" + "；".join(parts) + "。" + extra


def build_rerun_answer(monitor: dict[str, Any]) -> str:
    allowed, manual = rerun_candidates(monitor)
    if not allowed and not manual:
        return "当前没有读到补跑计划。"
    parts = []
    if allowed:
        names = "、".join(str(item.get("task_name") or item.get("task_id")) for item in allowed[:6])
        parts.append(f"可以自动补跑的是：{names}")
    if manual:
        names = "、".join(str(item.get("task_name") or item.get("task_id")) for item in manual[:6])
        parts.append(f"需要人工确认或只报告的是：{names}")
    return "；".join(parts) + "。"


def build_execution_answer(pipeline: dict[str, Any]) -> str:
    skipped = skipped_execution_agents(pipeline)
    if not skipped:
        return "这次没有读到被跳过的执行 Agent。"
    details = []
    for stage in skipped:
        details.append(
            f"{stage.get('name') or stage.get('id')}（id: {stage.get('id')}, agent: {stage.get('agent')}）："
            f"{compact_reason(stage.get('message'))}"
        )
    return "刚刚跳过的是 " + "；".join(details) + "。"


def answer_question(question: str, *, refreshed: dict[str, Any] | None = None) -> dict[str, Any]:
    pipeline = read_json(PIPELINE_PATH, {})
    monitor = read_json(MONITOR_PATH, {})
    task_runs = read_json(TASK_RUNS_PATH, {})
    normalized = question.strip() or "现在怎么样？"
    lower = normalized.lower()

    if any(keyword in normalized for keyword in ("执行", "跳过", "4号", "4 号")):
        intent = "execution_agent"
        answer = build_execution_answer(pipeline)
    elif any(keyword in normalized for keyword in ("补跑", "重跑", "恢复")):
        intent = "rerun"
        answer = build_rerun_answer(monitor)
    elif any(keyword in normalized for keyword in ("问题", "失败", "异常", "坏", "报错")):
        intent = "problems"
        answer = build_problem_answer(pipeline, monitor)
    elif "help" in lower or "怎么问" in normalized or "帮助" in normalized:
        intent = "help"
        answer = "你可以问：今天哪里有问题、哪些任务能补跑、刚刚跳过的执行 Agent 是谁、现在 agent 状态怎么样。"
    else:
        intent = "status"
        answer = build_status_answer(pipeline, monitor)

    return {
        "generated_at": now_text(),
        "host": socket.gethostname(),
        "question": normalized,
        "intent": intent,
        "answer": answer,
        "sources": {
            "pipeline": str(PIPELINE_PATH.relative_to(ROOT)),
            "monitor": str(MONITOR_PATH.relative_to(ROOT)),
            "task_runs": str(TASK_RUNS_PATH.relative_to(ROOT)),
        },
        "refresh": refreshed or {"ran": False},
        "task_runs_generated_at": task_runs.get("generated_at") if isinstance(task_runs, dict) else "",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="和本地多 Agent 运行结果对话。")
    parser.add_argument("question", nargs="*", help="要问 agent 的问题")
    parser.add_argument("--refresh", action="store_true", help="回答前先安全刷新 daily_automation_guard")
    parser.add_argument("--json-out", default=str(OUTPUT_DIR / "latest.json"), help="JSON 回答输出路径")
    parser.add_argument("--text-out", default=str(OUTPUT_DIR / "latest.txt"), help="文本回答输出路径")
    args = parser.parse_args()

    refreshed = None
    if args.refresh:
        refresh_result = run_refresh()
        refreshed = {"ran": True, **refresh_result}

    question = " ".join(args.question).strip() or "现在 agent 状态怎么样？"
    payload = answer_question(question, refreshed=refreshed)
    json_out = Path(args.json_out).expanduser()
    text_out = Path(args.text_out).expanduser()
    write_json(json_out, payload)
    atomic_write_text(text_out, payload["answer"] + "\n")
    print(payload["answer"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
