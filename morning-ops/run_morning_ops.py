from __future__ import annotations

import argparse
import contextlib
import fcntl
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent
LOG_DIR = ROOT / "logs"
LOCK_FILE = WORKSPACE / "outputs" / "locks" / "morning-ops.lock"
DAILY_RUNNER = WORKSPACE / "business-report-dashboard" / "run_daily_publish.command"
REPORT_DIR = WORKSPACE / "business-report-dashboard"
REPORT_AUTOMATION = REPORT_DIR / "chrome_cdp_reports.py"
REPORT_PROCESSOR = REPORT_DIR / "process_reports.py"
DIRECT_MEITUAN_DAILY_RUNNER = WORKSPACE / "scripts" / "download_direct_meituan_daily.py"
DIRECT_MEITUAN_REVIEW_RUNNER = WORKSPACE / "scripts" / "download_direct_meituan_reviews.py"
BALANCE_RUNNER = WORKSPACE / "store-inspection" / "run_all_balances.py"
EVIDENCE_MANIFEST_RUNNER = WORKSPACE / "scripts" / "build_store_inspection_evidence_manifest.py"
EVIDENCE_UPLOAD_RUNNER = WORKSPACE / "scripts" / "upload_store_inspection_evidence.zsh"
DAILY_FOCUS_STATUS_RUNNER = WORKSPACE / "scripts" / "build_daily_focus_status.py"
REVIEW_ACTION_STATUS_RUNNER = WORKSPACE / "scripts" / "build_review_action_status.py"
PROMO_BALANCE_STATUS_RUNNER = WORKSPACE / "scripts" / "build_promo_balance_status.py"
ELEME_BUDGET_RUNNER = WORKSPACE / "scripts" / "run_eleme_automation.zsh"
PROMO_PREVIEW_RUNNER = WORKSPACE / "scripts" / "build_promo_budget_preview.mjs"
PROMO_BUDGET_SYNC_RUNNER = WORKSPACE / "scripts" / "sync_promo_budget_overrides.py"
WORKBENCH_DATA_RUNNER = WORKSPACE / "scripts" / "build_workbench_data.py"
MORNING_COLLECTION_STATUS_RUNNER = WORKSPACE / "scripts" / "build_morning_collection_status.py"
TASK_HEALTH_RUNNER = WORKSPACE / "scripts" / "build_task_health.py"
MEITUAN_BUDGET_RUNNER = WORKSPACE / "store-inspection" / "meituan_budget_automation.py"
MEITUAN_BUDGET_CDP_RUNNER = WORKSPACE / "store-inspection" / "meituan_budget_cdp.py"
CHROME_CLEANUP_RUNNER = WORKSPACE / "scripts" / "cleanup_chrome_tabs.py"
WORKBENCH_DEPLOY_RUNNER = WORKSPACE / "scripts" / "deploy_workbench_to_cloud.zsh"
NOTIFY_RUNNER = WORKSPACE / "scripts" / "ops_notify.py"
TASK_RUN_RECORDER = WORKSPACE / "scripts" / "record_task_run.py"
RESUME_FLAG = WORKSPACE / "outputs" / "manual_resume" / "continue.flag"
NODE = Path("/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node")
REPORT_VENV_PYTHON = REPORT_DIR / ".venv" / "bin" / "python"
REPORT_PYTHON = REPORT_VENV_PYTHON if REPORT_VENV_PYTHON.exists() else Path("/usr/bin/python3")
TASK_ID = "ops.morning_collection"
DEFAULT_MEITUAN_BUDGET_TIMEOUT_SECONDS = 900


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


