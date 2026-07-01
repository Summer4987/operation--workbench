#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import plistlib
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUNS_PATH = ROOT / "outputs" / "task_runs" / "latest.json"
LEGACY_RUNS_PATH = Path.home() / "Documents" / "New project" / "outputs" / "task_runs" / "latest.json"
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
LABEL_PREFIX = "com.summer.operation"
GRACE_MINUTES = 20

LABEL_NAMES = {
    "com.summer.operation.morning": "上午运营一键采集",
    "com.summer.operation.realtime-order-income": "实时单量和营业额采集",
    "com.summer.operation.agent-task-notifier": "Hermes 自动汇报通知器",
    "com.summer.operation.ai-center-guardian": "AI 业务中心守护检查",
    "com.summer.operation.cainiao-logistics": "菜鸟物流采集",
    "com.summer.operation.evening": "晚间预算任务",
}
LABEL_TASK_IDS = {
    "com.summer.operation.morning": "ops.morning_collection",
    "com.summer.operation.realtime-order-income": "ops.realtime_order_income",
}
STATUS_WORDS = {
    "ok": "正常",
    "success": "完成",
    "failed": "失败",
    "warning": "需要关注",
    "missing": "没看到今天运行记录",
    "upcoming": "还没到时间",
    "running": "正在运行",
}
RERUN_HINTS = {
    "com.summer.operation.realtime-order-income": "可以补跑。它是只读采集加 data-only 发布，优先补这个；命令是 /bin/zsh ~/Library/Scripts/xiong-operation/run_realtime_order_income.zsh。",
    "com.summer.operation.cainiao-logistics": "可以补采集，但它没有写入统一任务账本，先确认安卓连接和采集脚本日志。",
    "com.summer.operation.morning": "不建议直接补跑整条上午任务，因为会碰到预算/发布等高风险步骤；应该按失败子步骤拆开处理。",
    "com.summer.operation.evening": "不建议自动补跑。它涉及推广预算真实提交，必须人工确认目标和窗口。",
}


def read_json(path: Path, fallback: Any) -> Any:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if payload is not None else fallback
    except Exception:
        return fallback


def load_task_runs() -> tuple[dict[str, Any], Path]:
    runs = read_json(RUNS_PATH, {})
    legacy_runs = read_json(LEGACY_RUNS_PATH, {})
    merged_tasks: dict[str, Any] = {}
    source_path = RUNS_PATH
    for path, payload in ((LEGACY_RUNS_PATH, legacy_runs), (RUNS_PATH, runs)):
        tasks = payload.get("tasks") if isinstance(payload.get("tasks"), dict) else {}
        if not tasks:
            continue
        if not merged_tasks:
            source_path = path
        for task_id, task in tasks.items():
            if not isinstance(task, dict):
                continue
            current = merged_tasks.get(task_id)
            if not isinstance(current, dict):
                merged_tasks[task_id] = task
                continue
            current_at = parse_time(current.get("finished_at") or current.get("updated_at"))
            task_at = parse_time(task.get("finished_at") or task.get("updated_at"))
            if current_at is None or (task_at is not None and task_at >= current_at):
                merged_tasks[task_id] = task
                source_path = path
    return {"tasks": merged_tasks}, source_path


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            pass
    return None


def load_plists(launch_agents_dir: Path = LAUNCH_AGENTS_DIR) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(launch_agents_dir.glob(f"{LABEL_PREFIX}*.plist")):
        try:
            payload = plistlib.loads(path.read_bytes())
        except Exception as exc:
            rows.append({"path": str(path), "label": path.stem, "plist_error": str(exc)})
            continue
        if not isinstance(payload, dict):
            continue
        label = str(payload.get("Label") or path.stem)
        rows.append({"path": str(path), "label": label, "plist": payload})
    return rows


def calendar_items(plist: dict[str, Any]) -> list[dict[str, Any]]:
    value = plist.get("StartCalendarInterval")
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def schedule_times_today(plist: dict[str, Any], now: datetime) -> list[datetime]:
    times: list[datetime] = []
    for item in calendar_items(plist):
        hour = item.get("Hour")
        minute = item.get("Minute", 0)
        try:
            scheduled = now.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
        except Exception:
            continue
        weekday = item.get("Weekday")
        if weekday is not None:
            launchd_weekday = 1 if now.isoweekday() == 7 else now.isoweekday() + 1
            if int(weekday) != launchd_weekday:
                continue
        day = item.get("Day")
        if day is not None and int(day) != now.day:
            continue
        month = item.get("Month")
        if month is not None and int(month) != now.month:
            continue
        times.append(scheduled)
    return sorted(times)


