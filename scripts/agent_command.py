from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from atomic_io import atomic_write_text

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "agent_command"
LATEST_PATH = OUTPUT_DIR / "latest.json"
PIPELINE_ID = "daily_automation_guard"

ORDERING_KEYWORDS = ("订货", "下单", "采购", "快驴", "order", "purchase", "kuailv", "inventory_order")
EXECUTE_KEYWORDS = ("执行", "恢复", "处理", "补跑", "修复", "跑一下")
REFRESH_KEYWORDS = ("刷新", "更新", "重新生成")
PUBLISH_KEYWORDS = ("发布", "上线", "同步到云端", "手机入口")
PROBLEM_KEYWORDS = ("问题", "失败", "异常", "坏", "报错")
RERUN_KEYWORDS = ("补跑", "重跑", "恢复")
STATUS_KEYWORDS = ("状态", "怎么样", "情况")


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def command_contains(text: str, keywords: tuple[str, ...]) -> bool:
    lower = text.lower()
    return any(keyword.lower() in lower for keyword in keywords)


def run_command(command: list[str], *, timeout: int = 900) -> dict[str, Any]:
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
        return {
            "command": command,
            "returncode": result.returncode,
            "output_tail": (result.stdout or "")[-4000:],
        }
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        if not isinstance(output, str):
            output = output.decode(errors="replace")
        return {
            "command": command,
            "returncode": 124,
            "output_tail": (output + f"\n命令超时：{timeout} 秒")[-4000:],
        }


def classify_intent(text: str) -> str:
    clean = text.strip()
    if not clean:
        return "help"
    non_ordering_scope = "非订货" in clean or "除了订货" in clean or "不含订货" in clean
    if command_contains(clean, EXECUTE_KEYWORDS) and non_ordering_scope:
        return "execute_non_ordering"
    if command_contains(clean, ORDERING_KEYWORDS):
        return "blocked_ordering"
    if command_contains(clean, PUBLISH_KEYWORDS) and command_contains(clean, ("发布", "上线", "同步到云端")):
        return "publish_mobile"
    if command_contains(clean, EXECUTE_KEYWORDS) and ("其他" in clean):
        return "execute_non_ordering"
    if command_contains(clean, REFRESH_KEYWORDS):
        return "refresh_status"
    if command_contains(clean, RERUN_KEYWORDS):
        return "rerun_plan"
    if command_contains(clean, PROBLEM_KEYWORDS):
        return "problems"
    if command_contains(clean, ("执行 agent", "执行Agent", "执行")):
        return "execution_status"
    if command_contains(clean, STATUS_KEYWORDS):
        return "status"
    return "chat"


def chat_answer(question: str, *, refresh: bool = False) -> str:
    command = [sys.executable or "python3", str(ROOT / "scripts" / "agent_chat.py")]
    if refresh:
        command.append("--refresh")
    command.append(question)
    result = run_command(command, timeout=900)
    output = result["output_tail"].strip()
    return output or f"agent_chat 没有返回内容，退出码 {result['returncode']}。"


def handle_command(text: str, *, execute: bool) -> dict[str, Any]:
    intent = classify_intent(text)
    actions: list[dict[str, Any]] = []
    blocked = False

    if intent == "blocked_ordering":
        blocked = True
        answer = "这个请求属于订货/下单/采购范围。当前 agent 明确不参与订货任务，所以我不会执行，只能报告或等待你另行授权设计订货专用流程。"
    elif intent == "execute_non_ordering":
        if not execute:
            answer = "这是非订货执行请求。为防误触发，请在 Mac mini 上加 `--execute` 执行；不加时我只做意图识别。"
        else:
            action = run_command([sys.executable or "python3", "scripts/agent_pipeline.py", PIPELINE_ID, "--allow-execution"], timeout=1200)
            actions.append(action)
            run_command([sys.executable or "python3", "scripts/build_agent_mobile_status.py"], timeout=300)
            answer = "已执行非订货恢复：执行 Agent 参与了允许的非订货动作，订货/下单/采购仍然排除。"
            if action["returncode"] != 0:
                answer = f"非订货恢复执行失败，退出码 {action['returncode']}。"
    elif intent == "publish_mobile":
        if not execute:
            answer = "这是发布请求。为防误发布，请在 Mac mini 上加 `--execute` 执行；不加时我只做意图识别。"
        else:
            env = {**os.environ, "OPERATION_CLOUD_DEPLOY_MODE": "ui-data"}
            result = subprocess.run(
                ["/bin/zsh", "scripts/deploy_workbench_to_cloud.zsh"],
                cwd=ROOT,
                env=env,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=1200,
            )
            actions.append({"command": ["/bin/zsh", "scripts/deploy_workbench_to_cloud.zsh"], "returncode": result.returncode, "output_tail": (result.stdout or "")[-4000:]})
            answer = "已发布手机入口和工作台数据到云端。" if result.returncode == 0 else f"发布失败，退出码 {result.returncode}。"
    elif intent == "refresh_status":
        if execute:
            action = run_command([sys.executable or "python3", "scripts/agent_pipeline.py", PIPELINE_ID], timeout=900)
            actions.append(action)
            run_command([sys.executable or "python3", "scripts/build_agent_mobile_status.py"], timeout=300)
            answer = "已刷新 agent 状态和手机入口数据。"
        else:
            answer = chat_answer("现在 agent 状态怎么样？", refresh=True)
    elif intent == "rerun_plan":
        answer = chat_answer("哪些任务可以补跑？")
    elif intent == "problems":
        answer = chat_answer("今天哪里有问题？")
    elif intent == "execution_status":
        answer = chat_answer("刚刚跳过的执行 Agent 是谁？")
    elif intent == "status":
        answer = chat_answer("现在 agent 状态怎么样？")
    elif intent == "help":
        answer = "你可以说：今天哪里有问题、刷新状态、执行非订货恢复、发布手机入口、哪些任务可以补跑。订货/下单/采购会被拦截。"
    else:
        answer = chat_answer(text)

    return {
        "generated_at": now_text(),
        "host": socket.gethostname(),
        "command_text": text,
        "intent": intent,
        "execute": bool(execute),
        "blocked": blocked,
        "answer": answer,
        "actions": actions,
        "safety": {
            "ordering_excluded": True,
            "requires_execute_flag_for_mutation": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="自然语言 Agent 命令入口。")
    parser.add_argument("command_text", nargs="*", help="例如：刷新状态 / 执行非订货恢复 / 今天哪里有问题")
    parser.add_argument("--execute", action="store_true", help="允许执行非订货恢复或发布类动作；订货仍然拦截")
    parser.add_argument("--output", default=str(LATEST_PATH), help="输出 JSON 路径")
    args = parser.parse_args()

    text = " ".join(args.command_text).strip()
    payload = handle_command(text, execute=args.execute)
    write_json(Path(args.output).expanduser(), payload)
    print(payload["answer"])
    return 1 if any(action.get("returncode") not in {0, None} for action in payload.get("actions") or []) else 0


if __name__ == "__main__":
    raise SystemExit(main())