@contextlib.contextmanager
def morning_ops_lock(source: str):
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.log"
    with LOCK_FILE.open("a+", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.seek(0)
            holder = lock.read().strip() or "已有上午运营任务正在运行。"
            message = f"已有上午运营任务正在运行，本次不重复启动。当前锁信息：{holder}"
            print(message, file=sys.stderr, flush=True)
            with log_path.open("a", encoding="utf-8") as log:
                log.write(f"\n[{datetime.now().strftime('%F %T')}] {message}\n")
            raise SystemExit(75)
        lock.seek(0)
        lock.truncate()
        lock.write(
            "\n".join(
                [
                    f"pid={os.getpid()}",
                    f"source={source}",
                    f"started_at={datetime.now().strftime('%F %T')}",
                    f"workspace={WORKSPACE}",
                ]
            )
        )
        lock.flush()
        try:
            yield
        finally:
            lock.seek(0)
            lock.truncate()
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


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


def record_task_run(status: str, message: str, step: str, log_path: Path, *, returncode: int | None = None, **extra: str) -> None:
    args = [
        sys.executable,
        str(TASK_RUN_RECORDER),
        TASK_ID,
        status,
        "--message",
        message,
        "--step",
        step,
        "--log-path",
        str(log_path),
    ]
    if returncode is not None:
        args.extend(["--returncode", str(returncode)])
    for key, value in extra.items():
        args.extend(["--extra", f"{key}={value}"])
    try:
        subprocess.run(args, cwd=WORKSPACE, timeout=10)
    except Exception as exc:
        print(f"记录上午运营任务状态失败：{exc}", file=sys.stderr, flush=True)


def looks_like_auth_block(text: str) -> bool:
    return any(pattern in text for pattern in AUTH_BLOCK_PATTERNS)


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        print(f"环境变量 {name}={raw!r} 不是整数，使用默认值 {default}。", file=sys.stderr, flush=True)
        return default
    if value <= 0:
        print(f"环境变量 {name}={raw!r} 必须大于 0，使用默认值 {default}。", file=sys.stderr, flush=True)
        return default
    return value


def is_production_environment() -> bool:
    env = os.environ.get("AI_BUSINESS_CENTER_ENV", "").strip().lower()
    hostname = os.uname().nodename.lower()
    return env == "production" or "mini" in hostname


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
        except subprocess.TimeoutExpired as exc:
            partial = exc.stdout or ""
            output = (
                f"{partial}\n"
                f"{name}超时：超过 {timeout_seconds} 秒，已停止本步骤。\n"
            )
            log.write(output)
            returncode = 124
    if returncode == 0:
        print(f"{name}完成。", flush=True)
        return StepResult(name, returncode, output, log_path)
    message = f"{name}失败，详情见 {log_path}"
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
        timeout_seconds=120,
    )


def cleanup_chrome_sessions(label: str) -> None:
    if not CHROME_CLEANUP_RUNNER.exists():
        return
    try:
        result = subprocess.run(
            [sys.executable, str(CHROME_CLEANUP_RUNNER)],
            cwd=WORKSPACE,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=90,
        )
        output = (result.stdout or "").strip()
        print(f"{label}：{output or '完成'}", flush=True)
    except Exception as exc:
        print(f"{label}失败，已跳过：{exc}", file=sys.stderr, flush=True)


