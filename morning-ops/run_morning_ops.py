from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent
sys.path.insert(0, str(WORKSPACE / "scripts"))

from task_run_state import classify_failure_text, record_task_event  # noqa: E402

LOG_DIR = ROOT / "logs"
DAILY_RUNNER = WORKSPACE / "business-report-dashboard" / "run_daily_publish.command"
REPORT_DIR = WORKSPACE / "business-report-dashboard"
REPORT_AUTOMATION = REPORT_DIR / "chrome_cdp_reports.py"
REPORT_PROCESSOR = REPORT_DIR / "process_reports.py"
BALANCE_RUNNER = WORKSPACE / "store-inspection" / "run_all_balances.py"
ELEME_BUDGET_RUNNER = WORKSPACE / "scripts" / "run_eleme_automation.zsh"
PROMO_PREVIEW_RUNNER = WORKSPACE / "scripts" / "build_promo_budget_preview.mjs"
PROMO_BUDGET_SYNC_RUNNER = WORKSPACE / "scripts" / "sync_promo_budget_overrides.py"
WORKBENCH_DATA_RUNNER = WORKSPACE / "scripts" / "build_workbench_data.py"
MEITUAN_BUDGET_RUNNER = WORKSPACE / "store-inspection" / "meituan_budget_automation.py"
MEITUAN_BUDGET_CDP_RUNNER = WORKSPACE / "store-inspection" / "meituan_budget_cdp.py"
WORKBENCH_DEPLOY_RUNNER = WORKSPACE / "scripts" / "deploy_workbench_to_cloud.zsh"
NOTIFY_RUNNER = WORKSPACE / "scripts" / "ops_notify.py"
RESUME_FLAG = WORKSPACE / "outputs" / "manual_resume" / "continue.flag"
NODE = Path("/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node")
REPORT_VENV_PYTHON = REPORT_DIR / ".venv" / "bin" / "python"
REPORT_PYTHON = REPORT_VENV_PYTHON if REPORT_VENV_PYTHON.exists() else Path("/usr/bin/python3")


BUDGET_PERIODS = {
    "午餐": {"time": "10:30", "label": "午餐"},
    "晚餐": {"time": "17:30", "label": "晚餐"},
}

AUTH_BLOCK_PATTERNS = [
    "验证码",
    "安全验证",
    "安全中心",
    "风控",
    "未登录",
    "登录页",
    "请确认日常 Chrome 已登录",
    "请先在本地 Chrome 打开",
    "没有进入美团",
    "没有找到“立即充值”",
    "UNAUTHORIZED",
    "Permission denied",
]


@dataclass
class StepResult:
    name: str
    returncode: int
    output: str
    log_path: Path


def resolve_budget_period(value: str = "auto") -> str:
    if value in BUDGET_PERIODS:
        return value
    now = datetime.now().time()
    return "午餐" if now.hour < 15 else "晚餐"


def notify(text: str) -> None:
    try:
        subprocess.run([sys.executable, str(NOTIFY_RUNNER), text], cwd=WORKSPACE, timeout=12)
    except Exception:
        pass


def looks_like_auth_block(text: str) -> bool:
    return any(pattern in text for pattern in AUTH_BLOCK_PATTERNS)


def wait_for_manual_resume(reason: str, *, timeout_minutes: int = 60) -> bool:
    RESUME_FLAG.parent.mkdir(parents=True, exist_ok=True)
    pause_started = time.time()
    message = "\n".join(
        [
            "【上午运营自动化暂停】",
            reason,
            "请在 Mac mini 的 Chrome 里完成登录/验证码/安全验证。",
            "处理完成后，双击：morning-ops/我已处理验证码继续.command",
            f"最多等待 {timeout_minutes} 分钟。",
        ]
    )
    print(message, flush=True)
    notify(message)
    deadline = pause_started + timeout_minutes * 60
    while time.time() < deadline:
        if RESUME_FLAG.exists() and RESUME_FLAG.stat().st_mtime >= pause_started:
            resumed = "已收到人工继续信号，自动化继续执行。"
            print(resumed, flush=True)
            notify(f"【上午运营自动化继续】{resumed}")
            return True
        time.sleep(10)
    timeout_message = "等待人工接管超时，上午运营自动化停止。"
    print(timeout_message, file=sys.stderr, flush=True)
    notify(f"【上午运营自动化停止】{timeout_message}")
    return False


def run_step(name: str, args: list[str], *, required: bool = True, timeout_seconds: int | None = None) -> StepResult:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.log"
    print(f"\n== {name} ==", flush=True)
    record_task_event("ops.morning_collection", "running", message=f"正在执行：{name}", step=name, log_path=log_path)
    output = ""
    returncode = 0
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\n[{datetime.now().strftime('%F %T')}] {name}\n")
        try:
            result = subprocess.run(
                args,
                cwd=WORKSPACE,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout_seconds,
            )
            output = result.stdout or ""
            returncode = result.returncode
            log.write(output)
        except subprocess.TimeoutExpired:
            output = f"\n{name}超时：超过 {timeout_seconds} 秒，已停止本步骤。\n"
            log.write(output)
            returncode = 124
    if returncode == 0:
        print(f"{name}完成。", flush=True)
        record_task_event("ops.morning_collection", "running", message=f"{name}完成，继续后续步骤。", step=name, log_path=log_path, returncode=returncode)
        return StepResult(name, returncode, output, log_path)
    message = f"{name}失败，详情见 {log_path}"
    record_task_event(
        "ops.morning_collection",
        "failed",
        message=message,
        step=name,
        log_path=log_path,
        returncode=returncode,
        failure_type=classify_failure_text(output, returncode),
    )
    if required:
        raise RuntimeError(message)
    print(message, file=sys.stderr, flush=True)
    return StepResult(name, returncode, output, log_path)


