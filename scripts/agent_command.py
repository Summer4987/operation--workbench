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
sys.path.insert(0, str(ROOT / "scripts"))

import agent_notify  # noqa: E402
import agent_llm  # noqa: E402

OUTPUT_DIR = ROOT / "outputs" / "agent_command"
LATEST_PATH = OUTPUT_DIR / "latest.json"
PIPELINE_ID = "daily_automation_guard"
PLAYWRIGHT_PYTHON = ROOT / "business-report-dashboard" / ".venv" / "bin" / "python"

ORDERING_KEYWORDS = ("订货", "下单", "采购", "快驴", "order", "purchase", "kuailv", "inventory_order")
EXECUTE_KEYWORDS = ("执行", "恢复", "处理", "补跑", "修复", "跑一下")
REFRESH_KEYWORDS = ("刷新", "更新", "重新生成")
PUBLISH_KEYWORDS = ("发布", "上线", "同步到云端", "手机入口")
PROBLEM_KEYWORDS = ("问题", "失败", "异常", "坏", "报错")
RERUN_KEYWORDS = ("补跑", "重跑", "恢复")
STATUS_KEYWORDS = ("状态", "怎么样", "情况", "正常", "稳", "顺利", "完成情况", "跑完")
EXECUTION_STATUS_KEYWORDS = ("执行 agent", "执行Agent", "执行 Agent", "4号", "4 号", "跳过的执行", "跳过的是谁")
BUDGET_KEYWORDS = ("预算", "推广预算")
BUDGET_PREVIEW_KEYWORDS = ("预览", "安全计划", "安全检查", "试算", "计划")
BUDGET_RERUN_KEYWORDS = ("重跑", "补跑", "重新", "设置", "初始化")
BUDGET_CONFIRM_KEYWORDS = ("确认执行预算重跑", "确认重跑预算设置", "确认真实提交预算", "确认提交预算")
MEITUAN_SPEND_KEYWORDS = ("美团", "meituan")
SPEND_INSPECTION_KEYWORDS = ("消耗", "花费", "推广花费", "实时消耗", "消耗量", "余量", "剩余", "巡检")
SYSTEM_CHECK_KEYWORDS = ("系统自检", "自检", "健康检查", "检查系统")
ACCEPTANCE_KEYWORDS = ("验收", "同步了吗", "接入了吗", "同步没", "接入没", "功能检查")


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


def browser_python() -> str:
    return str(PLAYWRIGHT_PYTHON) if PLAYWRIGHT_PYTHON.exists() else (sys.executable or "python3")


def classify_intent(text: str) -> str:
    clean = text.strip()
    if not clean:
        return "help"
    non_ordering_scope = "非订货" in clean or "除了订货" in clean or "不含订货" in clean
    if command_contains(clean, EXECUTE_KEYWORDS) and non_ordering_scope:
        return "execute_non_ordering"
    if command_contains(clean, ORDERING_KEYWORDS):
        return "blocked_ordering"
    if command_contains(clean, SYSTEM_CHECK_KEYWORDS):
        return "system_check"
    if command_contains(clean, ACCEPTANCE_KEYWORDS):
        return "feature_acceptance"
    if command_contains(clean, BUDGET_CONFIRM_KEYWORDS):
        return "budget_commit"
    if command_contains(clean, MEITUAN_SPEND_KEYWORDS) and command_contains(clean, SPEND_INSPECTION_KEYWORDS):
        return "meituan_spend_inspection"
    if command_contains(clean, BUDGET_KEYWORDS) and command_contains(clean, BUDGET_PREVIEW_KEYWORDS):
        return "budget_preview"
    if command_contains(clean, BUDGET_KEYWORDS) and command_contains(clean, BUDGET_RERUN_KEYWORDS):
        return "budget_preview"
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
    if command_contains(clean, EXECUTION_STATUS_KEYWORDS):
        return "execution_status"
    if command_contains(clean, STATUS_KEYWORDS):
        return "status"
    return "chat"


