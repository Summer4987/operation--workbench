#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any


DEFAULT_CUA_BIN = Path.home() / ".local/bin/cua-driver"
WECHAT_APPS = {"微信", "WeChat"}


OCR_SWIFT = r'''
import Foundation
import Vision
import AppKit

let path = CommandLine.arguments[1]
let url = URL(fileURLWithPath: path)
guard let image = NSImage(contentsOf: url),
      let tiff = image.tiffRepresentation,
      let bitmap = NSBitmapImageRep(data: tiff),
      let cg = bitmap.cgImage else {
  fputs("failed to load image\n", stderr)
  exit(1)
}

var rows: [[String: Any]] = []
let request = VNRecognizeTextRequest { request, error in
  if let error = error {
    fputs("ocr error: \(error)\n", stderr)
    exit(2)
  }
  let observations = (request.results as? [VNRecognizedTextObservation]) ?? []
  for obs in observations {
    guard let top = obs.topCandidates(1).first else { continue }
    let box = obs.boundingBox
    rows.append([
      "text": top.string,
      "x": box.origin.x,
      "y": box.origin.y,
      "w": box.size.width,
      "h": box.size.height,
    ])
  }
}
request.recognitionLanguages = ["zh-Hans", "en-US"]
request.recognitionLevel = .accurate
request.usesLanguageCorrection = true
let handler = VNImageRequestHandler(cgImage: cg, options: [:])
try handler.perform([request])
let data = try JSONSerialization.data(withJSONObject: rows, options: [])
FileHandle.standardOutput.write(data)
'''


def normalize_text(value: str) -> str:
    return "".join(ch for ch in value if not ch.isspace()).replace("（", "(").replace("）", ")")


def text_matches_target(text: str, target: str) -> bool:
    clean_text = normalize_text(text)
    clean_target = normalize_text(target)
    if not clean_text or not clean_target:
        return False
    if clean_text in clean_target or clean_target in clean_text:
        return True
    prefix = clean_target[:6]
    return len(prefix) >= 4 and clean_text.startswith(prefix)


def run(
    args: list[str],
    *,
    input_text: str | None = None,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        input=input_text,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
    )


def call_cua(cua_bin: Path, tool: str, payload: dict[str, Any], *, timeout: int = 30) -> dict[str, Any]:
    result = run([str(cua_bin), "call", tool, json.dumps(payload, ensure_ascii=False)], timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError((result.stdout or "").strip() or f"cua-driver {tool} failed")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"cua-driver {tool} returned non-json output: {result.stdout!r}") from exc


def call_cua_action(cua_bin: Path, tool: str, payload: dict[str, Any], *, timeout: int = 30) -> dict[str, Any]:
    result = run([str(cua_bin), "call", tool, json.dumps(payload, ensure_ascii=False)], timeout=timeout)
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "output": (result.stdout or "").strip(),
    }


