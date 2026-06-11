from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "download_config.json"


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def require_playwright():
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError:
        print("缺少浏览器自动化依赖：playwright")
        print("安装命令：python3 -m pip install playwright && python3 -m playwright install chromium")
        print("安装后再运行：python3 download_reports.py open-login")
        raise SystemExit(2)
    return sync_playwright, PlaywrightTimeoutError


def profile_dir(config: dict) -> Path:
    path = Path(config["browser"]["profile_dir"])
    if not path.is_absolute():
        path = ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def downloads_dir(config: dict) -> Path:
    path = Path(config["downloads"]["dir"]).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def launch_context(playwright, config: dict):
    return playwright.chromium.launch_persistent_context(
        user_data_dir=str(profile_dir(config)),
        headless=bool(config["browser"].get("headless", False)),
        accept_downloads=True,
        downloads_path=str(downloads_dir(config)),
        slow_mo=int(config["browser"].get("slow_mo_ms", 0)),
        viewport={"width": 1440, "height": 950},
    )


def page_for(context, url: str):
    page = context.pages[0] if context.pages else context.new_page()
    page.goto(url, wait_until="domcontentloaded", timeout=90_000)
    return page


def open_login() -> None:
    config = load_config()
    sync_playwright, _ = require_playwright()
    with sync_playwright() as p:
        context = launch_context(p, config)
        for platform in config["platforms"].values():
            page = context.new_page()
            page.goto(platform["entry_url"], wait_until="domcontentloaded", timeout=90_000)
        print("已打开独立浏览器窗口。请完成饿了么和美团登录。")
        print("登录完成后可以关闭浏览器；登录状态会保存在 browser-profile 目录。")
        print("如果你已经能进入报表下载页，请把地址栏 URL 填到 download_config.json 的 download_url。")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            context.close()


def wait_for_manual_ready(page, platform_name: str) -> None:
    print(f"{platform_name} 页面已打开：{page.url}")
    print("如果页面需要登录、选日期或切换到下载页，请先在浏览器里处理。")
    input("处理好后回到这个窗口按回车继续...")


def click_first_download(page, texts: list[str], timeout_ms: int):
    for text in texts:
        locator = page.get_by_text(text, exact=False)
        try:
            if locator.count() > 0:
                return locator.first().click(timeout=timeout_ms)
        except Exception:
            continue
    raise RuntimeError(f"没有找到下载按钮，尝试过：{', '.join(texts)}")


def download_one(context, platform_key: str, platform: dict, config: dict, manual: bool) -> Path:
    _, PlaywrightTimeoutError = require_playwright()
    page = context.new_page()
    page.goto(platform["download_url"], wait_until="domcontentloaded", timeout=90_000)
    if manual:
        wait_for_manual_ready(page, platform["name"])

    timeout_ms = int(config["downloads"].get("timeout_seconds", 90)) * 1000
    before = datetime.now().strftime("%Y%m%d%H%M%S")
    try:
        with page.expect_download(timeout=timeout_ms) as download_info:
            click_first_download(page, platform["download_button_texts"], timeout_ms)
        download = download_info.value
    except PlaywrightTimeoutError as exc:
        raise RuntimeError(f"{platform['name']} 下载超时，请确认按钮文字和页面路径。") from exc

    suffix = platform.get("expected_file", "dat")
    suggested = download.suggested_filename or f"{platform_key}_{before}.{suffix}"
    target = downloads_dir(config) / suggested
    download.save_as(str(target))
    print(f"{platform['name']} 已下载：{target}")
    return target


def download_all(manual: bool) -> None:
    config = load_config()
    sync_playwright, _ = require_playwright()
    with sync_playwright() as p:
        context = launch_context(p, config)
        downloaded: list[Path] = []
        for key, platform in config["platforms"].items():
            downloaded.append(download_one(context, key, platform, config, manual))
        context.close()
    print("下载完成。接下来可运行：python3 process_reports.py")
    for path in downloaded:
        print(path)


def print_status() -> None:
    config = load_config()
    print("下载器配置：")
    print(f"登录状态目录：{profile_dir(config)}")
    print(f"下载目录：{downloads_dir(config)}")
    for key, platform in config["platforms"].items():
        print(f"{platform['name']}入口：{platform['entry_url']}")
        print(f"{platform['name']}下载页：{platform['download_url']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="饿了么 / 美团报表下载器")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="查看当前下载器配置")
    subparsers.add_parser("open-login", help="打开独立浏览器，首次登录两个后台")
    download_parser = subparsers.add_parser("download", help="进入配置的报表页并下载")
    download_parser.add_argument("--manual", action="store_true", help="下载前暂停，允许手动登录、选日期或进入下载页")
    args = parser.parse_args()

    if args.command == "status":
        print_status()
    elif args.command == "open-login":
        open_login()
    elif args.command == "download":
        download_all(manual=args.manual)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