def classify_intent_with_llm(text: str, *, use_llm: bool = True) -> tuple[str, dict[str, Any]]:
    clean = text.strip()
    if not clean:
        return "help", {"used": False, "fallback": "empty-command"}

    # Hard safety boundaries stay deterministic and run before any model advice.
    non_ordering_scope = "非订货" in clean or "除了订货" in clean or "不含订货" in clean
    if command_contains(clean, EXECUTE_KEYWORDS) and non_ordering_scope:
        return "execute_non_ordering", {"used": False, "fallback": "hard-non-ordering-scope"}
    if command_contains(clean, ORDERING_KEYWORDS):
        return "blocked_ordering", {"used": False, "fallback": "hard-ordering-block"}
    if command_contains(clean, SYSTEM_CHECK_KEYWORDS):
        return "system_check", {"used": False, "fallback": "hard-system-check"}
    if command_contains(clean, ACCEPTANCE_KEYWORDS):
        return "feature_acceptance", {"used": False, "fallback": "hard-feature-acceptance"}
    if command_contains(clean, BUDGET_CONFIRM_KEYWORDS):
        return "budget_commit", {"used": False, "fallback": "hard-budget-confirmation"}
    if command_contains(clean, MEITUAN_SPEND_KEYWORDS) and command_contains(clean, SPEND_INSPECTION_KEYWORDS):
        return "meituan_spend_inspection", {"used": False, "fallback": "hard-meituan-spend-inspection"}
    if command_contains(clean, BUDGET_KEYWORDS) and command_contains(clean, BUDGET_PREVIEW_KEYWORDS):
        return "budget_preview", {"used": False, "fallback": "hard-budget-preview"}
    if command_contains(clean, REFRESH_KEYWORDS):
        return "refresh_status", {"used": False, "fallback": "hard-refresh-query"}
    if command_contains(clean, EXECUTION_STATUS_KEYWORDS):
        return "execution_status", {"used": False, "fallback": "hard-execution-status-query"}
    if command_contains(clean, STATUS_KEYWORDS):
        return "status", {"used": False, "fallback": "hard-status-query"}

    fallback_intent = classify_intent(clean)
    if not use_llm:
        return fallback_intent, {"used": False, "fallback": "llm-disabled-by-flag"}

    advice = agent_llm.classify(clean)
    if advice.get("used") and float(advice.get("confidence") or 0) >= 0.55:
        intent = str(advice.get("intent") or "")
        if intent in agent_llm.ALLOWED_INTENTS:
            return intent, advice
    advice["fallback_intent"] = fallback_intent
    return fallback_intent, advice


def chat_answer(question: str, *, refresh: bool = False) -> str:
    command = [sys.executable or "python3", str(ROOT / "scripts" / "agent_chat.py")]
    if refresh:
        command.append("--refresh")
    command.append(question)
    result = run_command(command, timeout=900)
    output = result["output_tail"].strip()
    return output or f"agent_chat 没有返回内容，退出码 {result['returncode']}。"


