#!/usr/bin/env python3
"""Install the 21:00 review from a clean GitHub main checkout on Mac mini."""
import argparse
from datetime import datetime
import os
from pathlib import Path
import plistlib
import socket
import shlex
import subprocess
import sys

LABEL = "com.summer.operation.meituan-roi-review"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, default=Path.home()/"Library/Application Support/xiong-operation/production")
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    if sys.platform != "darwin" or "mini" not in socket.gethostname().lower():
        parser.error("正式定时任务只能安装在 Mac mini")
    if datetime.now().astimezone().utcoffset().total_seconds() != 28800:
        parser.error("launchd日历任务要求生产主机系统时区为北京时间")
    def git(*parts):
        return subprocess.check_output(["git", "-C", str(source), *parts], text=True).strip()
    if git("branch", "--show-current") != "main" or git("rev-parse", "HEAD") != git("rev-parse", "origin/main"):
        parser.error("必须从已拉取 GitHub main 的正式检出安装")
    if git("status", "--porcelain", "--untracked-files=no"):
        parser.error("安装来源存在未提交代码改动，拒绝安装")
    runtime = args.runtime_root.resolve()
    python = runtime/"business-report-dashboard/.venv/bin/python"
    if not python.exists():
        parser.error("生产Python环境不存在")
    # Existing hourly publishers also send index.html. Use the GitHub checkout
    # for UI assets so a later data-only publication cannot remove the new page.
    launcher = Path.home()/"Library/Scripts/xiong-operation/deploy_workbench_to_cloud.zsh"
    if launcher.exists():
        backup = launcher.with_name(launcher.name+".before-roi")
        if not backup.exists():
            backup.write_bytes(launcher.read_bytes())
            backup.chmod(0o700)
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text("#!/bin/zsh\nset -euo pipefail\n" +
                        "export OPERATION_UI_SOURCE_ROOT=" + shlex.quote(str(source)) + "\n" +
                        "export OPERATION_ROOT=\"${OPERATION_ROOT:-" + str(runtime) + "}\"\n" +
                        "exec /bin/zsh " + shlex.quote(str(source/"scripts/deploy_workbench_to_cloud.zsh")) + ' "$@"\n')
    launcher.chmod(0o700)
    directory = Path.home()/"Library/LaunchAgents"
    logs = Path.home()/"Library/Logs/xiong-operation/promo_roi"
    directory.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    plist = directory/(LABEL+".plist")
    payload = dict(Label=LABEL, ProgramArguments=[str(python), str(source/"scripts/meituan_roi_review.py"), "--runtime-root", str(runtime), "--publish"],
                   WorkingDirectory=str(runtime), StartCalendarInterval=dict(Hour=21, Minute=0),
                   EnvironmentVariables=dict(TZ="Asia/Shanghai", PYTHONUNBUFFERED="1", PYTHONNOUSERSITE="1", AI_BUSINESS_CENTER_ENV="production", PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"),
                   StandardOutPath=str(logs/"review.out.log"), StandardErrorPath=str(logs/"review.err.log"), ProcessType="Background")
    temporary = plist.with_suffix(".tmp")
    temporary.write_bytes(plistlib.dumps(payload))
    subprocess.run(["plutil", "-lint", str(temporary)], check=True)
    temporary.replace(plist)
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain+"/"+LABEL], capture_output=True)
    subprocess.run(["launchctl", "bootstrap", domain, str(plist)], check=True)
    subprocess.run(["launchctl", "enable", domain+"/"+LABEL], check=True)
    subprocess.run(["launchctl", "print", domain+"/"+LABEL], check=True)
    print("美团ROI复盘已安装：每天北京时间21:00；未提前触发正式任务。")


if __name__ == "__main__":
    main()
