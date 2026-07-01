from __future__ import annotations

import argparse
import json
import socket
from datetime import datetime
from pathlib import Path
from typing import Any

from atomic_io import atomic_write_text


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "ai-business-center" / "config" / "notification_tasks.json"
DEFAULT_HEALTH_PATH = ROOT / "outputs" / "task_health" / "latest.json"
DEFAULT_RUNS_PATH = ROOT / "outputs" / "task_runs" / "latest.json"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "agent_task_monitor"

HEALTH_STATUS_FAILED = {"danger", "failed", "error"}
HEALTH_STATUS_WARN = {"warn", "warning", "stale", "missing"}
RUN_STATUS_DONE = {"success", "skipped"}
RUN_STATUS_FAILED = {"failed", "error"}


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


def policy_by_task(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    policies: dict[str, dict[str, Any]] = {}
    defaults = config.get("defaults") if isinstance(config.get("defaults"), dict) else {}
    default_rerun = defaults.get("rerun_policy") if isinstance(defaults.get("rerun_policy"), dict) else {}
    for item in config.get("tasks") or []:
        if isinstance(item, dict) and item.get("id"):
            item_rerun = item.get("rerun_policy") if isinstance(item.get("rerun_policy"), dict) else {}
            merged = {
                **defaults,
                **item,
                "rerun_policy": {**default_rerun, **item_rerun},
            }
            policies[str(item["id"])] = merged
    return policies


def task_rows(health: dict[str, Any], runs: dict[str, Any], policies: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for item in health.get("tasks") or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        task_id = str(item["id"])
        policy = policies.get(task_id, {})
        if policy.get("include_in_report") is False:
            continue
        rows[task_id] = build_task_report(task_id, item, runs, policy)

    for task_id, run_item in (runs.get("tasks") or {}).items():
        if not isinstance(run_item, dict) or task_id in rows:
            continue
        policy = policies.get(str(task_id), {})
        if not policy or policy.get("include_in_report") is False:
            continue
        rows[str(task_id)] = build_task_report(str(task_id), {}, runs, policy)

    configured_only = [
        task_id for task_id, policy in policies.items() if policy.get("include_in_report") is True and task_id not in rows
    ]
    for task_id in configured_only:
        rows[task_id] = build_task_report(task_id, {}, runs, policies[task_id])

    return sorted(rows.values(), key=task_sort_key)


def build_task_report(
    task_id: str,
    health_item: dict[str, Any],
    runs: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    run_item = (runs.get("tasks") or {}).get(task_id)
    if not isinstance(run_item, dict):
        run_item = {}

    health_status = str(health_item.get("status") or "")
    run_status = str(run_item.get("status") or health_item.get("last_run_status") or "")
    completion_status = classify_completion(health_status, run_status)
    failure_type = run_item.get("failure_type") or health_item.get("failure_type") or ""
    if completion_status == "attention":
        reason = first_text(
            health_item.get("reason"),
            run_item.get("message"),
            policy.get("missing_message") if completion_status == "missing" else "",
            "没有找到任务运行记录。",
        )
    else:
        reason = first_text(
            run_item.get("message"),
            health_item.get("reason"),
            policy.get("missing_message") if completion_status == "missing" else "",
            "没有找到任务运行记录。",
        )
    failed = completion_status == "failed"
    rerun_decision = build_rerun_decision(completion_status, health_item, run_item, policy)

    return {
        "id": task_id,
        "name": first_text(health_item.get("name"), policy.get("name"), task_id),
        "risk": first_text(health_item.get("risk"), policy.get("risk"), "unknown"),
        "schedule": first_text(health_item.get("schedule"), policy.get("schedule"), ""),
        "status": completion_status,
        "status_text": completion_status_text(completion_status),
        "completed": completion_status in {"completed", "skipped"},
        "failed": failed,
        "failure_type": failure_type,
        "failure_reason": reason if failed or completion_status in {"attention", "missing"} else "",
        "last_run_at": first_text(
            run_item.get("updated_at"),
            run_item.get("finished_at"),
            health_item.get("last_run_at"),
            health_item.get("last_seen_at"),
            "",
        ),
        "last_run_step": first_text(run_item.get("step"), health_item.get("last_run_step"), ""),
        "evidence": first_text(run_item.get("log_path"), health_item.get("evidence"), ""),
        "human_action": first_text(health_item.get("human_action"), policy.get("human_action"), ""),
        "rerun": rerun_decision,
    }


def classify_completion(health_status: str, run_status: str) -> str:
    if run_status in RUN_STATUS_FAILED or health_status in HEALTH_STATUS_FAILED:
        return "failed"
    if run_status == "running" or health_status == "running":
        return "running"
    if run_status == "skipped":
        return "skipped"
    if health_status in HEALTH_STATUS_WARN:
        return "attention"
    if run_status in RUN_STATUS_DONE or health_status == "ok":
        return "completed"
    return "missing"


def completion_status_text(status: str) -> str:
    labels = {
        "completed": "已完成",
        "failed": "失败",
        "running": "运行中",
        "skipped": "已跳过",
        "attention": "需关注",
        "missing": "未记录",
    }
    return labels.get(status, status)


def first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def build_rerun_decision(
    completion_status: str,
    health_item: dict[str, Any],
    run_item: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    rerun_policy = policy.get("rerun_policy") or {}
    allowed = bool(rerun_policy.get("auto_allowed"))
    reasons = rerun_policy.get("allowed_when") or ["failed", "missing"]
    should_suggest = completion_status in set(reasons)
    risk = first_text(health_item.get("risk"), policy.get("risk"), "unknown")
    if risk == "high":
        allowed = False
    if not should_suggest:
        return {
            "suggested": False,
            "auto_allowed": allowed,
            "mode": rerun_policy.get("mode") or "report_only",
            "reason": "当前状态不需要补跑。",
        }

    if allowed:
        command = rerun_policy.get("command") or []
        return {
            "suggested": True,
            "auto_allowed": True,
            "mode": rerun_policy.get("mode") or "dry_run_plan",
            "reason": rerun_policy.get("reason") or "任务属于只读或幂等任务，可进入补跑计划。",
            "command": command,
            "dry_run": True,
            "blocked_by": [],
        }

    blocked_by = rerun_policy.get("blocked_by") or []
    if risk == "high" and "high_risk_task" not in blocked_by:
        blocked_by = [*blocked_by, "high_risk_task"]
    return {
        "suggested": True,
        "auto_allowed": False,
        "mode": rerun_policy.get("mode") or "report_only",
        "reason": rerun_policy.get("reason") or "该任务只报告，不自动补跑。",
        "blocked_by": blocked_by,
        "last_returncode": run_item.get("returncode"),
    }


def task_sort_key(item: dict[str, Any]) -> tuple[int, str]:
    rank = {
        "failed": 0,
        "running": 1,
        "attention": 2,
        "missing": 3,
        "completed": 4,
        "skipped": 5,
    }.get(item.get("status"), 6)
    return rank, item.get("id", "")


def build_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {
        "total": len(rows),
        "completed": 0,
        "failed": 0,
        "running": 0,
        "attention": 0,
        "missing": 0,
        "skipped": 0,
        "rerun_suggested": 0,
        "auto_rerun_allowed": 0,
        "report_only": 0,
    }
    for row in rows:
        status = row.get("status")
        if status in summary:
            summary[status] += 1
        rerun = row.get("rerun") or {}
        if rerun.get("suggested"):
            summary["rerun_suggested"] += 1
            if rerun.get("auto_allowed"):
                summary["auto_rerun_allowed"] += 1
            else:
                summary["report_only"] += 1
    return summary


def build_rerun_plan(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    plan = []
    for row in rows:
        rerun = row.get("rerun") or {}
        if not rerun.get("suggested"):
            continue
        plan.append(
            {
                "task_id": row["id"],
                "task_name": row["name"],
                "auto_allowed": bool(rerun.get("auto_allowed")),
                "mode": rerun.get("mode", "report_only"),
                "reason": rerun.get("reason", ""),
                "command": rerun.get("command", []),
                "dry_run": bool(rerun.get("dry_run", True)),
                "blocked_by": rerun.get("blocked_by", []),
            }
        )
    return plan


def build_wechat_text(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    problem_rows = [row for row in payload["tasks"] if row["status"] in {"failed", "attention", "missing", "running"}]
    if not problem_rows:
        return f"今天纳入监控的 {summary['total']} 个自动化任务没有发现失败。完成 {summary['completed']} 个。\n"

    lines = [
        f"这次有 {len(problem_rows)} 个自动化任务需要处理，失败 {summary['failed']} 个，需关注 {summary['attention']} 个。",
    ]
    for row in problem_rows[:6]:
        lines.append(format_problem_row(row))

    allowed = [item for item in payload["rerun_plan"] if item.get("auto_allowed")]
    if allowed:
        names = "、".join(str(item.get("task_name") or item.get("task_id")) for item in allowed[:4])
        lines.append(f"可以安全补跑的是：{names}。你说“执行补跑”时，我只会跑这些低风险或幂等任务。")
    else:
        lines.append("这次没有可以直接自动补跑的低风险任务。")

    blocked = [item for item in payload["rerun_plan"] if not item.get("auto_allowed")]
    if blocked:
        names = "、".join(str(item.get("task_name") or item.get("task_id")) for item in blocked[:4])
        lines.append(f"不能自动补跑的是：{names}。这些会碰预算、发布、订货或需要人工确认。")
    return "\n".join(lines) + "\n"


def format_problem_row(row: dict[str, Any]) -> str:
    reason = clean_sentence(row.get("failure_reason") or row.get("human_action") or "还没有拿到更细的失败原因")
    step = row.get("last_run_step") or ""
    rerun = row.get("rerun") or {}
    if rerun.get("suggested") and rerun.get("auto_allowed"):
        rerun_text = "可以补跑"
    elif rerun.get("suggested"):
        rerun_text = "不自动补跑，需要人工确认"
    else:
        rerun_text = "暂不需要补跑"
    detail = f"{row['name']}：{row['status_text']}。原因：{reason}。"
    if step:
        detail += f" 出问题的步骤：{step}。"
    detail += f" 处理：{rerun_text}。"
    return detail


def clean_sentence(value: Any) -> str:
    return str(value or "").strip().rstrip("。.")


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    config_path = Path(args.config).expanduser()
    health_path = Path(args.health).expanduser()
    runs_path = Path(args.runs).expanduser()
    config = read_json(config_path, {"tasks": []})
    health = read_json(health_path, {"tasks": []})
    runs = read_json(runs_path, {"tasks": {}})
    policies = policy_by_task(config)
    rows = task_rows(health, runs, policies)
    payload = {
        "generated_at": now_text(),
        "host": socket.gethostname(),
        "sources": {
            "config": relpath(config_path),
            "task_health": relpath(health_path),
            "task_runs": relpath(runs_path),
        },
        "safety": {
            "executes_rerun": False,
            "dry_run_plan_only": False,
            "high_risk_policy": "report_only",
        },
        "summary": build_summary(rows),
        "tasks": rows,
        "rerun_plan": build_rerun_plan(rows),
    }
    payload["wechat_text"] = build_wechat_text(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 Hermes/Mac mini 自动化任务透明化报告")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="通知任务和补跑策略配置")
    parser.add_argument("--health", default=str(DEFAULT_HEALTH_PATH), help="任务健康状态 JSON")
    parser.add_argument("--runs", default=str(DEFAULT_RUNS_PATH), help="任务运行记录 JSON")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="报告输出目录")
    parser.add_argument("--json-out", default="", help="自定义 JSON 输出路径")
    parser.add_argument("--text-out", default="", help="自定义微信文本输出路径")
    parser.add_argument("--no-write", action="store_true", help="只打印摘要，不写文件")
    args = parser.parse_args()

    payload = build_payload(args)
    if not args.no_write:
        output_dir = Path(args.output_dir).expanduser()
        json_out = Path(args.json_out).expanduser() if args.json_out else output_dir / "latest.json"
        text_out = Path(args.text_out).expanduser() if args.text_out else output_dir / "latest.txt"
        write_json(json_out, payload)
        atomic_write_text(text_out, payload["wechat_text"])
        print(f"自动化任务报告已生成：{relpath(json_out)}，{relpath(text_out)}")
    summary = payload["summary"]
    print(
        "任务透明化摘要："
        f"完成 {summary['completed']}，失败 {summary['failed']}，关注 {summary['attention']}，"
        f"可自动补跑 {summary['auto_rerun_allowed']}，只报告 {summary['report_only']}。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