def handle_command(text: str, *, execute: bool, use_llm: bool = True) -> dict[str, Any]:
    intent, llm_record = classify_intent_with_llm(text, use_llm=use_llm)
    actions: list[dict[str, Any]] = []
    blocked = False

    if intent == "blocked_ordering":
        blocked = True
        answer = "这个请求属于订货/下单/采购范围。当前 agent 明确不参与订货任务，所以我不会执行，只能报告或等待你另行授权设计订货专用流程。"
    elif intent == "budget_preview":
        if not execute:
            answer = "这是推广预算重跑请求。我会先跑预算预览/安全计划；为防误触发平台动作，请在 Mac mini 上加 `--execute` 开始预览。真实提交预算还需要说：确认执行预算重跑。"
        else:
            action = run_command(["/bin/zsh", "scripts/run_current_budget.zsh", "--period", "auto", "--mode", "preview"], timeout=3600)
            actions.append(action)
            run_command([sys.executable or "python3", "scripts/build_agent_mobile_status.py"], timeout=300)
            if action["returncode"] == 0:
                answer = "已开始并完成推广预算预览/安全计划；这次没有真实提交预算。"
            else:
                answer = f"推广预算预览/安全计划失败，退出码 {action['returncode']}。"
    elif intent == "budget_commit":
        if not execute:
            answer = "你已说出预算确认语。真实提交预算需要在 Mac mini 上加 `--execute`，并且脚本仍会检查当前是否在允许时间窗口。"
        else:
            action = run_command(["/bin/zsh", "scripts/run_current_budget.zsh", "--period", "auto", "--mode", "commit"], timeout=3600)
            actions.append(action)
            run_command([sys.executable or "python3", "scripts/build_agent_mobile_status.py"], timeout=300)
            if action["returncode"] == 0:
                answer = "已执行推广预算真实提交流程，并刷新 agent 状态。"
            else:
                answer = f"推广预算真实提交没有完成，退出码 {action['returncode']}；可能被时间窗口、登录态或安全闸拦截。"
    elif intent == "meituan_spend_inspection":
        if not execute:
            answer = "这是美团推广实时消耗只读巡检。它不会改预算、出价或投放开关；需要在 Mac mini 上加 `--execute` 才会打开后台读取页面。"
        else:
            action = run_command(
                [browser_python(), "scripts/meituan_promo_spend_query.py", "--period", "all", "--quiet"],
                timeout=1200,
            )
            actions.append(action)
            answer = action["output_tail"].strip() or f"美团推广消耗巡检没有返回内容，退出码 {action['returncode']}。"
    elif intent == "system_check":
        command = [sys.executable or "python3", "scripts/agent_system_check.py", "--mode", "system"]
        action = run_command(command, timeout=180)
        actions.append(action)
        answer = action["output_tail"].strip() or f"系统自检没有返回内容，退出码 {action['returncode']}。"
    elif intent == "feature_acceptance":
        store = "望京" if "望京" in text else ""
        command = [sys.executable or "python3", "scripts/agent_system_check.py", "--mode", "feature"]
        if store:
            command.extend(["--store", store])
        action = run_command(command, timeout=180)
        actions.append(action)
        answer = action["output_tail"].strip() or f"功能验收没有返回内容，退出码 {action['returncode']}。"
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
        run_command([sys.executable or "python3", "scripts/agent_task_monitor.py"], timeout=300)
        command = [sys.executable or "python3", "scripts/agent_rerun_dry_run.py"]
        if execute:
            command.append("--execute")
        action = run_command(command, timeout=1800)
        actions.append(action)
        run_command([sys.executable or "python3", "scripts/build_agent_mobile_status.py"], timeout=300)
        answer = action["output_tail"].strip() or f"补跑计划没有返回内容，退出码 {action['returncode']}。"
    elif intent == "problems":
        answer = chat_answer("今天哪里有问题？")
    elif intent == "execution_status":
        answer = chat_answer("刚刚跳过的执行 Agent 是谁？")
    elif intent == "status":
        answer = chat_answer("现在 agent 状态怎么样？")
    elif intent == "help":
        answer = "你可以说：今天哪里有问题、刷新状态、巡检美团消耗、执行非订货恢复、发布手机入口、哪些任务可以补跑。订货/下单/采购会被拦截。"
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
        "llm": {
            "enabled": bool(use_llm),
            "used": bool(llm_record.get("used")),
            "provider": llm_record.get("provider", ""),
            "model": llm_record.get("model", ""),
            "intent": llm_record.get("intent", ""),
            "confidence": llm_record.get("confidence", 0),
            "reason": llm_record.get("reason", ""),
            "fallback": llm_record.get("fallback", ""),
            "fallback_intent": llm_record.get("fallback_intent", ""),
            "error": llm_record.get("error", ""),
        },
        "safety": {
            "ordering_excluded": True,
            "requires_execute_flag_for_mutation": True,
            "llm_advisory_only": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="自然语言 Agent 命令入口。")
    parser.add_argument("command_text", nargs="*", help="例如：刷新状态 / 执行非订货恢复 / 今天哪里有问题")
    parser.add_argument("--execute", action="store_true", help="允许执行非订货恢复或发布类动作；订货仍然拦截")
    parser.add_argument("--notify", action="store_true", help="把本次 agent 命令结果发送到企业微信/通知通道")
    parser.add_argument("--notify-on-problem", action="store_true", help="仅在失败、拦截或执行动作时发送通知")
    parser.add_argument("--notify-dry-run", action="store_true", help="只生成通知内容，不实际发送")
    parser.add_argument("--no-llm", action="store_true", help="禁用大模型意图识别，强制使用本地关键词规则")
    parser.add_argument("--output", default=str(LATEST_PATH), help="输出 JSON 路径")
    args = parser.parse_args()

    text = " ".join(args.command_text).strip()
    payload = handle_command(text, execute=args.execute, use_llm=not args.no_llm)
    should_notify = args.notify or (
        args.notify_on_problem
        and (
            payload.get("blocked")
            or bool(payload.get("actions"))
            or any(action.get("returncode") not in {0, None} for action in payload.get("actions") or [])
        )
    )
    if should_notify:
        payload["notification"] = agent_notify.send_command_notification(payload, dry_run=args.notify_dry_run)
    write_json(Path(args.output).expanduser(), payload)
    print(payload["answer"])
    return 1 if any(action.get("returncode") not in {0, None} for action in payload.get("actions") or []) else 0


if __name__ == "__main__":
    raise SystemExit(main())
