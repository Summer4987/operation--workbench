#!/usr/bin/env python3
"""Install the daily 21:30 order-margin job from verified GitHub main."""
from datetime import datetime
import os
from pathlib import Path
import plistlib
import shlex
import socket
import subprocess
import sys

from daily_order_margin import COST_INPUT, Costs, RUNTIME

LABEL = "com.summer.operation.order-margin"
SOURCE = Path(__file__).resolve().parents[1]


def point_publisher_at_release():
    launcher = Path.home() / "Library/Scripts/xiong-operation/deploy_workbench_to_cloud.zsh"
    original = launcher.read_text()
    source_line = "export OPERATION_UI_SOURCE_ROOT=" + shlex.quote(str(SOURCE))
    exec_line = "exec /bin/zsh " + shlex.quote(str(SOURCE / "scripts/deploy_workbench_to_cloud.zsh")) + ' "$@"'
    lines = original.splitlines()
    current_sources = [line for line in lines if line.startswith("export OPERATION_UI_SOURCE_ROOT=")]
    current_commands = [line for line in lines if line.startswith("exec /bin/zsh ") and "deploy_workbench_to_cloud.zsh" in line]
    if len(current_sources) != 1 or len(current_commands) != 1:
        raise RuntimeError("未识别到现有工作台发布入口")
    updated = "\n".join(source_line if line == current_sources[0] else exec_line if line == current_commands[0] else line
                        for line in lines) + "\n"
    if updated == original:
        return
    backup = launcher.with_name(launcher.name + ".before-order-margin")
    if not backup.exists():
        backup.write_text(original)
        backup.chmod(0o700)
    staging = launcher.with_suffix(".order-margin.tmp")
    staging.write_text(updated)
    staging.chmod(0o700)
    staging.replace(launcher)


def main():
    if sys.platform != "darwin" or "mini" not in socket.gethostname().lower():
        raise SystemExit("生产定时任务只能在 Mac mini 安装")
    if datetime.now().astimezone().utcoffset().total_seconds() != 28800:
        raise SystemExit("Mac mini 系统时区必须为北京时间")

    def git(*args):
        return subprocess.check_output(["git", "-C", str(SOURCE), *args], text=True).strip()

    if (git("branch", "--show-current") != "main" or git("rev-parse", "HEAD") != git("rev-parse", "origin/main")
            or git("status", "--porcelain", "--untracked-files=no")):
        raise SystemExit("请从已同步 GitHub main 的干净检出安装")

    python = RUNTIME / "business-report-dashboard/.venv/bin/python"
    if not python.is_file():
        raise SystemExit("缺少正式 Python 环境")
    Costs(COST_INPUT)
    point_publisher_at_release()
    directory = Path.home() / "Library/LaunchAgents"
    logs = Path.home() / "Library/Logs/xiong-operation/order_margin"
    directory.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    target = directory / f"{LABEL}.plist"
    temporary = target.with_suffix(".tmp")
    temporary.write_bytes(plistlib.dumps(dict(
        Label=LABEL, ProgramArguments=[str(python), str(SOURCE / "scripts/daily_order_margin.py")],
        WorkingDirectory=str(RUNTIME), StartCalendarInterval=dict(Hour=21, Minute=30),
        EnvironmentVariables=dict(TZ="Asia/Shanghai", PYTHONUNBUFFERED="1", PYTHONNOUSERSITE="1",
                                  PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"),
        StandardOutPath=str(logs / "order-margin.out.log"), StandardErrorPath=str(logs / "order-margin.err.log"),
        ProcessType="Background",
    )))
    subprocess.run(["plutil", "-lint", str(temporary)], check=True)
    temporary.replace(target)
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", f"{domain}/{LABEL}"], capture_output=True)
    subprocess.run(["launchctl", "bootstrap", domain, str(target)], check=True)
    subprocess.run(["launchctl", "enable", f"{domain}/{LABEL}"], check=True)
    subprocess.run(["launchctl", "print", f"{domain}/{LABEL}"], check=True)


if __name__ == "__main__":
    main()
