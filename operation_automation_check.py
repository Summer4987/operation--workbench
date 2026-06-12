from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


DEFAULT_ROOT = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("OPERATION_CENTER_ROOT", str(DEFAULT_ROOT))).expanduser().resolve()
CDP_PORT = 9222
CDP_URL = f"http://127.0.0.1:{CDP_PORT}/json/version"
WORKBENCH_HOST = os.environ.get("OPERATION_CLOUD_SERVER", "ubuntu@139.155.148.169")
IDENTITY_FILE = Path(os.environ.get("OPERATION_CLOUD_IDENTITY_FILE", str(Path.home() / ".ssh" / "xiong_operation_cloud_ed25519")))


def add_issue(issues: list[dict], category: str, status: str, message: str) -> None:
    issues.append({"category": category, "status": status, "message": message})


def port_listening(port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1.5)
    try:
        if sock.connect_ex(("127.0.0.1", port)) == 0:
            return True
    finally:
        sock.close()

    try:
        result = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
    except Exception:
        return False
    return result.returncode == 0 and str(result.stdout or "").strip() != ""


def check_required_paths(issues: list[dict]) -> None:
    required_paths = [
        ROOT / "morning-ops" / "上午运营一键采集.command",
        ROOT / "morning-ops" / "run_morning_ops.py",
        ROOT / "business-report-dashboard" / "chrome_cdp_reports.py",
        ROOT / "store-inspection" / "run_all_balances.py",
        ROOT / "scripts" / "deploy_workbench_to_cloud.zsh",
    ]
    missing = [str(path.relative_to(ROOT)) for path in required_paths if not path.exists()]
    if missing:
        add_issue(issues, "path", "blocked", f"缺少关键脚本：{'、'.join(missing)}")


def check_cdp(issues: list[dict]) -> None:
    listening = port_listening(CDP_PORT)
    if not listening:
        add_issue(issues, "chrome_debug_port", "blocked", f"Chrome 调试端口 {CDP_PORT} 未监听。")
        return
    try:
        with urlopen(CDP_URL, timeout=2) as response:
            if response.status != 200:
                add_issue(issues, "chrome_local_network", "blocked", f"Chrome 调试端口返回异常状态：{response.status}")
    except PermissionError:
        add_issue(issues, "chrome_local_network", "blocked", "当前进程无法访问本地 Chrome 调试端口；需要为 Terminal 或 Codex 放行本地网络。")
    except URLError as exc:
        reason = getattr(exc, "reason", None)
        if isinstance(reason, PermissionError):
            add_issue(issues, "chrome_local_network", "blocked", "当前进程无法访问本地 Chrome 调试端口；需要为 Terminal 或 Codex 放行本地网络。")
        elif reason:
            add_issue(issues, "chrome_local_network", "warning", f"Chrome 调试端口已监听，但 HTTP 探测失败：{reason}")
        else:
            add_issue(issues, "chrome_local_network", "warning", f"Chrome 调试端口已监听，但 HTTP 探测失败：{exc}")
    except Exception as exc:
        if isinstance(exc, PermissionError):
            add_issue(issues, "chrome_local_network", "blocked", "当前进程无法访问本地 Chrome 调试端口；需要为 Terminal 或 Codex 放行本地网络。")
        else:
            add_issue(issues, "chrome_local_network", "warning", f"Chrome 调试端口探测异常：{exc}")


def check_screen_recording(issues: list[dict]) -> None:
    with tempfile.NamedTemporaryFile(prefix="operation-screen-", suffix=".png", delete=False) as handle:
        path = Path(handle.name)
    try:
        result = subprocess.run(
            ["screencapture", "-x", str(path)],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            add_issue(issues, "screen_recording", "blocked", f"屏幕录制不可用：{detail or 'screencapture 返回非 0'}")
    except Exception as exc:
        add_issue(issues, "screen_recording", "blocked", f"屏幕录制探测失败：{exc}")
    finally:
        if path.exists():
            path.unlink()


def check_accessibility(issues: list[dict]) -> None:
    try:
        result = subprocess.run(
            ["osascript", "-e", 'tell application "System Events" to get UI elements enabled'],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        if "true" not in (result.stdout or "").lower():
            detail = (result.stderr or result.stdout or "").strip()
            add_issue(issues, "accessibility", "blocked", f"辅助功能不可用：{detail or 'System Events 未返回 true'}")
    except Exception as exc:
        add_issue(issues, "accessibility", "blocked", f"辅助功能探测失败：{exc}")


def check_ssh_publish(issues: list[dict]) -> None:
    ssh_args = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ConnectTimeout=5",
    ]
    if IDENTITY_FILE.exists():
        ssh_args.extend(["-i", str(IDENTITY_FILE)])
    ssh_args.extend([WORKBENCH_HOST, "exit"])
    try:
        result = subprocess.run(ssh_args, cwd=ROOT, text=True, capture_output=True)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            add_issue(issues, "cloud_publish", "blocked", f"云端 SSH 不可用：{detail or f'退出码 {result.returncode}'}")
    except Exception as exc:
        add_issue(issues, "cloud_publish", "blocked", f"云端 SSH 探测失败：{exc}")


def build_report() -> dict:
    issues: list[dict] = []
    check_required_paths(issues)
    check_cdp(issues)
    check_screen_recording(issues)
    check_accessibility(issues)
    check_ssh_publish(issues)
    blockers = [issue for issue in issues if issue["status"] == "blocked"]
    warnings = [issue for issue in issues if issue["status"] == "warning"]
    return {
        "generated_at": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "root": str(ROOT),
        "blockers": blockers,
        "warnings": warnings,
        "ok": not blockers,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="上午运营自动化体检")
    parser.add_argument("--json", action="store_true", help="输出 JSON，便于主流程解析")
    args = parser.parse_args()

    report = build_report()
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        if report["blockers"]:
            print("系统阻塞项：")
            for issue in report["blockers"]:
                print(f"- [{issue['category']}] {issue['message']}")
        else:
            print("系统阻塞项：无")
        if report["warnings"]:
            print("补充提醒：")
            for issue in report["warnings"]:
                print(f"- [{issue['category']}] {issue['message']}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
