#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit
from urllib import error, request


DEFAULT_SERVER = "http://139.155.148.169"
DEFAULT_TOKEN = "xiongxiaoxiao-order"
DEFAULT_OUTPUT_DIR = Path.home() / "Desktop" / "库存管理" / "出库记录"
DEFAULT_LATEST = 20


def main() -> None:
    parser = argparse.ArgumentParser(description="手动同步云端生成的出库单到本地打印目录")
    parser.add_argument("--server", default=DEFAULT_SERVER, help="库存看板地址")
    parser.add_argument("--token", default=DEFAULT_TOKEN, help="门店提交链接口令")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="本地打印/归档文件夹")
    parser.add_argument("--latest", type=int, default=DEFAULT_LATEST, help="最多同步最近多少个云端出库单")
    args = parser.parse_args()

    output_dir = Path(args.output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = fetch_json(f"{args.server.rstrip('/')}/api/public-order/files?token={args.token}")
    items = list(payload.get("items", []))
    if args.latest > 0:
        items = items[: args.latest]
    downloaded = 0
    skipped = 0

    for item in items:
        filename = Path(item["filename"]).name
        target = output_dir / filename
        if target.exists() and target.stat().st_size == int(item.get("size") or 0):
            skipped += 1
            continue
        download_url = item["download_url"]
        if download_url.startswith("/"):
            download_url = f"{args.server.rstrip('/')}{download_url}"
        data = fetch_bytes(download_url)
        target.write_bytes(data)
        downloaded += 1
        print(f"已同步：{filename}")

    if downloaded == 0:
        print("没有新的出库单")
    print(f"同步完成：新增 {downloaded}，跳过 {skipped}，检查范围 {len(items)}，目录 {output_dir}")


def fetch_json(url: str) -> dict:
    try:
        with request.urlopen(url, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(detail)
            raise RuntimeError(payload.get("detail", detail)) from exc
        except json.JSONDecodeError as parse_exc:
            raise RuntimeError(detail) from parse_exc


def fetch_bytes(url: str) -> bytes:
    with request.urlopen(quote_url(url), timeout=60) as response:
        return response.read()


def quote_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, quote(parts.path, safe="/%"), parts.query, parts.fragment))


if __name__ == "__main__":
    main()
