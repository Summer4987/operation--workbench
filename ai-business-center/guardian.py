#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import center


CENTER_ROOT = Path(__file__).resolve().parent
REPO_ROOT = CENTER_ROOT.parent
STATE_DIR = CENTER_ROOT / "state"
REPORT_DIR = STATE_DIR / "reports"


STATUS_LABELS = {
    "ok": "正常",
    "stale": "过旧",
    "missing_evidence": "缺产物",
    "invalid_evidence": "产物异常",
    "partial_evidence": "部分成功",
    "broken": "命令缺失",
    "planned": "待接入",
}


def load_operation_check_module():
    path = REPO_ROOT / "operation_automation_check.py"
    spec = importlib.util.spec_from_file_location("operation_automation_check", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载体检脚本：{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["operation_automation_check"] = module
    spec.loader.exec_module(module)
    return module


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)


def count_statuses(tasks: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for task in tasks:
        counts[task["status"]] = counts.get(task["status"], 0) + 1
    return counts


def issue_hint(text: str) -> str:
    lowered = text.lower()
    if "屏幕录制" in text or "screencapture" in lowered or "display" in lowered:
        return "到 Mac mini 的系统设置里检查屏幕录制权限，确认 Terminal、Codex、Chrome 已允许。"
    if "辅助功能" in text or "system events" in lowered:
        return "到隐私与安全性里检查辅助功能权限，确认 Terminal、Codex、Chrome 已允许。"
    if "playwright" in lowered:
        return "检查脚本是否使用包含 Playwright 的 Python 环境，优先复用 business-report-dashboard/.venv。"
    if "chrome" in lowered or "9222" in lowered or "cdp" in lowered:
        return "检查日常 Chrome 是否以调试端口启动，并确认 127.0.0.1:9222 可访问。"
    if "ssh" in lowered or "rsync" in lowered or "permission denied" in lowered:
        return "检查云服务器 SSH key、网络和远端目录权限。"
    if "登录" in text or "验证码" in text or "安全验证" in text:
        return "需要人工打开平台页面处理登录、验证码或安全验证后再继续。"
    if "没有生成" in text or "缺少" in text or "missing" in lowered:
        return "检查对应任务是否真实执行，并确认产物路径和生成时间。"
    return "查看该任务日志和产物内容，确认是否需要人工处理。"


def collect_task_issues(health: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for task in health["tasks"]:
        status = task["status"]
        if status in {"ok", "planned"}:
            continue
        bad_evidence = [item for item in task["evidence"] if item["status"] != "ok"]
        if not bad_evidence:
            issues.append(
                {
                    "task": task["name"],
                    "task_id": task["id"],
                    "status": status,
                    "message": status_label(status),
                    "hint": issue_hint(status),
                }
            )
            continue
        messages = [f"{item['path']}：{item['message']}" for item in bad_evidence]
        combined = "；".join(messages)
        issues.append(
            {
                "task": task["name"],
                "task_id": task["id"],
                "status": status,
                "message": combined,
                "hint": issue_hint(combined),
            }
        )
    return issues


def run_guardian() -> dict[str, Any]:
    health = center.build_health()
    center.render_dashboard(health)
    operation_check = load_operation_check_module().build_report()
    task_issues = collect_task_issues(health)
    counts = count_statuses(health["tasks"])
    ok = operation_check.get("ok", False) and not task_issues
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "production_root": str(center.ROOT),
        "dashboard_path": str(center.DASHBOARD_PATH),
        "health_path": str(center.STATE_DIR / "health.json"),
        "ok": ok,
        "status_counts": counts,
        "operation_check": operation_check,
        "task_issues": task_issues,
    }


def render_markdown(report: dict[str, Any]) -> str:
    counts = report["status_counts"]
    count_text = "，".join(f"{status_label(key)} {value}" for key, value in sorted(counts.items()))
    lines = [
        "# Mac mini 自动化守护报告",
        "",
        f"- 生成时间：{report['generated_at']}",
        f"- 生产目录：`{report['production_root']}`",
        f"- 总体状态：{'正常' if report['ok'] else '需要处理'}",
        f"- 任务状态：{count_text or '暂无任务'}",
        f"- 状态页：`{report['dashboard_path']}`",
        "",
        "## 系统体检",
        "",
    ]

    operation_check = report["operation_check"]
    blockers = operation_check.get("blockers", [])
    warnings = operation_check.get("warnings", [])
    if not blockers and not warnings:
        lines.append("- 无阻塞项，无警告。")
    for issue in blockers:
        lines.append(f"- 阻塞：{issue['category']} - {issue['message']}")
    for issue in warnings:
        lines.append(f"- 警告：{issue['category']} - {issue['message']}")

    lines.extend(["", "## 任务异常", ""])
    if not report["task_issues"]:
        lines.append("- 当前无任务异常。")
    else:
        for issue in report["task_issues"]:
            lines.extend(
                [
                    f"### {issue['task']}",
                    "",
                    f"- 任务：`{issue['task_id']}`",
                    f"- 状态：{status_label(issue['status'])}",
                    f"- 现象：{issue['message']}",
                    f"- 建议：{issue['hint']}",
                    "",
                ]
            )

    planned = [task for task in center.build_health()["tasks"] if task["status"] == "planned"]
    if planned:
        lines.extend(["", "## 待接入中心", ""])
        for task in planned:
            lines.append(f"- {task['name']}：{task['description']}")
    lines.append("")
    return "\n".join(lines)


def write_reports(report: dict[str, Any]) -> tuple[Path, Path]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = REPORT_DIR / f"{stamp}.json"
    md_path = REPORT_DIR / f"{stamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def maybe_notify(title: str, message: str) -> None:
    if os.environ.get("OPERATION_GUARDIAN_NOTIFY") != "1":
        return
    subprocess.run(
        ["osascript", "-e", f'display notification "{message}" with title "{title}"'],
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Mac mini 自动化守护器")
    parser.add_argument("--json", action="store_true", help="同时把报告 JSON 打印到终端")
    parser.add_argument(
        "--strict-exit",
        action="store_true",
        help="报告发现异常时返回 1；默认只在脚本运行失败时返回非 0，避免 launchd 误判。",
    )
    args = parser.parse_args()

    report = run_guardian()
    json_path, md_path = write_reports(report)
    status = "正常" if report["ok"] else "需要处理"
    print(f"守护报告：{status}")
    print(f"Markdown：{md_path}")
    print(f"JSON：{json_path}")
    print(f"状态页：{report['dashboard_path']}")
    if report["task_issues"]:
        print("异常任务：")
        seen = set()
        for issue in report["task_issues"]:
            key = (issue["task_id"], issue["status"])
            if key in seen:
                continue
            seen.add(key)
            print(f"- {issue['task']}：{status_label(issue['status'])}")
    maybe_notify("Mac mini 自动化守护", status)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.strict_exit and not report["ok"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
