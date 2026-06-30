from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from task_run_state import classify_failure_text, record_task_event


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG_DIR = ROOT / "outputs" / "agent_task_wrapper" / "logs"


def choose_python() -> str:
    return sys.executable or os.environ.get("PYTHON", "python3")


def run_followup(name: str, command: Sequence[str]) -> int:
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode != 0:
        print(f"后续步骤失败：{name}，退出码 {result.returncode}", file=sys.stderr)
    return result.returncode


def refresh_reports(*, skip_health: bool = False, skip_monitor: bool = False) -> None:
    python = choose_python()
    if not skip_health:
        run_followup("生成任务健康状态", [python, str(ROOT / "scripts" / "build_task_health.py")])
    if not skip_monitor:
        run_followup("生成自动化透明化报告", [python, str(ROOT / "scripts" / "agent_task_monitor.py")])


def append_log(log_path: Path, text: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(text)


def run_task(args: argparse.Namespace) -> int:
    command = args.command
    if not command:
        raise SystemExit("缺少要运行的命令；用法：agent_task_wrapper.py TASK_ID -- command ...")

    log_path = Path(args.log_path).expanduser() if args.log_path else DEFAULT_LOG_DIR / f"{args.task_id}.log"
    display_command = " ".join(shlex.quote(part) for part in command)
    step = args.step or "执行任务"
    record_task_event(
        args.task_id,
        "running",
        message=args.start_message or f"任务开始：{display_command}",
        step=step,
        log_path=log_path,
        extra={"wrapped_command": command},
    )
    append_log(log_path, f"\n[{args.task_id}] START {display_command}\n")

    try:
        with log_path.open("a", encoding="utf-8") as handle:
            result = subprocess.run(command, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT)
    except FileNotFoundError as exc:
        message = f"任务命令不存在：{exc.filename}"
        record_task_event(
            args.task_id,
            "failed",
            message=message,
            step=step,
            log_path=log_path,
            returncode=127,
            failure_type="command_not_found",
            extra={"wrapped_command": command},
        )
        refresh_reports(skip_health=args.skip_health_refresh, skip_monitor=args.skip_monitor_refresh)
        return 127

    if result.returncode == 0:
        record_task_event(
            args.task_id,
            "success",
            message=args.success_message or "任务完成。",
            step=step,
            log_path=log_path,
            returncode=0,
            extra={"wrapped_command": command},
        )
    else:
        message = args.failure_message or f"任务失败，退出码 {result.returncode}。"
        record_task_event(
            args.task_id,
            "failed",
            message=message,
            step=step,
            log_path=log_path,
            returncode=result.returncode,
            failure_type=classify_failure_text(message, result.returncode),
            extra={"wrapped_command": command},
        )

    refresh_reports(skip_health=args.skip_health_refresh, skip_monitor=args.skip_monitor_refresh)
    append_log(log_path, f"[{args.task_id}] END rc={result.returncode}\n")
    return result.returncode


def split_argv(argv: list[str]) -> tuple[list[str], list[str]]:
    if "--" not in argv:
        return argv, []
    divider = argv.index("--")
    return argv[:divider], argv[divider + 1 :]


def main() -> int:
    wrapper_argv, command = split_argv(sys.argv[1:])
    parser = argparse.ArgumentParser(
        description="包装 Mac mini 自动化任务：记录运行状态，任务结束后刷新 Hermes 透明化报告。"
    )
    parser.add_argument("task_id", help="notification_tasks.json / task_runs 使用的任务 ID")
    parser.add_argument("--step", default="", help="运行步骤名称")
    parser.add_argument("--log-path", default="", help="任务日志路径；默认写入 outputs/agent_task_wrapper/logs/")
    parser.add_argument("--start-message", default="", help="开始状态说明")
    parser.add_argument("--success-message", default="", help="成功状态说明")
    parser.add_argument("--failure-message", default="", help="失败状态说明")
    parser.add_argument("--skip-health-refresh", action="store_true", help="不刷新 outputs/task_health/latest.json")
    parser.add_argument("--skip-monitor-refresh", action="store_true", help="不刷新自动化透明化报告")
    args = parser.parse_args(wrapper_argv)
    args.command = command
    return run_task(args)


if __name__ == "__main__":
    raise SystemExit(main())
