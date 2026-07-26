from __future__ import annotations

import argparse
import csv
import json
import re
import socket
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from atomic_io import atomic_write_text


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import agent_llm  # noqa: E402

PIPELINE_ID = "daily_automation_guard"
PIPELINE_PATH = ROOT / "outputs" / "agent_pipeline" / PIPELINE_ID / "latest.json"
MONITOR_PATH = ROOT / "outputs" / "agent_task_monitor" / "latest.json"
TASK_RUNS_PATH = ROOT / "outputs" / "task_runs" / "latest.json"
DIRECT_DAILY_PATH = ROOT / "business-report-dashboard" / "data" / "direct_unified_daily.csv"
OUTPUT_DIR = ROOT / "outputs" / "agent_chat"

TRACKED_TASKS = [
    ("ops.morning_collection", "上午运营一键采集", "上午主流程"),
    ("ops.realtime_order_income", "加盟店实时数据采集", "实时采集"),
    ("growth.promo_budget", "下午/晚餐推广预算设置", "推广预算"),
    ("agents.daily_automation_guard", "Agent 守护巡检", "Agent"),
]


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_text() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def date_for_question(question: str) -> str:
    if "昨天" in question:
        return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    if "前天" in question:
        return (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    return today_text()


def read_json(path: Path, fallback: Any) -> Any:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if payload is not None else fallback
    except Exception:
        return fallback


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    except Exception:
        return []


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
    text = text.replace("\n", " ")
    if "\\x" in text:
        text = re.sub(r"关键日志[:：][^。；]*", "关键日志已省略", text)
        text = re.sub(r"(?:\\x[0-9a-fA-F]{2})+", "", text)
    text = " ".join(text.split())
    return text[:180].rstrip("。.")


def date_part(value: Any) -> str:
    return str(value or "").strip()[:10]


def time_part(value: Any) -> str:
    text = str(value or "").strip()
    return text[11:16] if len(text) >= 16 else text


def comparable_time(value: Any) -> str:
    return str(value or "").strip()


def task_run_details(task: dict[str, Any]) -> str:
    message = compact_reason(task.get("message"), fallback="")
    extra = task.get("extra") if isinstance(task.get("extra"), dict) else {}
    details_text = str(extra.get("failure_details") or "").strip()
    if details_text:
        try:
            details = json.loads(details_text)
        except Exception:
            details = []
        if isinstance(details, list) and details:
            first = next((item for item in details if isinstance(item, dict)), {})
            if first:
                name = str(first.get("name") or first.get("step") or "").strip()
                tail = compact_reason(first.get("output_tail"), fallback="")
                detail_message = compact_reason(first.get("message"), fallback="")
                pieces = [part for part in (name, detail_message, tail) if part]
                if pieces:
                    return "；".join(pieces)[:260]
    return message


def event_details(event: dict[str, Any]) -> str:
    message = compact_reason(event.get("message"), fallback="")
    tail = compact_reason((event.get("extra") or {}).get("output_tail") if isinstance(event.get("extra"), dict) else "", fallback="")
    return tail or message


def task_status_label(status: str) -> str:
    return {
        "success": "成功",
        "failed": "失败",
        "running": "运行中",
        "skipped": "跳过",
    }.get(status, status or "未记录")


def tracked_task_action(task_id: str, status: str, run_date: str, target_date: str) -> str:
    if run_date != target_date:
        return "不算今天失败；先刷新状态或等计划时间运行"
    if status == "success":
        return "无需处理"
    if status == "running":
        return "等待结束后复核"
    if status == "failed":
        if task_id == "ops.realtime_order_income":
            return "低风险，可自动补跑"
        if task_id in {"ops.morning_collection", "growth.promo_budget"}:
            return "高风险，需人工确认，不自动补跑"
        return "先看日志，再决定是否补跑"
    return "先确认是否符合预期"


def task_runs_generated_date(task_runs: dict[str, Any]) -> str:
    return date_part(task_runs.get("generated_at")) if isinstance(task_runs, dict) else ""


def is_task_runs_stale_for_date(task_runs: dict[str, Any], target_date: str) -> bool:
    generated_date = task_runs_generated_date(task_runs)
    return bool(generated_date and generated_date != target_date)


def stale_task_runs_notice(task_runs: dict[str, Any], target_date: str) -> str:
    generated_at = str(task_runs.get("generated_at") or "未知时间") if isinstance(task_runs, dict) else "未知时间"
    title_date = "今天" if target_date == today_text() else target_date
    return (
        f"数据源过期：{title_date}的任务账本还没有刷新。"
        f"当前 task_runs/latest.json 最后更新时间是 {generated_at}，所以我不能把里面的旧失败当成{title_date}的问题。"
    )


def tracked_task_line(
    index: int,
    task_id: str,
    name: str,
    section: str,
    task: dict[str, Any],
    target_date: str,
    *,
    include_stale_reason: bool = True,
) -> str:
    if not task:
        return f"{index}. {name}：今日未记录。分组：{section}。处理：先刷新状态或等计划时间运行。"
    updated = str(task.get("updated_at") or task.get("finished_at") or "")
    status = str(task.get("status") or "")
    run_date = date_part(updated)
    when = time_part(updated)
    step = str(task.get("step") or "")
    detail = task_run_details(task)
    if run_date == target_date:
        line = f"{index}. {name}：{task_status_label(status)}"
        if when:
            line += f"（{when}）"
        if step:
            line += f"，步骤：{step}"
        if status != "success" and detail:
            line += f"。原因：{detail}"
        elif detail:
            line += f"。说明：{detail}"
        evidence = task.get("log_path") or ""
        if status != "success" and evidence:
            line += f"。证据：{evidence}"
        line += f"。处理：{tracked_task_action(task_id, status, run_date, target_date)}"
        return line
    stale_text = "今日未运行"
    if target_date != today_text():
        stale_text = f"{target_date} 未记录"
    line = f"{index}. {name}：{stale_text}"
    if run_date:
        line += f"；最近一次 {run_date} {when} 是{task_status_label(status)}"
    if include_stale_reason and status != "success" and detail:
        line += f"。最近原因：{detail}"
    elif include_stale_reason and detail:
        line += f"。最近说明：{detail}"
    line += f"。处理：{tracked_task_action(task_id, status, run_date, target_date)}"
    return line


def latest_task_event_on_date(task_runs: dict[str, Any], task_id: str, target_date: str) -> dict[str, Any]:
    events = task_runs.get("events") if isinstance(task_runs.get("events"), list) else []
    matches = [
        event
        for event in events
        if isinstance(event, dict)
        and event.get("task_id") == task_id
        and date_part(event.get("created_at")) == target_date
        and str(event.get("status") or "") in {"success", "failed", "running", "skipped"}
    ]
    return matches[-1] if matches else {}


def task_from_event(event: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    if not event:
        return fallback
    return {
        **fallback,
        "task_id": event.get("task_id") or fallback.get("task_id"),
        "status": event.get("status"),
        "message": event.get("message") or fallback.get("message"),
        "step": event.get("step") or fallback.get("step"),
        "log_path": event.get("log_path") or fallback.get("log_path"),
        "returncode": event.get("returncode"),
        "failure_type": event.get("failure_type") or fallback.get("failure_type"),
        "updated_at": event.get("created_at") or fallback.get("updated_at"),
        "finished_at": event.get("created_at") or fallback.get("finished_at"),
    }


def build_daily_task_runs_report(task_runs: dict[str, Any], monitor: dict[str, Any], question: str) -> str:
    target_date = date_for_question(question)
    is_today_report = target_date == today_text()
    stale_for_target = is_today_report and is_task_runs_stale_for_date(task_runs, target_date)
    tasks = task_runs.get("tasks") if isinstance(task_runs.get("tasks"), dict) else {}
    today_rows = []
    today_failed = 0
    today_success = 0
    today_running = 0
    today_missing = 0
    for index, (task_id, name, section) in enumerate(TRACKED_TASKS, start=1):
        latest_task = tasks.get(task_id) if isinstance(tasks.get(task_id), dict) else {}
        task = task_from_event(latest_task_event_on_date(task_runs, task_id, target_date), latest_task)
        if task and date_part(task.get("updated_at") or task.get("finished_at")) == target_date:
            status = str(task.get("status") or "")
            today_success += 1 if status == "success" else 0
            today_failed += 1 if status == "failed" else 0
            today_running += 1 if status == "running" else 0
        else:
            today_missing += 1
        today_rows.append(
            tracked_task_line(
                index,
                task_id,
                name,
                section,
                task,
                target_date,
                include_stale_reason=not is_today_report,
            )
        )

    title_date = "今天" if target_date == today_text() else target_date
    lines = [f"{title_date}任务状态 / 值班报告："]
    if stale_for_target:
        lines.append(stale_task_runs_notice(task_runs, target_date))
    failure_word = "今日" if target_date == today_text() else "当天"
    if today_failed:
        lines.append(f"结论：有 {today_failed} 个{failure_word}失败项；成功 {today_success} 项，未运行/未记录 {today_missing} 项。")
    elif today_running:
        lines.append(f"结论：没有{failure_word}失败项，有 {today_running} 项运行中；成功 {today_success} 项，未运行/未记录 {today_missing} 项。")
    else:
        lines.append(f"结论：没有{failure_word}失败项；成功 {today_success} 项，未运行/未记录 {today_missing} 项。")
    lines.append("任务清单：")
    lines.extend(today_rows)

    if target_date == today_text() and today_missing:
        lines.append("说明：未运行不等于失败，下午/晚餐预算、晚间实时采集等任务未到时间时会显示未运行。")

    monitor_summary = monitor.get("summary") if isinstance(monitor.get("summary"), dict) else {}
    if monitor_summary:
        monitor_failed = int(monitor_summary.get("failed") or 0)
        monitor_attention = int(monitor_summary.get("attention") or 0)
        if is_today_report and not today_failed and (monitor_failed or monitor_attention):
            lines.append(
                "透明化报告："
                f"仍保留历史未处理项，失败 {monitor_failed}，需核实 {monitor_attention}；"
                "这不等于今天新增失败。"
            )
            issue_lines = numbered_monitor_issue_lines(monitor)
            issue_label = "历史未处理清单" if monitor_failed else "需核实清单"
            if issue_lines:
                lines.append(f"{issue_label}：")
                lines.extend(issue_lines)
            else:
                lines.append(f"{issue_label}：透明化报告没有展开到具体任务，请刷新 Agent 状态。")
        else:
            lines.append(
                "透明化报告："
                f"完成 {monitor_summary.get('completed', 0)}，失败 {monitor_failed}，"
                f"需核实 {monitor_attention}。"
            )
    return "\n".join(lines)


def skipped_execution_agents(pipeline: dict[str, Any]) -> list[dict[str, Any]]:
    stages = pipeline.get("stages") if isinstance(pipeline.get("stages"), list) else []
    return [
        stage
        for stage in stages
        if isinstance(stage, dict)
        and str(stage.get("agent") or "").lower() in {"execute", "execution"}
        and stage.get("status") == "skipped"
    ]


def successful_execution_agents(pipeline: dict[str, Any]) -> list[dict[str, Any]]:
    stages = pipeline.get("stages") if isinstance(pipeline.get("stages"), list) else []
    return [
        stage
        for stage in stages
        if isinstance(stage, dict)
        and str(stage.get("agent") or "").lower() in {"execute", "execution"}
        and stage.get("status") == "success"
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


def failed_tasks(monitor: dict[str, Any]) -> list[dict[str, Any]]:
    rows = monitor.get("tasks") if isinstance(monitor.get("tasks"), list) else []
    return [row for row in rows if isinstance(row, dict) and row.get("status") == "failed"]


def verification_tasks(monitor: dict[str, Any]) -> list[dict[str, Any]]:
    rows = monitor.get("tasks") if isinstance(monitor.get("tasks"), list) else []
    return [row for row in rows if isinstance(row, dict) and row.get("status") in {"attention", "missing", "running"}]


def rerun_candidates(monitor: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    plan = monitor.get("rerun_plan") if isinstance(monitor.get("rerun_plan"), list) else []
    allowed = [item for item in plan if isinstance(item, dict) and item.get("auto_allowed")]
    manual = [item for item in plan if isinstance(item, dict) and not item.get("auto_allowed")]
    return allowed, manual


def monitor_tasks(monitor: dict[str, Any]) -> list[dict[str, Any]]:
    rows = monitor.get("tasks") if isinstance(monitor.get("tasks"), list) else []
    return [row for row in rows if isinstance(row, dict)]


def task_state_text(row: dict[str, Any]) -> str:
    labels = {
        "completed": "成功",
        "failed": "失败",
        "attention": "需核实",
        "missing": "未记录",
        "running": "运行中",
        "skipped": "已跳过",
    }
    status = str(row.get("status") or "")
    return labels.get(status, str(row.get("status_text") or status or "未知"))


def task_action_text(row: dict[str, Any]) -> str:
    rerun = row.get("rerun") if isinstance(row.get("rerun"), dict) else {}
    if rerun.get("suggested") and rerun.get("auto_allowed"):
        return "可自动补跑"
    if rerun.get("suggested"):
        return "需人工确认，不自动补跑"
    return "不用补跑"


def task_evidence(row: dict[str, Any]) -> str:
    return str(row.get("evidence") or row.get("log_path") or "").strip()


def task_reason(row: dict[str, Any]) -> str:
    status = str(row.get("status") or "")
    if status in {"completed", "skipped"}:
        return ""
    return compact_reason(row.get("failure_reason") or row.get("message") or row.get("human_action"), fallback="")


def monitor_issue_rows(monitor: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        row
        for row in monitor_tasks(monitor)
        if row.get("status") in {"failed", "attention", "missing", "running"}
    ]


def numbered_monitor_issue_lines(monitor: dict[str, Any], *, limit: int = 8) -> list[str]:
    rows = monitor_issue_rows(monitor)
    lines: list[str] = []
    for index, row in enumerate(rows[:limit], start=1):
        name = str(row.get("name") or row.get("id") or "未命名任务")
        line = f"{index}. {name}：{task_state_text(row)}"
        reason = task_reason(row)
        evidence = task_evidence(row)
        action = task_action_text(row)
        if reason:
            line += f"。原因：{reason}"
        if evidence:
            line += f"。证据：{evidence}"
        if action != "不用补跑" or str(row.get("status") or "") != "completed":
            line += f"。处理：{action}"
        lines.append(line)
    if len(rows) > limit:
        lines.append(f"另外还有 {len(rows) - limit} 项未展开。")
    return lines


def report_conclusion(summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    total = int(summary.get("total") or len(rows))
    completed = int(summary.get("completed") or 0)
    failed = int(summary.get("failed") or 0)
    attention = int(summary.get("attention") or 0) + int(summary.get("missing") or 0)
    running = int(summary.get("running") or 0)
    if failed:
        return f"结论：不完全正常，有 {failed} 个失败项；成功 {completed}/{total}，需核实 {attention}，运行中 {running}。"
    if attention or running:
        return f"结论：核心任务没有失败，但有 {attention + running} 项需要核实；成功 {completed}/{total}。"
    return f"结论：当前任务正常；成功 {completed}/{total}，没有失败或待核实项。"


def feature_status_line(index: int, row: dict[str, Any]) -> str:
    name = str(row.get("name") or row.get("id") or "未命名功能")
    status = task_state_text(row)
    action = task_action_text(row)
    reason = task_reason(row)
    parts = [f"{index}. {name}：{status}"]
    if reason:
        parts.append(f"依据：{reason}")
    if action != "不用补跑" or str(row.get("status") or "") != "completed":
        parts.append(f"处理：{action}")
    return "。".join(parts)


def format_task_line(index: int, row: dict[str, Any]) -> str:
    name = str(row.get("name") or row.get("id") or "未命名任务")
    line = f"{index}. {name}：{task_state_text(row)}"
    reason = task_reason(row)
    if reason:
        line += f"。原因：{reason}"
    action = task_action_text(row)
    if action != "不用补跑" or str(row.get("status") or "") != "completed":
        line += f"。处理：{action}"
    return line


def build_numbered_task_report(monitor: dict[str, Any], *, problem_only: bool = False) -> str:
    summary = monitor.get("summary") if isinstance(monitor.get("summary"), dict) else {}
    rows = monitor_tasks(monitor)
    if problem_only:
        rows = [row for row in rows if row.get("status") in {"failed", "attention", "missing", "running"}]
    total = int(summary.get("total") or len(monitor_tasks(monitor)) or len(rows))
    completed = int(summary.get("completed") or 0)
    failed = int(summary.get("failed") or 0)
    attention = int(summary.get("attention") or 0)
    missing = int(summary.get("missing") or 0)
    running = int(summary.get("running") or 0)
    if not rows:
        if problem_only:
            return f"今天没有失败项，也没有需要核实的任务。已完成 {completed}/{total} 项。"
        return "当前没有读到任务明细，请先刷新 Agent 状态。"

    unresolved = failed + attention + missing + running
    title = "今天需要处理的功能：" if problem_only else "自动化功能验收报告："
    lines = [
        title,
        report_conclusion(summary, monitor_tasks(monitor)),
        "功能验收状态：",
    ]
    for index, row in enumerate(rows[:20], start=1):
        lines.append(feature_status_line(index, row))
    if len(rows) > 20:
        lines.append(f"另外还有 {len(rows) - 20} 项没有展开。")

    allowed, manual = rerun_candidates(monitor)
    lines.append("处理建议：")
    if allowed:
        names = "、".join(str(item.get("task_name") or item.get("task_id")) for item in allowed[:6])
        lines.append(f"可自动处理：{names}。你说“执行补跑”时，我只跑这些低风险项。")
    else:
        lines.append("可自动处理：当前没有低风险自动补跑项。")
    if manual and unresolved:
        names = "、".join(str(item.get("task_name") or item.get("task_id")) for item in manual[:6])
        extra = "" if len(manual) <= 6 else f"；另有 {len(manual) - 6} 项"
        lines.append(f"需要你确认：{names}{extra}。")
    return "\n".join(lines)


def build_status_answer(pipeline: dict[str, Any], monitor: dict[str, Any], task_runs: dict[str, Any] | None = None, question: str = "") -> str:
    if isinstance(task_runs, dict) and task_runs.get("tasks"):
        return build_daily_task_runs_report(task_runs, monitor, question)
    if monitor_tasks(monitor):
        return build_numbered_task_report(monitor)
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
            f"真正失败 {monitor_summary.get('failed', 0)} 个，需核实 {monitor_summary.get('attention', 0)} 个。"
        )
    skipped = skipped_execution_agents(pipeline)
    if skipped:
        names = "、".join(str(stage.get("name") or stage.get("id")) for stage in skipped)
        line += f" 被跳过的是：{names}。它需要显式启用，且订货任务排除在外。"
    executed = successful_execution_agents(pipeline)
    if executed:
        names = "、".join(str(stage.get("name") or stage.get("id")) for stage in executed)
        line += f" 已参与执行的是：{names}；订货/下单/采购类动作仍然排除。"
    return line


def build_problem_answer(pipeline: dict[str, Any], monitor: dict[str, Any]) -> str:
    failed_stages = failed_pipeline_stages(pipeline)
    if failed_stages:
        first = failed_stages[0]
        return f"agent 流程本身有失败：{first.get('name')}。原因：{compact_reason(first.get('message'))}。"

    if monitor_tasks(monitor):
        return build_numbered_task_report(monitor, problem_only=True)

    failures = failed_tasks(monitor)
    checks = verification_tasks(monitor)
    if not failures and not checks:
        return "这组 agent 本身没有失败项。当前没有从透明化报告里读到需要处理或核实的任务。"

    if not failures:
        names = "、".join(str(row.get("name") or row.get("id")) for row in checks[:5])
        extra = "" if len(checks) <= 5 else f"；另外还有 {len(checks) - 5} 项"
        return (
            f"今天没有读到真正失败项。需核实 {len(checks)} 项，但这些不是失败：{names}{extra}。"
            "需核实通常表示产物存在但步骤账本缺记录，不能直接算失败。"
        )

    parts = []
    for row in failures[:5]:
        name = row.get("name") or row.get("id")
        reason = compact_reason(row.get("failure_reason") or row.get("message"))
        evidence = row.get("evidence") or ""
        evidence_text = f"，证据：{evidence}" if evidence else ""
        parts.append(f"{name}：{reason}{evidence_text}")
    extra_failures = "" if len(failures) <= 5 else f" 另外还有 {len(failures) - 5} 个失败项。"
    verify_text = f"另有 {len(checks)} 项需核实，但不算失败。" if checks else "没有其它需核实项。"
    return f"今天真正失败 {len(failures)} 项：" + "；".join(parts) + f"。{extra_failures}{verify_text}"


def build_problem_answer_for_date(pipeline: dict[str, Any], monitor: dict[str, Any], task_runs: dict[str, Any], question: str) -> str:
    target_date = date_for_question(question)
    if target_date == today_text() and is_task_runs_stale_for_date(task_runs, target_date):
        lines = [
            "今天失败明细：",
            stale_task_runs_notice(task_runs, target_date),
            "结论：当前不能确认今天是否有新增失败；下面只列历史未处理项。",
        ]
        issue_lines = numbered_monitor_issue_lines(monitor)
        if issue_lines:
            lines.append("历史未处理清单：")
            lines.extend(issue_lines)
        else:
            lines.append("历史未处理清单：当前没有读到失败或需核实任务。")
        lines.append("处理建议：先刷新 Agent 状态；刷新后再按编号看今天新增失败。")
        return "\n".join(lines)
    tasks = task_runs.get("tasks") if isinstance(task_runs.get("tasks"), dict) else {}
    events = task_runs.get("events") if isinstance(task_runs.get("events"), list) else []
    failed = []
    task_names = {task_id: name for task_id, name, _section in TRACKED_TASKS}
    for event in events:
        if not isinstance(event, dict) or event.get("status") != "failed":
            continue
        if date_part(event.get("created_at")) != target_date:
            continue
        task_id = str(event.get("task_id") or "")
        name = task_names.get(task_id, task_id or str(event.get("step") or "未知任务"))
        failed.append((name, task_from_event(event, tasks.get(task_id, {}) if isinstance(tasks.get(task_id), dict) else {})))
    for task_id, name, _section in TRACKED_TASKS:
        task = tasks.get(task_id) if isinstance(tasks.get(task_id), dict) else {}
        if task and date_part(task.get("updated_at") or task.get("finished_at")) == target_date and task.get("status") == "failed":
            failed.append((name, task))
    if failed:
        title_date = "今天" if target_date == today_text() else target_date
        seen = set()
        unique_failed = []
        for name, task in failed:
            key = (name, task.get("updated_at"), task.get("step"), task.get("message"))
            if key in seen:
                continue
            seen.add(key)
            unique_failed.append((name, task))

        success_events = [
            event
            for event in events
            if isinstance(event, dict)
            and date_part(event.get("created_at")) == target_date
            and event.get("status") == "success"
        ]
        active_failed = []
        recovered_failed = []
        for name, task in unique_failed:
            task_id = str(task.get("task_id") or "")
            failed_at = comparable_time(task.get("updated_at") or task.get("finished_at"))
            later_success = next(
                (
                    event
                    for event in success_events
                    if str(event.get("task_id") or "") == task_id
                    and comparable_time(event.get("created_at")) >= failed_at
                ),
                None,
            )
            latest_task = tasks.get(task_id) if isinstance(tasks.get(task_id), dict) else {}
            latest_at = comparable_time(latest_task.get("updated_at") or latest_task.get("finished_at"))
            latest_success = (
                bool(latest_task)
                and latest_task.get("status") == "success"
                and date_part(latest_at) == target_date
                and latest_at >= failed_at
            )
            if later_success or latest_success:
                recovered_failed.append((name, task, later_success or latest_task))
            else:
                active_failed.append((name, task))

        lines = [f"{title_date}失败明细："]
        date_scope = "今日" if target_date == today_text() else f"{target_date} 当天"
        if active_failed:
            lines.append(f"结论：当前仍有 {len(active_failed)} 个{date_scope}失败项。")
            lines.append("当前失败清单：")
        else:
            lines.append(f"结论：当前没有{date_scope}未恢复失败；{date_scope}曾失败后已恢复 {len(recovered_failed)} 项。")

        for index, (name, task) in enumerate(active_failed, start=1):
            updated = str(task.get("updated_at") or task.get("finished_at") or "")
            detail = task_run_details(task)
            evidence = task.get("log_path") or ""
            line = f"{index}. {name}：失败（{time_part(updated)}）"
            if task.get("step"):
                line += f"，步骤：{task.get('step')}"
            if detail:
                line += f"。原因：{detail}"
            if evidence:
                line += f"。证据：{evidence}"
            lines.append(line)

        if recovered_failed:
            lines.append("已恢复记录：")
            for index, (name, task, recovery) in enumerate(recovered_failed, start=1):
                updated = str(task.get("updated_at") or task.get("finished_at") or "")
                detail = task_run_details(task)
                evidence = task.get("log_path") or ""
                recovery_at = str(recovery.get("created_at") or recovery.get("updated_at") or recovery.get("finished_at") or "")
                recovery_step = str(recovery.get("step") or "").strip()
                recovery_text = f"后续已有成功记录（{time_part(recovery_at)}"
                if recovery_step:
                    recovery_text += f"，{recovery_step}"
                recovery_text += "），所以不算当前失败"
                line = f"{index}. {name}：曾失败（{time_part(updated)}）"
                if task.get("step"):
                    line += f"，步骤：{task.get('step')}"
                if detail:
                    line += f"。原因：{detail}"
                if evidence:
                    line += f"。证据：{evidence}"
                line += f"。恢复：{recovery_text}"
                lines.append(line)
        if recovered_failed and not active_failed:
            lines.append("处理建议：无需按失败处理；如需复盘，再查看对应证据日志。")
        return "\n".join(lines)
    if target_date == today_text() and ("今天" in question or "今日" in question):
        monitor_summary = monitor.get("summary") if isinstance(monitor.get("summary"), dict) else {}
        historical_failed = int(monitor_summary.get("failed") or 0)
        historical_attention = int(monitor_summary.get("attention") or 0)
        lines = [
            "今天失败明细：",
            "结论：今天没有读到失败项。",
        ]
        if historical_failed or historical_attention:
            lines.append(
                f"历史未处理：透明化报告仍保留失败 {historical_failed}，需核实 {historical_attention}；"
                "这不是今天新增失败。"
            )
            issue_lines = numbered_monitor_issue_lines(monitor)
            issue_label = "历史未处理清单" if historical_failed else "需核实清单"
            if issue_lines:
                lines.append(f"{issue_label}：")
                lines.extend(issue_lines)
            else:
                lines.append(f"{issue_label}：透明化报告没有展开到具体任务，请刷新 Agent 状态。")
        lines.append("说明：如果你要看历史原因，可以问“最近一次失败是什么原因”或指定日期。")
        return "\n".join(lines)
    if "昨天" in question:
        return build_daily_task_runs_report(task_runs, monitor, question)
    return build_problem_answer(pipeline, monitor)


def build_rerun_answer(monitor: dict[str, Any]) -> str:
    allowed, manual = rerun_candidates(monitor)
    if not allowed and not manual:
        return "当前没有读到补跑计划。"
    failures = {str(row.get("id") or "") for row in failed_tasks(monitor)}
    lines = ["补跑计划："]
    if allowed:
        lines.append("可自动补跑：")
        for index, item in enumerate(allowed[:10], start=1):
            name = str(item.get("task_name") or item.get("task_id"))
            reason = compact_reason(item.get("reason"), fallback="低风险或幂等任务")
            lines.append(f"{index}. {name}：{reason}")
    else:
        lines.append("可自动补跑：当前没有。")
    if manual:
        failed_manual = [item for item in manual if str(item.get("task_id") or "") in failures]
        other_manual = [item for item in manual if str(item.get("task_id") or "") not in failures]
        if failed_manual:
            lines.append("失败但需人工确认：")
            for index, item in enumerate(failed_manual[:10], start=1):
                name = str(item.get("task_name") or item.get("task_id"))
                reason = compact_reason(item.get("reason"), fallback="高风险或需要登录态确认")
                lines.append(f"{index}. {name}：{reason}")
        if other_manual:
            lines.append("需核实但不是失败：")
            for index, item in enumerate(other_manual[:10], start=1):
                name = str(item.get("task_name") or item.get("task_id"))
                reason = compact_reason(item.get("reason"), fallback="需要补齐完成证据")
                lines.append(f"{index}. {name}：{reason}")
    lines.append("你说“执行补跑”时，我只会执行可自动补跑清单里的低风险项。")
    return "\n".join(lines)


def build_execution_answer(pipeline: dict[str, Any]) -> str:
    executed = successful_execution_agents(pipeline)
    if executed:
        details = []
        execution_payload = read_json(ROOT / "outputs" / "agent_execution" / "latest.json", {})
        summary = execution_payload.get("summary") if isinstance(execution_payload.get("summary"), dict) else {}
        for stage in executed:
            details.append(f"{stage.get('name') or stage.get('id')}（id: {stage.get('id')}, agent: {stage.get('agent')}）")
        return (
            "执行 Agent 已参与：" + "、".join(details) + "。"
            f"最近执行结果：成功 {summary.get('success', 0)} 个，失败 {summary.get('failed', 0)} 个，"
            f"拦截 {summary.get('blocked', 0)} 个；订货/下单/采购类动作不参与。"
        )
    skipped = skipped_execution_agents(pipeline)
    if not skipped:
        return "这次没有读到执行 Agent 的运行记录。"
    details = []
    for stage in skipped:
        details.append(
            f"{stage.get('name') or stage.get('id')}（id: {stage.get('id')}, agent: {stage.get('agent')}）："
            f"{compact_reason(stage.get('message'))}"
        )
    return "刚刚跳过的是 " + "；".join(details) + "。"


def normalized_store_name(value: str) -> str:
    text = str(value or "").strip()
    aliases = {
        "朝阳门": "朝阳门店",
        "雅宝": "朝阳门店",
        "银泰城": "银泰城店",
        "万象城": "万象城店",
        "金融城": "金融城店",
        "保利中心": "保利中心店",
    }
    for key, name in aliases.items():
        if key in text:
            return name
    return text


def platform_terms(question: str) -> list[str]:
    platforms = []
    if "美团" in question:
        platforms.append("美团")
    if "饿了么" in question or "饿了" in question:
        platforms.append("饿了么")
    return platforms


def is_business_data_question(question: str) -> bool:
    if not any(token in question for token in ("店", "朝阳门", "雅宝", "银泰", "万象", "金融城", "保利")):
        return False
    return any(token in question for token in ("数据", "数据页", "日报", "恢复", "有没有", "有吗", "订单", "营业额", "美团", "饿了么"))


def format_number(value: str) -> str:
    try:
        number = float(str(value or "0"))
    except ValueError:
        return str(value or "0")
    if abs(number - round(number)) < 0.001:
        return str(int(round(number)))
    return f"{number:.2f}".rstrip("0").rstrip(".")


def direct_daily_answer(question: str) -> str:
    rows = read_csv_rows(DIRECT_DAILY_PATH)
    if not rows:
        return "我没读到直营日报数据文件，暂时不能判断门店数据页是否恢复。"
    store = normalized_store_name(question)
    if not store or store == question:
        store = next((name for name in ["朝阳门店", "银泰城店", "万象城店", "金融城店", "保利中心店"] if name[:2] in question or name in question), "")
    if not store:
        return "你问的是门店数据，但我没识别出具体门店。可以直接说“朝阳门店美团数据恢复了吗”。"

    latest = max(str(row.get("date") or "") for row in rows if row.get("date"))
    store_rows = [row for row in rows if row.get("date") == latest and row.get("store") == store]
    wanted_platforms = platform_terms(question) or ["美团", "饿了么"]
    matched = [row for row in store_rows if row.get("platform") in wanted_platforms]
    if not matched:
        have = "、".join(row.get("platform", "") for row in store_rows) or "没有任何平台"
        return f"没有恢复完整。{store} 最新直营日报日期是 {latest or '未知'}，当前只读到：{have}；没有读到 {'、'.join(wanted_platforms)}。"

    lines = [f"{store}数据页：已恢复。" if len(matched) == len(wanted_platforms) else f"{store}数据页：部分恢复。"]
    lines.append(f"最新日期：{latest}。")
    for row in matched:
        lines.append(
            f"{row.get('platform')}：{format_number(row.get('orders', '0'))} 单，营业收入 {format_number(row.get('income', '0'))}。"
        )
    missing = [platform for platform in wanted_platforms if platform not in {row.get("platform") for row in matched}]
    if missing:
        lines.append("未读到：" + "、".join(missing) + "。")
    raw_names = [row.get("store_raw") for row in matched if row.get("store_raw") and row.get("store_raw") != store]
    if raw_names:
        lines.append(f"平台原始门店名：{raw_names[0]}；系统已归并为 {store}。")
    return "\n".join(lines)


def looks_like_rerun_request(question: str) -> bool:
    if any(token in question for token in ("补跑", "重跑", "重新跑", "执行补跑", "执行重跑")):
        return True
    if "恢复" in question and any(token in question for token in ("执行", "开始", "处理", "修复")):
        return True
    return False


def compact_task_rows(rows: Any, *, limit: int = 8) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    compacted: list[dict[str, Any]] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        compacted.append(
            {
                "id": row.get("id") or row.get("task_id"),
                "name": row.get("name") or row.get("task_name"),
                "status": row.get("status"),
                "status_text": row.get("status_text"),
                "message": compact_reason(row.get("failure_reason") or row.get("message"), fallback=""),
                "auto_allowed": row.get("auto_allowed"),
            }
        )
    return compacted


def build_llm_context(
    *,
    intent: str,
    pipeline: dict[str, Any],
    monitor: dict[str, Any],
    task_runs: dict[str, Any],
    refreshed: dict[str, Any] | None,
) -> dict[str, Any]:
    stages = pipeline.get("stages") if isinstance(pipeline.get("stages"), list) else []
    monitor_tasks = monitor.get("tasks") if isinstance(monitor.get("tasks"), list) else []
    rerun_plan = monitor.get("rerun_plan") if isinstance(monitor.get("rerun_plan"), list) else []
    return {
        "intent": intent,
        "generated_at": {
            "pipeline": pipeline.get("generated_at"),
            "monitor": monitor.get("generated_at"),
            "task_runs": task_runs.get("generated_at") if isinstance(task_runs, dict) else "",
        },
        "pipeline": {
            "name": (pipeline.get("pipeline") or {}).get("name") if isinstance(pipeline.get("pipeline"), dict) else "",
            "summary": pipeline.get("summary") if isinstance(pipeline.get("summary"), dict) else {},
            "safety": pipeline.get("safety") if isinstance(pipeline.get("safety"), dict) else {},
            "stages": compact_task_rows(stages, limit=8),
        },
        "monitor": {
            "summary": monitor.get("summary") if isinstance(monitor.get("summary"), dict) else {},
            "attention_tasks": compact_task_rows(attention_tasks(monitor), limit=8),
            "rerun_plan": compact_task_rows(rerun_plan, limit=8),
        },
        "refresh": refreshed or {"ran": False},
        "safety": {
            "ordering_excluded": True,
            "llm_advisory_only": True,
            "requires_execute_flag_for_mutation": True,
        },
    }


def maybe_improve_answer(
    *,
    question: str,
    draft_answer: str,
    intent: str,
    pipeline: dict[str, Any],
    monitor: dict[str, Any],
    task_runs: dict[str, Any],
    refreshed: dict[str, Any] | None,
    use_llm: bool,
) -> tuple[str, dict[str, Any]]:
    if not use_llm:
        return draft_answer, {"enabled": False, "used": False, "fallback": "llm-disabled-by-flag"}
    context = build_llm_context(
        intent=intent,
        pipeline=pipeline,
        monitor=monitor,
        task_runs=task_runs,
        refreshed=refreshed,
    )
    record = agent_llm.generate_answer(question=question, draft_answer=draft_answer, context=context)
    record["draft_answer"] = draft_answer
    if record.get("used") and float(record.get("confidence") or 0) >= 0.5:
        return str(record.get("answer") or draft_answer), record
    return draft_answer, record


def answer_question(question: str, *, refreshed: dict[str, Any] | None = None, use_llm: bool = True) -> dict[str, Any]:
    pipeline = read_json(PIPELINE_PATH, {})
    monitor = read_json(MONITOR_PATH, {})
    task_runs = read_json(TASK_RUNS_PATH, {})
    normalized = question.strip() or "现在怎么样？"
    lower = normalized.lower()

    if is_business_data_question(normalized):
        intent = "business_data"
        answer = direct_daily_answer(normalized)
    elif any(keyword in normalized for keyword in ("执行", "跳过", "4号", "4 号")):
        intent = "execution_agent"
        answer = build_execution_answer(pipeline)
    elif looks_like_rerun_request(normalized):
        intent = "rerun"
        answer = build_rerun_answer(monitor)
    elif any(keyword in normalized for keyword in ("问题", "失败", "异常", "坏", "报错")):
        intent = "problems"
        answer = build_problem_answer_for_date(pipeline, monitor, task_runs if isinstance(task_runs, dict) else {}, normalized)
    elif "help" in lower or "怎么问" in normalized or "帮助" in normalized:
        intent = "help"
        answer = "你可以问：今天哪里有问题、哪些任务能补跑、刚刚跳过的执行 Agent 是谁、现在 agent 状态怎么样。"
    else:
        intent = "status"
        answer = build_status_answer(pipeline, monitor, task_runs if isinstance(task_runs, dict) else {}, normalized)

    factual_intents = {"status", "problems", "rerun", "execution_agent", "business_data"}
    effective_use_llm = bool(use_llm and intent not in factual_intents)
    final_answer, llm_record = maybe_improve_answer(
        question=normalized,
        draft_answer=answer,
        intent=intent,
        pipeline=pipeline,
        monitor=monitor,
        task_runs=task_runs if isinstance(task_runs, dict) else {},
        refreshed=refreshed,
        use_llm=effective_use_llm,
    )

    return {
        "generated_at": now_text(),
        "host": socket.gethostname(),
        "question": normalized,
        "intent": intent,
        "answer": final_answer,
        "llm": {
            "enabled": bool(effective_use_llm),
            "used": bool(llm_record.get("used")),
            "provider": llm_record.get("provider", ""),
            "model": llm_record.get("model", ""),
            "confidence": llm_record.get("confidence", 0),
            "reason": llm_record.get("reason", ""),
            "error": llm_record.get("error", ""),
            "fallback": llm_record.get("fallback", ""),
            "draft_answer": llm_record.get("draft_answer", ""),
        },
        "sources": {
            "pipeline": str(PIPELINE_PATH.relative_to(ROOT)),
            "monitor": str(MONITOR_PATH.relative_to(ROOT)),
            "task_runs": str(TASK_RUNS_PATH.relative_to(ROOT)),
            "direct_daily": str(DIRECT_DAILY_PATH.relative_to(ROOT)),
        },
        "refresh": refreshed or {"ran": False},
        "task_runs_generated_at": task_runs.get("generated_at") if isinstance(task_runs, dict) else "",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="和本地多 Agent 运行结果对话。")
    parser.add_argument("question", nargs="*", help="要问 agent 的问题")
    parser.add_argument("--refresh", action="store_true", help="回答前先安全刷新 daily_automation_guard")
    parser.add_argument("--no-llm", action="store_true", help="禁用大模型回答生成，强制使用本地规则回答")
    parser.add_argument("--json-out", default=str(OUTPUT_DIR / "latest.json"), help="JSON 回答输出路径")
    parser.add_argument("--text-out", default=str(OUTPUT_DIR / "latest.txt"), help="文本回答输出路径")
    args = parser.parse_args()

    refreshed = None
    if args.refresh:
        refresh_result = run_refresh()
        refreshed = {"ran": True, **refresh_result}

    question = " ".join(args.question).strip() or "现在 agent 状态怎么样？"
    payload = answer_question(question, refreshed=refreshed, use_llm=not args.no_llm)
    json_out = Path(args.json_out).expanduser()
    text_out = Path(args.text_out).expanduser()
    write_json(json_out, payload)
    atomic_write_text(text_out, payload["answer"] + "\n")
    print(payload["answer"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
