#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import Any

import center


HEALTH_PATH = center.STATE_DIR / "health.json"
ALIASES_PATH = center.CENTER_ROOT / "config" / "business_aliases.json"
ROOT = center.ROOT
MONITOR_OUTPUT_PATH = ROOT / "outputs" / "agent_task_monitor" / "latest.txt"
BAD_STATUSES = {
    "broken",
    "invalid_evidence",
    "missing_evidence",
    "partial_evidence",
    "stale",
}
STATUS_HINTS = {
    "broken": "命令或脚本路径需要先修复",
    "invalid_evidence": "产物存在但内容异常，优先看最近日志",
    "missing_evidence": "缺少关键产物，优先确认任务是否触发",
    "partial_evidence": "部分产物成功，先核对缺失环节",
    "stale": "产物过旧，先跑只读健康检查或预览",
    "planned": "还在规划接入，不能自动执行",
    "ok": "正常",
}
STATUS_WORDS = {
    "状态",
    "怎么样",
    "情况",
    "正常吗",
    "是否正常",
    "有没有问题",
    "健康",
    "检查",
    "巡检",
}
AUTOMATION_WORDS = {
    "失败",
    "报错",
    "错误",
    "异常",
    "补跑",
    "自动化",
    "任务报告",
    "失败报告",
    "今早",
    "早上",
    "今天任务",
}
FINANCE_WORDS = {
    "财务",
    "记账",
    "入账",
    "收入",
    "支出",
    "付款",
    "收款",
    "采购",
    "报销",
    "转账",
    "发票",
    "账单",
    "押金",
    "租金",
    "工资",
}
FILE_WORDS = {
    "桌面",
    "下载",
    "文件",
    "表格",
    "excel",
    "xlsx",
    "csv",
    "word",
    "pdf",
    "修改",
    "编辑",
    "整理",
    "汇总",
    "回传",
    "发给我",
}
HELP_WORDS = {
    "你能做什么",
    "能做什么",
    "怎么用",
    "帮助",
    "命令",
    "不会用",
    "记不住",
}


def normalize_alias(value: str) -> str:
    return "".join(value.strip().lower().split())


def normalized_contains(text: str, choices: set[str]) -> bool:
    normalized = normalize_alias(text)
    return any(normalize_alias(choice) in normalized for choice in choices)


def looks_like_finance_entry(text: str) -> bool:
    if not normalized_contains(text, FINANCE_WORDS):
        return False
    has_amount = bool(re.search(r"\d+(?:\.\d+)?\s*(?:元|块|rmb|人民币)?", text, flags=re.IGNORECASE))
    has_direction = normalized_contains(text, {"收入", "支出", "付款", "收款", "采购", "报销", "转账", "记一笔", "记账"})
    return has_amount or has_direction


def run_checked(command: list[str]) -> str:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = completed.stdout.strip()
    if completed.returncode != 0:
        return output or f"命令执行失败，退出码 {completed.returncode}。"
    return output


def load_aliases() -> dict[str, Any]:
    if not ALIASES_PATH.exists():
        return {"task_aliases": {}, "business_terms": []}
    return json.loads(ALIASES_PATH.read_text(encoding="utf-8"))


def load_or_build_health(refresh: bool) -> dict[str, Any]:
    if refresh or not HEALTH_PATH.exists():
        return center.build_health()
    return json.loads(HEALTH_PATH.read_text(encoding="utf-8"))


