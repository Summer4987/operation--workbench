"""Bounded CDP attachment and read-only recovery of an isolated store Chrome.

Never saves platform settings. Recovery preserves the on-disk login profile and
is restricted to the production Mac mini, an exact profile/port pair, and one
graceful restart. Commit callers must leave allow_recovery=False.
"""
from __future__ import annotations

import fcntl
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
CONNECT_TIMEOUT_MS = 30_000
RECOVERY_COOLDOWN_SECONDS = 300


def process_rows() -> list[tuple[int, str]]:
    output = subprocess.check_output(["ps", "-axo", "pid=,command="], text=True, timeout=5)
    return [(int(pid), command) for line in output.splitlines() if line.strip()
            for pid, command in [line.strip().split(None, 1)]]


def matches_profile(command: str, profile: Path) -> bool:
    # ps renders arguments with spaces unquoted. Delimit with the next flag;
    # substring matching alone would also match profile suffixes/port 192240.
    return (command.startswith(str(CHROME) + " ")
            and f" --user-data-dir={profile} " in command + " ")


def matches_browser(command: str, profile: Path, port: int) -> bool:
    return (matches_profile(command, profile)
            and f" --remote-debugging-port={port} " in command + " ")


def cdp_ready(port: int) -> bool:
    try:
        with urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as response:
            return response.status == 200
    except (OSError, ValueError):
        return False


def production_recovery_allowed(profile: Path, port: int) -> bool:
    return (sys.platform == "darwin"
            and "mini" in socket.gethostname().lower()
            and ROOT.resolve() == (Path.home() / "Library/Application Support/xiong-operation/production").resolve()
            and profile.parent == Path.home() / "Library/Application Support/XiongOps"
            and profile.name.startswith("meituan-direct-")
            and port in {19223, 19224, 19225, 19226})


def restart_store_browser(account: dict) -> None:
    profile = Path(account["profile_dir"]).expanduser().resolve()
    port = int(account["debug_port"])
    if not production_recovery_allowed(profile, port):
        raise RuntimeError("浏览器自动恢复仅允许在 Mac mini 正式运行目录操作独立直营账号。")
    profile.mkdir(parents=True, exist_ok=True)
    with (profile / ".automation-recovery.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("该门店已有浏览器恢复正在进行，跳过重复重启。") from exc
        lock.seek(0)
        previous = lock.read().strip()
        if previous and time.time() - float(previous) < RECOVERY_COOLDOWN_SECONDS:
            raise RuntimeError("该门店浏览器 5 分钟内已尝试恢复，不重复重启。")
        rows = process_rows()
        if any("meituan_budget_cdp.py" in command and "--mode commit" in command
               and "--preflight" not in command for _, command in rows):
            raise RuntimeError("美团预算正式提交正在运行，暂不重启浏览器。")
        pids = [pid for pid, command in rows if matches_browser(command, profile, port)]
        if len(pids) > 1:
            raise RuntimeError(f"无法唯一确认该门店 Chrome 主进程（匹配 {len(pids)} 个），拒绝重启。")
        if not pids and (cdp_ready(port) or any(matches_profile(command, profile) for _, command in rows)):
            raise RuntimeError("门店 profile 或调试端口被不匹配的进程占用，拒绝启动重复实例。")
        lock.seek(0)
        lock.truncate()
        lock.write(str(time.time()))
        lock.flush()
        # No killall, forced termination, profile deletion or session copying.
        if pids:
            os.kill(pids[0], signal.SIGTERM)
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                if not any(pid == pids[0] for pid, _ in process_rows()):
                    break
                time.sleep(0.25)
            else:
                raise RuntimeError("该门店 Chrome 未能正常退出，未强制终止；需人工检查。")
        with open(os.devnull, "wb") as output:
            subprocess.Popen([
                str(CHROME), f"--user-data-dir={profile}", "--profile-directory=Default",
                f"--remote-debugging-port={port}", "--no-first-run", "--no-default-browser-check",
                "--new-window", "https://e.waimai.meituan.com/",
            ], stdout=output, stderr=output, start_new_session=True)
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            if cdp_ready(port):
                return
            time.sleep(0.25)
        raise RuntimeError("该门店 Chrome 重启后调试端口未就绪。")


def connect_cdp_browser(playwright, endpoint: str):
    """Retry attachment only, before callers can navigate or submit anything."""
    try:
        return playwright.chromium.connect_over_cdp(endpoint, timeout=CONNECT_TIMEOUT_MS)
    except Exception:
        # A live port/WebSocket does not mean Chrome finished attaching its targets.
        print("Chrome CDP 接入未完成，等待后重试一次。", flush=True)
        time.sleep(1)
        return playwright.chromium.connect_over_cdp(endpoint, timeout=CONNECT_TIMEOUT_MS)


def connect_store_browser(playwright, account: dict, *, allow_recovery: bool = False):
    endpoint = f"http://127.0.0.1:{int(account['debug_port'])}"
    try:
        return connect_cdp_browser(playwright, endpoint)
    except Exception as exc:
        # Login/selector/business errors never reach this connection-only handler.
        if not allow_recovery:
            raise
        print(f"直营 Chrome 接入异常：{account.get('id')}；尝试一次独立浏览器恢复。", flush=True)
        try:
            restart_store_browser(account)
        except Exception as recovery_error:
            raise RuntimeError(f"CDP 接入失败；浏览器恢复未完成：{recovery_error}") from exc
        browser = playwright.chromium.connect_over_cdp(endpoint, timeout=CONNECT_TIMEOUT_MS)
        print(f"直营 Chrome 已恢复连接：{account.get('id')}；继续只读预检。", flush=True)
        return browser