def run_osascript(script: str, *args: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return run(["osascript", "-", *args], input_text=script, timeout=timeout)


def run_health_check(cua_bin: Path = DEFAULT_CUA_BIN) -> dict[str, Any]:
    if not cua_bin.exists():
        return {"ok": False, "returncode": 1, "output": f"cua-driver not found: {cua_bin}"}
    permissions = run([str(cua_bin), "permissions", "status"], timeout=20)
    output = (permissions.stdout or "").strip()
    has_accessibility = "Accessibility:" in output and "✅ granted" in output
    has_screen = "Screen Recording:" in output and "✅ granted" in output
    try:
        window = find_wechat_window(cua_bin)
    except Exception as exc:
        return {
            "ok": False,
            "returncode": permissions.returncode,
            "output": f"{output}\nWeChat window check failed: {exc}",
        }
    return {
        "ok": permissions.returncode == 0 and has_accessibility and has_screen,
        "returncode": permissions.returncode,
        "output": output,
        "window": window,
    }


def activate_wechat() -> None:
    run_osascript('tell application "WeChat" to activate\ndelay 0.8', timeout=10)


def find_wechat_window(cua_bin: Path) -> dict[str, Any]:
    activate_wechat()
    listing = call_cua(cua_bin, "list_windows", {}, timeout=20)
    candidates = []
    for window in listing.get("windows", []):
        if window.get("app_name") not in WECHAT_APPS:
            continue
        bounds = window.get("bounds") or {}
        area = float(bounds.get("width") or 0) * float(bounds.get("height") or 0)
        if not window.get("is_on_screen") or area < 100_000:
            continue
        candidates.append((area, window))
    if not candidates:
        raise RuntimeError("没有找到可见的微信主窗口")
    return max(candidates, key=lambda item: item[0])[1]


def capture_window(cua_bin: Path, window: dict[str, Any], screenshot_path: Path) -> dict[str, Any]:
    return call_cua(
        cua_bin,
        "get_window_state",
        {
            "pid": int(window["pid"]),
            "window_id": int(window["window_id"]),
            "screenshot_out_file": str(screenshot_path),
            "max_elements": 500,
            "max_depth": 12,
        },
        timeout=30,
    )


def ocr_image(path: Path) -> list[dict[str, Any]]:
    result = run(["swift", "-", str(path)], input_text=OCR_SWIFT, timeout=30)
    if result.returncode != 0:
        raise RuntimeError((result.stdout or "").strip() or "OCR failed")
    return json.loads(result.stdout or "[]")


def text_center(row: dict[str, Any], width: int, height: int) -> tuple[int, int]:
    x = (float(row["x"]) + float(row["w"]) / 2) * width
    y = (1 - (float(row["y"]) + float(row["h"]) / 2)) * height
    return int(round(x)), int(round(y))


def find_chat_list_match(rows: list[dict[str, Any]], target: str) -> dict[str, Any] | None:
    matches = []
    for row in rows:
        text = str(row.get("text") or "")
        if float(row.get("x") or 0) >= 0.34:
            continue
        if text_matches_target(text, target):
            matches.append(row)
    if not matches:
        return None
    return min(matches, key=lambda row: float(row.get("y") or 0), default=None)


def title_matches(rows: list[dict[str, Any]], target: str) -> bool:
    for row in rows:
        if float(row.get("x") or 0) < 0.34 or float(row.get("y") or 0) < 0.88:
            continue
        if text_matches_target(str(row.get("text") or ""), target):
            return True
    return False


def click_window_point(cua_bin: Path, window: dict[str, Any], x: int, y: int) -> dict[str, Any]:
    result = call_cua_action(
        cua_bin,
        "click",
        {
            "pid": int(window["pid"]),
            "window_id": int(window["window_id"]),
            "x": x,
            "y": y,
        },
        timeout=20,
    )
    if not result.get("ok"):
        raise RuntimeError(result.get("output") or "cua-driver click failed")
    return result


def select_target_chat(cua_bin: Path, target: str) -> dict[str, Any]:
    window = find_wechat_window(cua_bin)
    with tempfile.TemporaryDirectory(prefix="wechat-cua-") as tmp:
        screenshot = Path(tmp) / "wechat.png"
        state = capture_window(cua_bin, window, screenshot)
        width = int(state.get("screenshot_width") or 0)
        height = int(state.get("screenshot_height") or 0)
        rows = ocr_image(screenshot)

        if title_matches(rows, target):
            return {"ok": True, "already_selected": True, "window": window, "screenshot_width": width, "screenshot_height": height}

        match = find_chat_list_match(rows, target)
        if not match:
            return {
                "ok": False,
                "step": "find_chat",
                "output": f"聊天列表里没有识别到目标群：{target}",
                "texts": [row.get("text") for row in rows[:30]],
            }
        x, y = text_center(match, width, height)
        click_window_point(cua_bin, window, x, y)

        verify_screenshot = Path(tmp) / "wechat-verify.png"
        verify_state = capture_window(cua_bin, window, verify_screenshot)
        verify_rows = ocr_image(verify_screenshot)
        if not title_matches(verify_rows, target):
            return {
                "ok": False,
                "step": "verify_title",
                "output": f"点击后没有确认进入目标群：{target}",
                "clicked_text": match.get("text"),
                "click": [x, y],
                "texts": [row.get("text") for row in verify_rows[:30]],
            }
        return {
            "ok": True,
            "already_selected": False,
            "clicked_text": match.get("text"),
            "click": [x, y],
            "window": window,
            "screenshot_width": int(verify_state.get("screenshot_width") or width),
            "screenshot_height": int(verify_state.get("screenshot_height") or height),
        }


def focus_input(cua_bin: Path, window: dict[str, Any], width: int, height: int) -> None:
    click_window_point(cua_bin, window, int(width * 0.58), int(height * 0.89))


def send_text(cua_bin: Path, window: dict[str, Any], message: str) -> dict[str, Any]:
    call_cua(cua_bin, "type_text", {"pid": int(window["pid"]), "window_id": int(window["window_id"]), "text": message}, timeout=30)
    result = call_cua_action(cua_bin, "press_key", {"pid": int(window["pid"]), "window_id": int(window["window_id"]), "key": "return"}, timeout=20)
    if not result.get("ok"):
        raise RuntimeError(result.get("output") or "cua-driver press_key failed")
    return result


def send_file_with_wechat(cua_bin: Path, window: dict[str, Any], width: int, height: int, file_path: Path) -> subprocess.CompletedProcess[str]:
    focus_input(cua_bin, window, width, height)
    script = r'''
on run argv
  set filePath to item 1 of argv
  set fileRef to POSIX file filePath
  delay 0.6
  set the clipboard to fileRef
  tell application "System Events"
    keystroke "v" using command down
    delay 1.2
    key code 36
    delay 0.8
  end tell
end run
'''
    return run_osascript(script, str(file_path), timeout=30)


def verify_file_visible(cua_bin: Path, window: dict[str, Any], file_path: Path) -> bool:
    with tempfile.TemporaryDirectory(prefix="wechat-cua-file-") as tmp:
        screenshot = Path(tmp) / "wechat-file.png"
        capture_window(cua_bin, window, screenshot)
        rows = ocr_image(screenshot)
    stem = normalize_text(file_path.stem)
    for row in rows:
        text = normalize_text(str(row.get("text") or ""))
        if len(stem) >= 6 and (stem[:6] in text or text[:6] in stem):
            return True
    return False


def send(
    target: str,
    message: str,
    file_path: Path | None,
    *,
    dry_run: bool = False,
    select_only: bool = False,
    cua_bin: Path = DEFAULT_CUA_BIN,
) -> dict[str, Any]:
    clean_target = target.strip()
    if not clean_target:
        raise ValueError("target is required")
    clean_message = message.strip()
    expanded_file = file_path.expanduser() if file_path else None
    if expanded_file and not expanded_file.exists():
        raise FileNotFoundError(str(expanded_file))
    if not clean_message and not expanded_file and not select_only:
        raise ValueError("message or file is required")

    payload = {
        "target": clean_target,
        "message": clean_message,
        "file": str(expanded_file) if expanded_file else "",
    }
    if dry_run:
        return {"ok": True, "dry_run": True, **payload}

    selection = select_target_chat(cua_bin, clean_target)
    if not selection.get("ok"):
        return {"ok": False, "dry_run": False, "selection": selection, **payload}
    if select_only:
        return {"ok": True, "dry_run": False, "selected_only": True, "selection": selection, **payload}

    window = selection["window"]
    width = int(selection["screenshot_width"])
    height = int(selection["screenshot_height"])
    focus_input(cua_bin, window, width, height)
    result: dict[str, Any] = {"text": None, "file": None}
    if clean_message:
        result["text"] = send_text(cua_bin, window, clean_message)
    if expanded_file:
        file_result = send_file_with_wechat(cua_bin, window, width, height, expanded_file)
        file_visible = file_result.returncode == 0 and verify_file_visible(cua_bin, window, expanded_file)
        result["file"] = {
            "returncode": file_result.returncode,
            "output": (file_result.stdout or "").strip(),
            "visible": file_visible,
        }
        if file_result.returncode != 0 or not file_visible:
            return {"ok": False, "dry_run": False, "selection": selection, "send_result": result, **payload}
    return {"ok": True, "dry_run": False, "selection": selection, "send_result": result, **payload}


def main() -> int:
    parser = argparse.ArgumentParser(description="在 Mac mini 上通过 CuaDriver 识别微信目标群并发送文本/文件")
    parser.add_argument("--target", default="皮皮球球备忘录", help="微信群或联系人名称")
    parser.add_argument("--message", default="", help="要发送的文本")
    parser.add_argument("--file", default="", help="要发送的本地文件路径")
    parser.add_argument("--cua-bin", default=str(DEFAULT_CUA_BIN), help="cua-driver 路径")
    parser.add_argument("--health-check", action="store_true", help="只检查 CuaDriver 权限和微信窗口")
    parser.add_argument("--dry-run", action="store_true", help="只输出计划，不操作微信")
    parser.add_argument("--select-only", action="store_true", help="只识别并选中群聊，不发送内容")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    cua_bin = Path(args.cua_bin).expanduser()
    if args.health_check:
        payload = run_health_check(cua_bin)
    else:
        payload = send(
            args.target,
            args.message,
            Path(args.file) if args.file else None,
            dry_run=args.dry_run,
            select_only=args.select_only,
            cua_bin=cua_bin,
        )

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("ok" if payload.get("ok") else f"failed: {payload.get('selection') or payload.get('output', '')}")
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
