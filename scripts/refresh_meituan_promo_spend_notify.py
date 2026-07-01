#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "meituan_promo_spend"
LATEST_TEXT_PATH = OUTPUT_DIR / "latest.txt"
LOG_PATH = OUTPUT_DIR / "refresh_notify.log"
PLAYWRIGHT_PYTHON = ROOT / "business-report-dashboard" / ".venv" / "bin" / "python"
HERMES_BIN = Path.home() / ".local" / "bin" / "hermes"


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def append_log(message: str) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"[{now_text()}] {message}\n")


def run_query(timeout_seconds: int) -> tuple[bool, str]:
    python_bin = PLAYWRIGHT_PYTHON if PLAYWRIGHT_PYTHON.exists() else Path("python3")
    try:
        result = subprocess.run(
            [str(python_bin), "scripts/meituan_promo_spend_query.py", "--quiet"],
            cwd=str(ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        return False, f"美团推广消耗实时采集超过 {timeout_seconds} 秒，已停止等待。\n{output}".strip()
    output = (result.stdout or "").strip()
    return result.returncode == 0, output or f"美团推广消耗采集没有返回内容，退出码 {result.returncode}。"


def send_weixin(text: str, target: str) -> tuple[bool, str]:
    if not HERMES_BIN.exists():
        return False, f"Hermes CLI 不存在：{HERMES_BIN}"
    try:
        result = subprocess.run(
            [str(HERMES_BIN), "send", "--to", target, text],
            cwd=str(ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=45,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, "Hermes 微信发送超过 45 秒。"
    return result.returncode == 0, (result.stdout or "").strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="后台刷新美团推广消耗并通过 Hermes 微信回报")
    parser.add_argument("--reason", default="", help="用户原始请求")
    parser.add_argument("--target", default="weixin", help="Hermes send 目标")
    parser.add_argument("--timeout", type=int, default=180, help="采集超时时间")
    parser.add_argument("--no-send", action="store_true", help="只刷新并保存结果，不发送微信")
    args = parser.parse_args()

    append_log(f"start reason={args.reason!r}")
    ok, output = run_query(args.timeout)
    prefix = "美团推广消耗实时查询完成。" if ok else "美团推广消耗实时查询失败。"
    message = f"{prefix}\n{output}".strip()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_TEXT_PATH.write_text(message + "\n", encoding="utf-8")
    append_log(f"query ok={ok} chars={len(output)}")

    if args.no_send:
        print(message)
        return 0 if ok else 1

    delivered, delivery_output = send_weixin(message, args.target)
    append_log(f"send delivered={delivered} output={delivery_output}")
    print(message)
    if not delivered:
        print(f"微信发送失败，结果已保存：{LATEST_TEXT_PATH}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