def status_counts(tasks: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for task in tasks:
        status = task["status"]
        counts[status] = counts.get(status, 0) + 1
    return counts


def first_evidence_issue(task: dict[str, Any]) -> str:
    for item in task.get("evidence", []):
        if item.get("status") != "ok":
            return f"{item.get('path', '未知产物')}：{item.get('message', item.get('status', '异常'))}"
    blockers = task.get("blockers") or []
    if blockers:
        return "可能阻塞：" + "、".join(blockers[:4])
    return "暂无细分原因"


def task_line(task: dict[str, Any]) -> str:
    status = center.status_badge(task["status"])
    hint = STATUS_HINTS.get(task["status"], "需要人工确认")
    issue = first_evidence_issue(task)
    return f"- {task['name']}（{task['id']}）：{status}。{issue}。建议：{hint}。"


def build_snapshot(refresh: bool) -> dict[str, Any]:
    health = load_or_build_health(refresh)
    tasks = health["tasks"]
    counts = status_counts(tasks)
    abnormal = [task for task in tasks if task["status"] in BAD_STATUSES]
    planned = [task for task in tasks if task["status"] == "planned"]
    return {
        "generated_at": health["generated_at"],
        "root": health["root"],
        "counts": counts,
        "abnormal": abnormal,
        "planned": planned,
        "tasks": tasks,
    }


def format_status(snapshot: dict[str, Any], *, limit: int) -> str:
    counts_text = "、".join(
        f"{center.status_badge(status)} {count}"
        for status, count in sorted(snapshot["counts"].items())
    )
    lines = [
        "AI 业务中心状态",
        f"生成时间：{snapshot['generated_at']}",
        f"任务概况：{counts_text or '暂无任务'}",
    ]
    abnormal = snapshot["abnormal"]
    if abnormal:
        lines.append(f"异常/待处理：{len(abnormal)} 个")
        lines.extend(task_line(task) for task in abnormal[:limit])
        if len(abnormal) > limit:
            lines.append(f"- 还有 {len(abnormal) - limit} 个异常任务，发送“任务列表”查看。")
    else:
        lines.append("异常/待处理：0 个。")
    lines.append("安全边界：这里只读检查和预览，不自动执行预算、出价、订货、发布等高风险动作。")
    return "\n".join(lines)


def find_task(snapshot: dict[str, Any], task_id_or_name: str) -> dict[str, Any] | None:
    needle = task_id_or_name.strip().lower()
    normalized_needle = normalize_alias(task_id_or_name)
    aliases = load_aliases().get("task_aliases", {})
    for task_id, names in aliases.items():
        alias_values = [task_id, *names]
        if normalized_needle in {normalize_alias(str(value)) for value in alias_values}:
            for task in snapshot["tasks"]:
                if task["id"] == task_id:
                    return task
    for task in snapshot["tasks"]:
        if task["id"].lower() == needle or task["name"].lower() == needle:
            return task
    for task in snapshot["tasks"]:
        if needle in task["id"].lower() or needle in task["name"].lower():
            return task
    return None


def find_business_term(task_id_or_name: str) -> dict[str, Any] | None:
    normalized_needle = normalize_alias(task_id_or_name)
    for term in load_aliases().get("business_terms", []):
        values = [term.get("name", ""), *term.get("aliases", [])]
        if normalized_needle in {normalize_alias(str(value)) for value in values}:
            return term
    for term in load_aliases().get("business_terms", []):
        values = [term.get("name", ""), *term.get("aliases", [])]
        if any(normalized_needle in normalize_alias(str(value)) for value in values):
            return term
    return None


def find_task_or_term_from_text(snapshot: dict[str, Any], text: str) -> tuple[str, dict[str, Any]] | None:
    normalized_text = normalize_alias(text)
    aliases = load_aliases().get("task_aliases", {})
    for task_id, names in aliases.items():
        for value in [task_id, *names]:
            if normalize_alias(str(value)) in normalized_text:
                for task in snapshot["tasks"]:
                    if task["id"] == task_id:
                        return "task", task
    for task in snapshot["tasks"]:
        if normalize_alias(task["name"]) in normalized_text or normalize_alias(task["id"]) in normalized_text:
            return "task", task
    for term in load_aliases().get("business_terms", []):
        values = [term.get("name", ""), *term.get("aliases", [])]
        for value in values:
            if value and normalize_alias(str(value)) in normalized_text:
                return "term", term
    return None


def format_task_detail(task: dict[str, Any]) -> str:
    lines = [
        f"{task['name']}（{task['id']}）",
        f"状态：{center.status_badge(task['status'])}",
        f"风险：{task.get('risk', 'unknown')}；模式：{task.get('mode', 'unknown')}",
        f"说明：{task.get('description') or '无'}",
    ]
    evidence = task.get("evidence") or []
    if evidence:
        lines.append("产物：")
        for item in evidence:
            lines.append(
                f"- {center.status_badge(item.get('status', 'unknown'))} "
                f"{item.get('path', '未知路径')}：{item.get('message', '')}"
            )
    blockers = task.get("blockers") or []
    if blockers:
        lines.append("可能阻塞：" + "、".join(blockers))
    lines.append("建议：" + STATUS_HINTS.get(task["status"], "先做只读检查，再决定是否人工执行。"))
    return "\n".join(lines)


def format_business_term(term: dict[str, Any]) -> str:
    lines = [
        f"{term.get('name', '业务简称')}",
        f"中心：{term.get('center', 'unknown')}；风险：{term.get('risk', 'unknown')}",
    ]
    if term.get("status"):
        lines.append(f"状态：{term['status']}")
    if term.get("url"):
        lines.append(f"链接：{term['url']}")
    if term.get("command"):
        lines.append(f"安全命令：{term['command']}")
    aliases = term.get("aliases") or []
    if aliases:
        lines.append("可识别简称：" + "、".join(aliases))
    if term.get("safe_note"):
        lines.append("安全边界：" + term["safe_note"])
    return "\n".join(lines)


def format_task_list(snapshot: dict[str, Any]) -> str:
    lines = ["任务列表"]
    for task in snapshot["tasks"]:
        aliases = load_aliases().get("task_aliases", {}).get(task["id"], [])
        alias_text = f"；简称：{'、'.join(aliases[:5])}" if aliases else ""
        lines.append(f"- {task['id']}：{center.status_badge(task['status'])}，{task['name']}{alias_text}")
    return "\n".join(lines)


def format_aliases() -> str:
    aliases = load_aliases()
    lines = ["业务简称表"]
    for task_id, names in aliases.get("task_aliases", {}).items():
        lines.append(f"- {task_id}：{'、'.join(names)}")
    for term in aliases.get("business_terms", []):
        lines.append(f"- {term.get('name')}：{'、'.join(term.get('aliases', []))}")
    return "\n".join(lines)


def format_commands() -> str:
    return "\n".join(
        [
            "Hermes 可用业务命令",
            "你不需要记命令，可以直接说自然语言，例如“今早自动化为什么失败了”“帮我记一笔 128 元采购”“桌面那个表格帮我汇总”。",
            "状态：查看 AI 业务中心摘要",
            "任务列表：查看全部登记任务",
            "任务 <任务ID/名称>：查看单个任务详情",
            "简称：查看业务简称表",
            "只读健康检查：刷新健康状态，不执行平台写操作",
            "高风险动作默认不执行；预算、出价、订货、发布需要你明确确认。",
        ]
    )


def format_natural_help() -> str:
    return "\n".join(
        [
            "不用记任务类型，直接按人话说就行。",
            "我会先判断你是在说：Mac mini 自动化、财务记录、订货/推广、文件表格处理，还是普通问题。",
            "例子：",
            "- 今早自动化有没有失败？失败原因是什么？",
            "- 帮我记一笔：万象城采购原料 128 元，微信支付。",
            "- 桌面最新的表格帮我按门店汇总，生成新文件发我。",
            "- 快驴今天按缺货清单给我做订货预览。",
            "安全边界：订货、出价、财务正式入账、云端发布默认只做预览或草稿，等你确认才执行。",
        ]
    )


def format_file_task_guidance(text: str) -> str:
    return "\n".join(
        [
            "我理解这是私人文件/表格任务。",
            "接下来要走 HermesPrivate 工作区：先复制原文件，再生成处理后的新文件，不覆盖原件。",
            "当前安全做法：请把文件放到 Mac mini 的桌面、下载目录或 ~/HermesPrivate/inbox/，然后直接说要处理哪个文件和怎么处理。",
            f"我收到的任务描述：{text}",
            "下一步需要接入文件处理器和微信附件回传；在这之前，我不会擅自修改桌面原文件。",
        ]
    )


def route_natural_text(text: str, *, limit: int) -> str:
    stripped = text.strip()
    if not stripped:
        return format_commands()

    if normalized_contains(stripped, HELP_WORDS):
        return format_natural_help()

    if looks_like_finance_entry(stripped):
        return run_checked(
            [
                sys.executable,
                "scripts/finance_inbox.py",
                "intake",
                "--operator",
                "hermes-weixin",
                "--text",
                stripped,
            ]
        )

    if normalized_contains(stripped, {"财务草稿", "待确认财务", "待确认的财务", "我记了什么账"}):
        return run_checked([sys.executable, "scripts/finance_inbox.py", "list-drafts"])

    if normalized_contains(stripped, AUTOMATION_WORDS):
        output = run_checked([sys.executable, "scripts/agent_task_monitor.py"])
        if MONITOR_OUTPUT_PATH.exists():
            latest = MONITOR_OUTPUT_PATH.read_text(encoding="utf-8").strip()
            return latest or output
        return output

    snapshot = build_snapshot(refresh=True)
    matched = find_task_or_term_from_text(snapshot, stripped)
    if matched is not None:
        kind, item = matched
        if kind == "task":
            return format_task_detail(item)
        return format_business_term(item)

    if normalized_contains(stripped, FILE_WORDS):
        return format_file_task_guidance(stripped)

    if normalized_contains(stripped, STATUS_WORDS):
        return format_status(snapshot, limit=limit)

    return "\n".join(
        [
            "我没完全识别这句话对应哪个系统任务。",
            "你不用改成固定命令，可以换成更自然但具体一点的说法，比如：查今天自动化、记一笔支出、处理桌面表格、快驴订货预览、推广出价建议。",
            "如果是高风险动作，我会先给预览或草稿，不会直接执行。",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Hermes/微信可调用的 AI 业务中心只读桥接入口")
    parser.add_argument("--json", action="store_true", help="输出 JSON 快照")
    parser.add_argument("--no-refresh", action="store_true", help="复用已有 health.json，不重新检查产物")
    parser.add_argument("--limit", type=int, default=6, help="状态摘要中最多展示的异常任务数")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="输出微信可读的业务状态摘要")
    sub.add_parser("list", help="输出任务列表")
    task_parser = sub.add_parser("task", help="输出单个任务详情")
    task_parser.add_argument("task_id_or_name")
    sub.add_parser("commands", help="输出 Hermes 可用命令说明")
    sub.add_parser("aliases", help="输出业务简称表")
    route_parser = sub.add_parser("route", help="按自然语言自动判断 Hermes 应该调用什么能力")
    route_parser.add_argument("text", nargs="+")

    args = parser.parse_args()
    if args.command == "commands":
        print(format_commands())
        return 0
    if args.command == "aliases":
        print(format_aliases())
        return 0
    if args.command == "route":
        print(route_natural_text(" ".join(args.text), limit=args.limit))
        return 0

    snapshot = build_snapshot(refresh=not args.no_refresh)
    if args.json:
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
        return 0

    if args.command == "status":
        print(format_status(snapshot, limit=args.limit))
        return 0
    if args.command == "list":
        print(format_task_list(snapshot))
        return 0
    if args.command == "task":
        task = find_task(snapshot, args.task_id_or_name)
        if task is not None:
            print(format_task_detail(task))
            return 0
        term = find_business_term(args.task_id_or_name)
        if term is not None:
            print(format_business_term(term))
            return 0
        else:
            print(f"没有找到任务或业务简称：{args.task_id_or_name}")
            return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