def run_step_with_pause(name: str, args: list[str], *, required: bool = True, timeout_seconds: int | None = None) -> StepResult:
    result = run_step(name, args, required=required, timeout_seconds=timeout_seconds)
    if result.returncode != 0 and looks_like_auth_block(result.output):
        reason = f"{name}遇到登录/验证码/安全验证问题，已跳过。日志：{result.log_path}"
        print(reason, file=sys.stderr, flush=True)
        notify(f"【上午运营自动化跳过】{reason}")
    return result


def ensure_backend_chrome(report_python: str) -> None:
    run_step(
        "启动/检查后台 Chrome",
        [report_python, str(REPORT_AUTOMATION), "start-chrome"],
        required=False,
        timeout_seconds=30,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="运营一键采集")
    parser.add_argument(
        "--budget-period",
        choices=["auto", "午餐", "晚餐"],
        default="auto",
        help="预算时段：auto 按当前时间判断，15:00 前午餐，15:00 后晚餐。",
    )
    parser.add_argument(
        "--mode",
        choices=["commit", "preview"],
        default="commit",
        help="commit 正式执行预算和云端发布；preview 只做安全预演，不保存预算、不上传云端。",
    )
    args = parser.parse_args()
    budget_period = resolve_budget_period(args.budget_period)
    budget_time = BUDGET_PERIODS[budget_period]["time"]
    print(f"运营一键采集开始：日报 + 双平台余额巡检 + {budget_period}推广预算（{args.mode}）。", flush=True)
    record_task_event(
        "ops.morning_collection",
        "running",
        message=f"运营一键采集开始：{budget_period}推广预算（{args.mode}）。",
        step="start",
        extra={"mode": args.mode, "budget_period": budget_period},
    )
    failures = []
    try:
        report_python = str(REPORT_PYTHON if REPORT_PYTHON.exists() else Path(sys.executable))
        if args.mode == "preview":
            print("预览模式：跳过平台评价下载、日报后台采集、余额巡检，不打开外卖后台页面。", flush=True)
            if run_step("本地门店日报生成", [report_python, str(REPORT_PROCESSOR)], required=False).returncode != 0:
                failures.append("本地门店日报")
        else:
            ensure_backend_chrome(report_python)
            if run_step_with_pause("双平台评价下载", [report_python, str(REPORT_AUTOMATION), "download-reviews-and-process"], required=False, timeout_seconds=240).returncode != 0:
                failures.append("双平台评价")
            ensure_backend_chrome(report_python)
            if run_step_with_pause("门店日报采集并发布", ["/bin/zsh", str(DAILY_RUNNER)], required=False, timeout_seconds=720).returncode != 0:
                failures.append("门店日报")
            if run_step_with_pause("推广余额总巡检", [sys.executable, str(BALANCE_RUNNER)], required=False, timeout_seconds=420).returncode != 0:
                failures.append("推广余额总巡检")
        if run_step("同步云端预算配置", [sys.executable, str(PROMO_BUDGET_SYNC_RUNNER)], required=False).returncode != 0:
            failures.append("预算配置同步")
        node = str(NODE if NODE.exists() else "node")
        if run_step("推广预算初始化预览", [node, str(PROMO_PREVIEW_RUNNER)], required=False).returncode != 0:
            failures.append("推广预算预览")
        if args.mode == "preview":
            print("预览模式：跳过双平台预算页面检查和保存。", flush=True)
        else:
            if run_step_with_pause(
                f"饿了么{budget_period}预算真实提交",
                ["/bin/zsh", str(ELEME_BUDGET_RUNNER), "--time", budget_time, "--mode", "commit", "--limit", "all"],
                required=False,
                timeout_seconds=300,
            ).returncode != 0:
                failures.append(f"饿了么{budget_period}预算")
            if run_step_with_pause(f"美团{budget_period}预算真实提交", [str(REPORT_PYTHON), str(MEITUAN_BUDGET_CDP_RUNNER), "--period", budget_period], required=False, timeout_seconds=360).returncode != 0:
                failures.append(f"美团{budget_period}预算")
        if run_step("运营总看板数据更新", [sys.executable, str(WORKBENCH_DATA_RUNNER)], required=False).returncode != 0:
            failures.append("运营总看板")
        if args.mode == "preview":
            print("预览模式：跳过运营总看板云端发布。", flush=True)
        elif run_step("运营总看板发布腾讯云", ["/bin/zsh", str(WORKBENCH_DEPLOY_RUNNER)], required=False).returncode != 0:
            failures.append("总看板云端发布")
        if failures:
            print(f"\n运营一键采集完成，但有失败项：{'、'.join(failures)}。", file=sys.stderr, flush=True)
            record_task_event(
                "ops.morning_collection",
                "failed",
                message=f"完成但有失败项：{'、'.join(failures)}。",
                step="finish",
                failure_type="partial_failed",
                extra={"failures": failures},
            )
            return 1
        print("\n运营一键采集完成。", flush=True)
        record_task_event("ops.morning_collection", "success", message="运营一键采集完成。", step="finish", extra={"mode": args.mode, "budget_period": budget_period})
        return 0
    except Exception as exc:
        print(f"\n运营一键采集失败：{exc}", file=sys.stderr, flush=True)
        record_task_event("ops.morning_collection", "failed", message=f"运营一键采集失败：{exc}", step="exception", failure_type=classify_failure_text(str(exc)))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
