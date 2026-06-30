#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib import error, request
from urllib.parse import quote, urlsplit, urlunsplit


DEFAULT_SERVER = "http://139.155.148.169"
DEFAULT_TOKEN = "xiongxiaoxiao-order"
DEFAULT_OUTPUT_DIR = Path.home() / "Desktop" / "库存管理" / "出库记录"
DEFAULT_STATE_PATH = Path.home() / "HermesPrivate" / "state" / "daily_order_hermes_delivery.json"
DEFAULT_LOG_DIR = Path.home() / "HermesPrivate" / "logs" / "daily_order_hermes_delivery"
DEFAULT_HERMES_BIN = Path.home() / ".local" / "bin" / "hermes"
DEFAULT_TARGET = "熊小小牛排饭-易代仓仓储配送群"
DEFAULT_LATEST = 20
DEFAULT_SENDER = "hermes"
DEFAULT_WECHAT_GUI_BIN = Path(__file__).resolve().with_name("wechat_gui_sender.py")


def fetch_order_files(server: str, token: str, latest: int) -> list[dict[str, Any]]:
    payload = fetch_json(f"{server.rstrip('/')}/api/public-order/files?token={quote(token)}")
    items = list(payload.get("items") or [])
    return items[:latest] if latest > 0 else items


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"delivered": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"delivered": {}}
    if not isinstance(payload, dict):
        return {"delivered": {}}
    delivered = payload.get("delivered")
    if not isinstance(delivered, dict):
        payload["delivered"] = {}
    return payload


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def item_key(item: dict[str, Any]) -> str:
    return f"{Path(str(item.get('filename') or '')).name}|{int(item.get('size') or 0)}"


def undelivered_items(items: list[dict[str, Any]], state: dict[str, Any]) -> list[dict[str, Any]]:
    delivered = state.get("delivered") or {}
    return [item for item in items if item_key(item) not in delivered]


def mark_delivered(state: dict[str, Any], item: dict[str, Any], status: str) -> None:
    delivered = state.setdefault("delivered", {})
    delivered[item_key(item)] = {
        "filename": Path(str(item.get("filename") or "")).name,
        "size": int(item.get("size") or 0),
        "mtime": item.get("mtime") or 0,
        "status": status,
        "recorded_at": int(time.time()),
    }


def download_item(server: str, item: dict[str, Any], output_dir: Path) -> Path:
    filename = Path(str(item["filename"])).name
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / filename
    expected_size = int(item.get("size") or 0)
    if target.exists() and (expected_size <= 0 or target.stat().st_size == expected_size):
        return target
    download_url = str(item["download_url"])
    if download_url.startswith("/"):
        download_url = f"{server.rstrip('/')}{download_url}"
    target.write_bytes(fetch_bytes(download_url))
    return target


def build_message(path: Path, item: dict[str, Any]) -> str:
    return "\n".join(
        [
            "熊小小日配订货 Excel 已生成，文件见附件。",
            f"文件：{Path(str(item.get('filename') or path.name)).name}",
            f"文件路径：{path}",
            f"MEDIA:{path}",
        ]
    )


def build_wechat_gui_message(path: Path, item: dict[str, Any]) -> str:
    return "\n".join(
        [
            "熊小小日配订货 Excel 已生成，文件见附件。",
            f"文件：{Path(str(item.get('filename') or path.name)).name}",
        ]
    )


def send_with_hermes(message: str, target: str, hermes_bin: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(hermes_bin), "send", "--to", target, message],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=90,
    )


def send_with_wechat_gui(message: str, target: str, file_path: Path, sender_bin: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "/usr/bin/python3",
            str(sender_bin),
            "--target",
            target,
            "--message",
            message,
            "--file",
            str(file_path),
            "--json",
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=90,
    )


