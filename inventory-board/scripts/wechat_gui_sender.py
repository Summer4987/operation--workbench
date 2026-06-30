#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any


APPLESCRIPT = r'''
on run argv
  set targetName to item 1 of argv
  set messageText to item 2 of argv
  set filePath to item 3 of argv
  set shouldSendFile to item 4 of argv

  tell application "WeChat" to activate
  delay 0.8

  tell application "System Events"
    if UI elements enabled is false then
      error "macOS 辅助功能未授权，无法自动操作微信"
    end if

    tell process "WeChat"
      set frontmost to true
      keystroke "f" using command down
      delay 0.4
      set the clipboard to targetName
      keystroke "v" using command down
      delay 0.8
      key code 36
      delay 0.8

      if messageText is not "" then
        set the clipboard to messageText
        keystroke "v" using command down
        delay 0.2
        key code 36
        delay 0.8
      end if

      if shouldSendFile is "1" then
        set the clipboard to (POSIX file filePath)
        keystroke "v" using command down
        delay 1.2
        key code 36
        delay 0.8
      end if
    end tell
  end tell
end run
'''


HEALTHCHECK_SCRIPT = r'''
tell application "System Events"
  if UI elements enabled is false then
    error "macOS 辅助功能未授权，无法自动操作微信"
  end if
end tell
tell application "System Events"
  set wechatRunning to exists process "WeChat"
end tell
return wechatRunning
'''


def run_health_check() -> dict[str, Any]:
    result = subprocess.run(
        ["osascript", "-e", HEALTHCHECK_SCRIPT],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=20,
    )
    output = (result.stdout or "").strip()
    return {
        "ok": result.returncode == 0 and output.lower() == "true",
        "returncode": result.returncode,
        "output": output,
    }


def send(target: str, message: str, file_path: Path | None, *, dry_run: bool = False) -> dict[str, Any]:
    clean_target = target.strip()
    if not clean_target:
        raise ValueError("target is required")
    clean_message = message.strip()
    expanded_file = file_path.expanduser() if file_path else None
    if expanded_file and not expanded_file.exists():
        raise FileNotFoundError(str(expanded_file))
    if not clean_message and not expanded_file:
        raise ValueError("message or file is required")

    payload = {
        "target": clean_target,
        "message": clean_message,
        "file": str(expanded_file) if expanded_file else "",
    }
    if dry_run:
        return {"ok": True, "dry_run": True, **payload}

    result = subprocess.run(
        [
            "osascript",
            "-",
            clean_target,
            clean_message,
            str(expanded_file or ""),
            "1" if expanded_file else "0",
        ],
        input=APPLESCRIPT,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=60,
    )
    return {
        "ok": result.returncode == 0,
        "dry_run": False,
        "returncode": result.returncode,
        "output": (result.stdout or "").strip(),
        **payload,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="在 Mac mini 上通过已登录微信 GUI 搜索群名并发送文本/文件")
    parser.add_argument("--target", default="皮皮球球备忘录", help="微信群或联系人名称")
    parser.add_argument("--message", default="", help="要发送的文本")
    parser.add_argument("--file", default="", help="要发送的本地文件路径")
    parser.add_argument("--health-check", action="store_true", help="只检查辅助功能权限和微信是否运行")
    parser.add_argument("--dry-run", action="store_true", help="只输出计划，不操作微信")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.health_check:
        payload = run_health_check()
    else:
        payload = send(
            args.target,
            args.message,
            Path(args.file) if args.file else None,
            dry_run=args.dry_run,
        )

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("ok" if payload.get("ok") else f"failed: {payload.get('output', '')}")
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