def refresh_final_status() -> None:
    for label, runner in (
        ("上午采集状态刷新", MORNING_COLLECTION_STATUS_RUNNER),
        ("任务健康状态刷新", TASK_HEALTH_RUNNER),
        ("运营总看板数据刷新", WORKBENCH_DATA_RUNNER),
    ):
        if not runner.exists():
            continue
        try:
            result = subprocess.run(
                [sys.executable, str(runner)],
                cwd=WORKSPACE,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=180,
            )
            output = (result.stdout or "").strip()
            if result.returncode == 0:
                print(f"{label}：{output or '完成'}", flush=True)
            else:
                print(f"{label}失败，已跳过：{output or result.returncode}", file=sys.stderr, flush=True)
        except Exception as exc:
            print(f"{label}失败，已跳过：{exc}", file=sys.stderr, flush=True)


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
    parser.add_argument(
        "--source",
        default=os.environ.get("MORNING_OPS_SOURCE", "scheduled"),
        help="运行来源标记，用于区分 launchd 定时、手动入口或排障补跑。",
    )
    args = parser.parse_args()
    with morning_ops_lock(args.source):
        log_path = LOG_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.log"
        budget_period = resolve_budget_period(args.budget_period)
        budget_time = BUDGET_PERIODS[budget_period]["time"]
        record_task_run(
            "running",
            "上午运营一键采集开始。",
            "初始化",
            log_path,
            mode=args.mode,
            source=args.source,
            budget_period=budget_period,
        )
        print(f"运营一键采集开始：日报 + 双平台余额巡检 + {budget_period}推广预算（{args.mode}，来源：{args.source}）。", flush=True)
        cleanup_chrome_sessions("任务开始前 Chrome 会话清理")
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
                if run_step_with_pause("直营美团评价下载", [report_python, str(DIRECT_MEITUAN_REVIEW_RUNNER), "--all"], required=False, timeout_seconds=420).returncode != 0:
                    failures.append("直营美团评价")
                if run_step_with_pause("直营美团日报下载", [report_python, str(DIRECT_MEITUAN_DAILY_RUNNER), "--all", "--submit"], required=False, timeout_seconds=600).returncode != 0:
                    failures.append("直营美团日报")
                ensure_backend_chrome(report_python)
                if run_step_with_pause("门店日报采集并发布", ["/bin/zsh", str(DAILY_RUNNER)], required=False, timeout_seconds=720).returncode != 0:
                    failures.append("门店日报")
                if run_step("日报重点状态更新", [sys.executable, str(DAILY_FOCUS_STATUS_RUNNER)], required=False, timeout_seconds=120).returncode != 0:
                    failures.append("日报重点状态")
                if run_step("评价待办状态更新", [sys.executable, str(REVIEW_ACTION_STATUS_RUNNER)], required=False, timeout_seconds=120).returncode != 0:
                    failures.append("评价待办状态")
                balance_result = run_step_with_pause("推广余额总巡检", [sys.executable, str(BALANCE_RUNNER)], required=False, timeout_seconds=420)
                if balance_result.returncode != 0:
                    if args.source == "scheduled":
                        print("推广余额总巡检失败，定时任务已跳过该项并继续后续业务。", file=sys.stderr, flush=True)
                    else:
                        failures.append("推广余额总巡检")
                run_step("巡检证据清单生成", [sys.executable, str(EVIDENCE_MANIFEST_RUNNER), "--days", "7"], required=False, timeout_seconds=120)
                if run_step("推广余额状态更新", [sys.executable, str(PROMO_BALANCE_STATUS_RUNNER)], required=False, timeout_seconds=120).returncode != 0:
                    failures.append("推广余额状态")
                if is_production_environment():
                    run_step("巡检证据上传云端", ["/bin/zsh", str(EVIDENCE_UPLOAD_RUNNER), "--days", "7"], required=False, timeout_seconds=240)
                else:
                    print("开发环境：跳过巡检证据云端上传，仅保留本地证据清单。", flush=True)
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
                    timeout_seconds=int(os.environ.get("ELEME_BUDGET_TIMEOUT_SECONDS", "1800")),
                ).returncode != 0:
                    failures.append(f"饿了么{budget_period}预算")
                meituan_budget_timeout = env_int(
                    "MEITUAN_BUDGET_TIMEOUT_SECONDS",
                    DEFAULT_MEITUAN_BUDGET_TIMEOUT_SECONDS,
                )
                if run_step_with_pause(
                    f"美团{budget_period}预算真实提交",
                    [
                        str(REPORT_PYTHON),
                        str(MEITUAN_BUDGET_CDP_RUNNER),
                        "--period",
                        budget_period,
                        "--mode",
                        "commit",
                        "--limit",
                        "all",
                    ],
                    required=False,
                    timeout_seconds=meituan_budget_timeout,
                ).returncode != 0:
                    failures.append(f"美团{budget_period}预算")
            if run_step("运营总看板数据更新", [sys.executable, str(WORKBENCH_DATA_RUNNER)], required=False).returncode != 0:
                failures.append("运营总看板")
            if args.mode == "preview":
                print("预览模式：跳过运营总看板云端发布。", flush=True)
            elif run_step("运营总看板发布腾讯云", ["/bin/zsh", str(WORKBENCH_DEPLOY_RUNNER)], required=False).returncode != 0:
                failures.append("总看板云端发布")
            cleanup_chrome_sessions("任务结束后 Chrome 会话清理")
            if failures:
                print(f"\n运营一键采集完成，但有失败项：{'、'.join(failures)}。", file=sys.stderr, flush=True)
                record_task_run(
                    "failed",
                    f"上午运营一键采集完成，但有失败项：{'、'.join(failures)}。",
                    "汇总",
                    log_path,
                    returncode=1,
                    mode=args.mode,
                    source=args.source,
                    budget_period=budget_period,
                    failures="、".join(failures),
                )
                refresh_final_status()
                return 1
            print("\n运营一键采集完成。", flush=True)
            record_task_run(
                "success",
                "上午运营一键采集完成。",
                "汇总",
                log_path,
                returncode=0,
                mode=args.mode,
                source=args.source,
                budget_period=budget_period,
            )
            refresh_final_status()
            return 0
        except Exception as exc:
            cleanup_chrome_sessions("异常后 Chrome 会话清理")
            print(f"\n运营一键采集失败：{exc}", file=sys.stderr, flush=True)
            record_task_run(
                "failed",
                f"上午运营一键采集失败：{exc}",
                "异常",
                log_path,
                returncode=1,
                mode=args.mode,
                source=args.source,
                budget_period=budget_period,
            )
            refresh_final_status()
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