def schedule_text(times: list[datetime], plist: dict[str, Any]) -> str:
    if times:
        values = [item.strftime("%H:%M") for item in times]
        if len(values) > 8:
            return "、".join(values[:8]) + f" 等 {len(values)} 次"
        return "、".join(values)
    interval = plist.get("StartInterval")
    if interval:
        return f"每 {interval} 秒"
    if plist.get("RunAtLoad"):
        return "启动时运行"
    return "未配置时间"


def parse_launchctl_list(text: str) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        pid, status, label = parts[0], parts[1], parts[2]
        if label.startswith(LABEL_PREFIX):
            rows[label] = {"pid": pid, "status_code": status}
    return rows


def load_launchctl() -> dict[str, dict[str, str]]:
    completed = subprocess.run(
        ["launchctl", "list"],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    return parse_launchctl_list(completed.stdout or "")


def newest_log_time(plist: dict[str, Any]) -> tuple[datetime | None, str]:
    candidates = [plist.get("StandardOutPath"), plist.get("StandardErrorPath")]
    newest: tuple[datetime | None, str] = (None, "")
    for item in candidates:
        if not item:
            continue
        path = Path(os.path.expandvars(os.path.expanduser(str(item))))
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
        except OSError:
            continue
        if newest[0] is None or mtime > newest[0]:
            newest = (mtime, str(path))
    return newest


def task_run_for_label(label: str, runs: dict[str, Any]) -> dict[str, Any]:
    task_id = LABEL_TASK_IDS.get(label, "")
    tasks = runs.get("tasks") if isinstance(runs.get("tasks"), dict) else {}
    if task_id and isinstance(tasks.get(task_id), dict):
        return tasks[task_id]
    return {}


def classify_row(row: dict[str, Any], runs: dict[str, Any], launchctl: dict[str, dict[str, str]], now: datetime) -> dict[str, Any]:
    label = row.get("label") or ""
    plist = row.get("plist") or {}
    name = LABEL_NAMES.get(label, label.replace("com.summer.operation.", ""))
    times = schedule_times_today(plist, now)
    run = task_run_for_label(label, runs)
    finished_at = parse_time(run.get("finished_at") or run.get("updated_at"))
    latest_log_at, latest_log_path = newest_log_time(plist)
    state = launchctl.get(label, {})
    pid = state.get("pid", "-")
    status_code = state.get("status_code", "-")
    due_times = [item for item in times if item <= now - timedelta(minutes=GRACE_MINUTES)]

    status = "upcoming"
    reason = ""
    evidence = latest_log_path or row.get("path") or ""
    last_at = finished_at or latest_log_at

    if pid not in {"", "-"}:
        status = "running"
        reason = "launchd 显示正在运行。"
    elif finished_at and finished_at.date() == now.date():
        run_status = str(run.get("status") or "")
        if run_status == "success":
            status = "success"
            reason = str(run.get("message") or "今天已经完成。")
        elif run_status == "failed":
            status = "failed"
            reason = str(run.get("message") or "今天记录为失败。")
        elif run_status in {"warning", "skipped"}:
            status = "warning"
            reason = str(run.get("message") or "今天需要关注。")
        else:
            status = "warning"
            reason = str(run.get("message") or "今天有运行记录，但状态不明确。")
    elif latest_log_at and latest_log_at.date() == now.date() and due_times:
        if status_code not in {"0", "-", ""}:
            status = "failed"
            reason = f"今天有日志，但 launchd 最近退出码是 {status_code}。"
        else:
            status = "warning"
            reason = "今天有日志，但没有写入任务账本；Hermes 只能判断它触发过，不能确认业务结果。"
    elif due_times:
        status = "missing"
        reason = "已经过了计划时间，但没看到今天的运行账本或日志。"
    else:
        status = "upcoming"
        reason = "今天后面还有计划时间，当前不算失败。"

    if row.get("plist_error"):
        status = "failed"
        reason = f"launchd 配置文件读取失败：{row['plist_error']}"

    return {
        "label": label,
        "name": name,
        "status": status,
        "status_text": STATUS_WORDS.get(status, status),
        "reason": reason,
        "schedule": schedule_text(times, plist),
        "times": [item.strftime("%H:%M") for item in times],
        "pid": pid,
        "status_code": status_code,
        "last_at": last_at.strftime("%Y-%m-%d %H:%M:%S") if last_at else "",
        "evidence": evidence,
    }


def collect_status(period: str = "all", now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now()
    runs, runs_path = load_task_runs()
    launchctl = load_launchctl()
    rows = [classify_row(row, runs, launchctl, now) for row in load_plists()]
    if period == "afternoon":
        rows = [
            row
            for row in rows
            if any(parse_hhmm(value) and parse_hhmm(value).hour >= 12 for value in row.get("times") or [])
        ]
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return {
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "period": period,
        "runs_path": str(runs_path),
        "tasks": rows,
        "counts": counts,
    }


def parse_hhmm(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%H:%M")
    except Exception:
        return None


def format_human(payload: dict[str, Any]) -> str:
    tasks = payload.get("tasks") or []
    period = "下午自动化" if payload.get("period") == "afternoon" else "今天定时任务"
    counts = payload.get("counts") or {}
    bad = [row for row in tasks if row.get("status") in {"failed", "missing", "warning"}]
    lines = [
        f"我查了 Mac mini 的{period}，不是读缓存。",
        f"共 {len(tasks)} 个；完成 {counts.get('success', 0)}，失败 {counts.get('failed', 0)}，没看到记录 {counts.get('missing', 0)}，需要关注 {counts.get('warning', 0)}，未到时间 {counts.get('upcoming', 0)}。",
    ]
    if not tasks:
        lines.append("我没有找到对应的 launchd 定时任务。")
        return "\n".join(lines)
    if bad:
        lines.append("需要你关注的是：")
        for row in bad[:8]:
            last = f"，最近记录 {row['last_at']}" if row.get("last_at") else ""
            lines.append(f"- {row['name']}：{row['status_text']}。{row['reason']}{last}")
    else:
        lines.append("目前没看到失败或漏跑。")
    lines.append("完整任务：")
    for row in tasks[:12]:
        last = f"，最近 {row['last_at']}" if row.get("last_at") else ""
        lines.append(f"- {row['name']}：{row['status_text']}；计划 {row['schedule']}{last}")
    if len(tasks) > 12:
        lines.append(f"还有 {len(tasks) - 12} 个没展开。")
    return "\n".join(lines)


def latest_issue(payload: dict[str, Any]) -> dict[str, Any] | None:
    rows = [
        row
        for row in payload.get("tasks") or []
        if row.get("status") in {"failed", "warning", "missing"}
    ]
    if not rows:
        return None

    def sort_key(row: dict[str, Any]) -> tuple[int, datetime]:
        priority = {"failed": 0, "warning": 1, "missing": 2}.get(str(row.get("status")), 9)
        return (priority, parse_time(row.get("last_at")) or datetime.min)

    return sorted(rows, key=sort_key)[0]


def format_latest_issue(payload: dict[str, Any], *, include_rerun: bool) -> str:
    row = latest_issue(payload)
    if row is None:
        return "我查了今天的定时任务，目前没有看到失败、漏跑或需要关注的任务。"
    label = str(row.get("label") or "")
    lines = [
        f"最近需要处理的是：{row.get('name')}。",
        f"状态：{row.get('status_text')}。",
        f"原因：{row.get('reason') or '没有记录到具体原因。'}",
    ]
    if row.get("last_at"):
        lines.append(f"时间：{row['last_at']}。")
    if row.get("evidence"):
        lines.append(f"日志：{row['evidence']}。")
    if include_rerun:
        lines.append(RERUN_HINTS.get(label, "我先不建议直接补跑；需要先看日志确认是否涉及登录、预算、发布或真实平台操作。"))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="给 Hermes 查询 Mac mini launchd 定时任务运行情况")
    parser.add_argument("--period", choices=["all", "afternoon"], default="all")
    parser.add_argument("--explain-latest", action="store_true", help="解释最近一个失败/需关注任务")
    parser.add_argument("--rerun-advice", action="store_true", help="同时给出是否适合补跑")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = collect_status(period=args.period)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.explain_latest:
        print(format_latest_issue(payload, include_rerun=args.rerun_advice))
    else:
        print(format_human(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