def write_log(log_dir: Path, name: str, payload: dict[str, Any]) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(char if char.isalnum() or char in "._-" else "-" for char in name)[:80] or "delivery"
    path = log_dir / f"{int(time.time())}-{safe_name}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def deliver(args: argparse.Namespace) -> dict[str, Any]:
    server = args.server.rstrip("/")
    output_dir = Path(args.output_dir).expanduser()
    state_path = Path(args.state_path).expanduser()
    log_dir = Path(args.log_dir).expanduser()
    state = load_state(state_path)
    items = fetch_order_files(server, args.token, args.latest)
    pending = undelivered_items(items, state)

    if args.init_baseline:
        for item in pending:
            mark_delivered(state, item, "baseline")
        save_state(state_path, state)
        return {"status": "baseline", "checked": len(items), "marked": len(pending), "sent": 0, "failed": 0}

    sent = 0
    failed = 0
    logs: list[str] = []
    for item in reversed(pending):
        path = download_item(server, item, output_dir)
        message = build_message(path, item) if args.sender == "hermes" else build_wechat_gui_message(path, item)
        if args.dry_run:
            log_path = write_log(
                log_dir,
                Path(str(item.get("filename") or path.name)).name,
                {"status": "dry-run", "sender": args.sender, "message": message, "file": str(path), "item": item},
            )
            logs.append(str(log_path))
            continue
        if args.sender == "wechat-gui":
            result = send_with_wechat_gui(message, args.target, path, Path(args.wechat_gui_bin).expanduser())
        else:
            result = send_with_hermes(message, args.target, Path(args.hermes_bin).expanduser())
        payload = {
            "status": "sent" if result.returncode == 0 else "failed",
            "sender": args.sender,
            "returncode": result.returncode,
            "output": (result.stdout or "").strip(),
            "target": args.target,
            "message": message,
            "item": item,
        }
        log_path = write_log(log_dir, Path(str(item.get("filename") or path.name)).name, payload)
        logs.append(str(log_path))
        if result.returncode == 0:
            mark_delivered(state, item, "sent")
            sent += 1
            save_state(state_path, state)
        else:
            failed += 1
            break
    if not args.dry_run:
        save_state(state_path, state)
    return {"status": "ok" if failed == 0 else "failed", "checked": len(items), "pending": len(pending), "sent": sent, "failed": failed, "logs": logs}


def fetch_json(url: str) -> dict[str, Any]:
    try:
        with request.urlopen(url, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(detail) from exc


def fetch_bytes(url: str) -> bytes:
    with request.urlopen(quote_url(url), timeout=60) as response:
        return response.read()


def quote_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, quote(parts.path, safe="/%"), parts.query, parts.fragment))


def main() -> int:
    parser = argparse.ArgumentParser(description="从云端同步熊小小日配订货 Excel，并通过 Mac mini Hermes 发送到普通微信群")
    parser.add_argument("--server", default=DEFAULT_SERVER)
    parser.add_argument("--token", default=DEFAULT_TOKEN)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--state-path", default=str(DEFAULT_STATE_PATH))
    parser.add_argument("--log-dir", default=str(DEFAULT_LOG_DIR))
    parser.add_argument("--hermes-bin", default=str(DEFAULT_HERMES_BIN))
    parser.add_argument("--sender", choices=["hermes", "wechat-gui"], default=DEFAULT_SENDER)
    parser.add_argument("--wechat-gui-bin", default=str(DEFAULT_WECHAT_GUI_BIN))
    parser.add_argument("--target", default=DEFAULT_TARGET)
    parser.add_argument("--latest", type=int, default=DEFAULT_LATEST)
    parser.add_argument("--init-baseline", action="store_true", help="只把当前云端文件标记为已处理，不发送历史文件")
    parser.add_argument("--dry-run", action="store_true", help="下载并记录将发送的消息，不调用 Hermes、不写入已发送状态")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = deliver(args)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"检查 {payload.get('checked', 0)} 个，待发送 {payload.get('pending', 0)} 个，已发送 {payload.get('sent', 0)} 个，失败 {payload.get('failed', 0)} 个")
    return 0 if payload.get("failed", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
