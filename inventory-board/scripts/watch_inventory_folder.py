#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path
from urllib import request, error


DEFAULT_SERVER = "http://139.155.148.169"
DEFAULT_ROOT = Path.home() / "Desktop" / "库存管理"
STATE_FILE = ".upload_state.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="自动上传库存 Excel 单据")
    parser.add_argument("--server", default=DEFAULT_SERVER, help="库存看板地址")
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="库存管理文件夹")
    parser.add_argument("--interval", type=int, default=20, help="扫描间隔秒数")
    parser.add_argument(
        "--movement",
        choices=["all", "inbound", "outbound"],
        default="inbound",
        help="监听入库、出库或全部文件夹，默认只监听入库",
    )
    args = parser.parse_args()

    root = Path(args.root).expanduser()
    inbound = root / "入库记录"
    outbound = root / "出库记录"
    imported = root / "已导入"
    failed = root / "导入失败"
    for folder in [inbound, outbound, imported, failed]:
        folder.mkdir(parents=True, exist_ok=True)

    state_path = root / STATE_FILE
    state = load_state(state_path)
    print(f"正在监听：{root}")
    print(f"云端地址：{args.server}")

    while True:
        changed = False
        folders = [("inbound", inbound), ("outbound", outbound)]
        if args.movement != "all":
            folders = [(movement_type, folder) for movement_type, folder in folders if movement_type == args.movement]
        for movement_type, folder in folders:
            for path in sorted(folder.iterdir()):
                if not is_excel(path):
                    continue
                key = f"{path.resolve()}:{path.stat().st_mtime_ns}:{path.stat().st_size}"
                if state.get(key) == "success":
                    continue
                if not file_is_stable(path):
                    continue

                ok, message = upload(args.server, movement_type, path)
                stamp = time.strftime("%Y%m%d-%H%M%S")
                if ok:
                    destination = unique_path(imported / f"{stamp}_{path.name}")
                    shutil.move(str(path), destination)
                    state[key] = "success"
                    print(f"已导入：{path.name} -> {destination.name}")
                else:
                    log_path = failed / f"{stamp}_{path.stem}.txt"
                    log_path.write_text(message, encoding="utf-8")
                    state[key] = "failed"
                    print(f"导入失败：{path.name}，原因：{message}")
                changed = True

        if changed:
            save_state(state_path, state)
        time.sleep(args.interval)


def is_excel(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in {".xlsx", ".xlsm"} and not path.name.startswith("~$")


def file_is_stable(path: Path) -> bool:
    size = path.stat().st_size
    time.sleep(1)
    return path.exists() and path.stat().st_size == size


def upload(server: str, movement_type: str, path: Path) -> tuple[bool, str]:
    boundary = "----inventory-upload-boundary"
    body = build_multipart(boundary, movement_type, path)
    req = request.Request(
        f"{server.rstrip('/')}/api/import",
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with request.urlopen(req, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return True, payload.get("message") or payload.get("status", "success")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(detail)
            return False, payload.get("detail", detail)
        except json.JSONDecodeError:
            return False, detail
    except Exception as exc:
        return False, str(exc)


def build_multipart(boundary: str, movement_type: str, path: Path) -> bytes:
    parts = [
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="movement_type"\r\n\r\n'
        f"{movement_type}\r\n".encode("utf-8"),
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
        "Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n".encode("utf-8"),
        path.read_bytes(),
        f"\r\n--{boundary}--\r\n".encode("utf-8"),
    ]
    return b"".join(parts)


def load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_state(path: Path, state: dict) -> None:
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for idx in range(2, 1000):
        candidate = path.with_name(f"{path.stem}_{idx}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"无法生成文件名：{path}")


if __name__ == "__main__":
    main()
