from __future__ import annotations

import json
import socket
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from atomic_io import atomic_write_text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import agent_chat  # noqa: E402
import agent_command  # noqa: E402


OUTPUT_DIR = ROOT / "outputs" / "agent_mobile"
LATEST_PATH = OUTPUT_DIR / "latest.json"

QUESTIONS = [
    ("status", "现在 agent 状态怎么样？"),
    ("problems", "今天哪里有问题？"),
    ("rerun", "哪些任务可以补跑？"),
    ("execution_agent", "刚刚跳过的执行 Agent 是谁？"),
]

SAMPLE_COMMANDS = [
    "今天跑得稳不稳？",
    "今天哪里有问题？",
    "刷新状态",
    "预算那边是不是又挂了？",
    "执行非订货恢复",
    "重跑预算设置",
    "确认执行预算重跑",
    "发布手机入口",
    "订货补跑",
]


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


def build_payload() -> dict[str, Any]:
    answers = []
    for key, question in QUESTIONS:
        response = agent_chat.answer_question(question, use_llm=False)
        answers.append(
            {
                "id": key,
                "question": question,
                "answer": response["answer"],
                "intent": response["intent"],
            }
        )

    pipeline = read_json(agent_chat.PIPELINE_PATH, {})
    monitor = read_json(agent_chat.MONITOR_PATH, {})
    pipeline_summary = pipeline.get("summary") if isinstance(pipeline.get("summary"), dict) else {}
    monitor_summary = monitor.get("summary") if isinstance(monitor.get("summary"), dict) else {}
    return {
        "generated_at": now_text(),
        "host": socket.gethostname(),
        "page_title": "Agent 手机入口",
        "summary": {
            "pipeline_generated_at": pipeline.get("generated_at", ""),
            "agent_success": pipeline_summary.get("success", 0),
            "agent_failed": pipeline_summary.get("failed", 0),
            "agent_skipped": pipeline_summary.get("skipped", 0),
            "task_completed": monitor_summary.get("completed", 0),
            "task_failed": monitor_summary.get("failed", 0),
            "task_attention": monitor_summary.get("attention", 0),
        },
        "safety": {
            "mobile_can_execute": False,
            "execution_agent_enabled": False,
            "note": "手机入口只展示最近一次 Mac mini 生成的 agent 报告，不执行预算、出价、订货、财务发布或云端发布。",
        },
        "answers": answers,
        "commands": [
            {
                "text": command,
                "intent": agent_command.classify_intent_with_llm(command, use_llm=False)[0],
                "preview": agent_command.handle_command(command, execute=False, use_llm=False)["answer"],
            }
            for command in SAMPLE_COMMANDS
        ],
        "assistant": {
            "name": "运营 Agent",
            "status": "online",
            "intro": "我在看 Mac mini 最近一次自动化报告。",
        },
        "sources": {
            "agent_pipeline": "outputs/agent_pipeline/daily_automation_guard/latest.json",
            "agent_monitor": "outputs/agent_task_monitor/latest.json",
            "agent_chat": "outputs/agent_chat/latest.json",
        },
    }


def main() -> int:
    payload = build_payload()
    write_json(LATEST_PATH, payload)
    print(f"Agent 手机入口数据已生成：{LATEST_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
