from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from balance_coverage import apply_direct_coverage
from cdp_meituan_balance import (
    ACCOUNT_INFO_API_KEY,
    THRESHOLD,
    account_balance_from_payload,
    balance_from_page_text,
    normalize_space,
)
from parse_balance_ocr import build_result


ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent
CONFIG_PATH = WORKSPACE / "config" / "direct_meituan_accounts.json"
OUTPUT_JSON = ROOT / "direct-meituan-cdp-latest.json"
OUTPUT_DATA_JS = ROOT / "direct-meituan-cdp-latest-data.js"
MAC_CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
WORKING_NODE = "/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
if Path(WORKING_NODE).exists():
    os.environ.setdefault("PLAYWRIGHT_NODEJS_PATH", WORKING_NODE)


def require_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError:
        print("缺少 playwright。请先安装 business-report-dashboard/requirements.txt。")
        raise SystemExit(2)
    return sync_playwright


def read_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def enabled_accounts(account_id: str | None) -> list[dict]:
    accounts = [item for item in read_config().get("accounts") or [] if item.get("enabled")]
    if account_id:
        accounts = [item for item in accounts if item.get("id") == account_id]
    if not accounts:
        raise SystemExit(f"没有找到已启用的直营美团账号：{account_id or '全部'}")
    return accounts


def cdp_url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def cdp_available(port: int) -> bool:
    try:
        with urlopen(f"{cdp_url(port)}/json/version", timeout=2) as response:
            return response.status == 200
    except (URLError, OSError):
        return False
    except Exception:
        return False


def connect_account(playwright, account: dict, *, visible: bool):
    debug_port = int(account.get("debug_port") or 0)
    if debug_port and cdp_available(debug_port):
        browser = playwright.chromium.connect_over_cdp(cdp_url(debug_port))
        context = browser.contexts[0] if browser.contexts else browser.new_context(accept_downloads=False)
        page = context.pages[0] if context.pages else context.new_page()
        return "cdp", browser, context, page

    profile_dir = Path(account["profile_dir"]).expanduser()
    profile_dir.mkdir(parents=True, exist_ok=True)
    options = {
        "user_data_dir": str(profile_dir),
        "headless": not visible,
        "accept_downloads": False,
        "viewport": {"width": 1440, "height": 950},
    }
    if MAC_CHROME.exists():
        options["executable_path"] = str(MAC_CHROME)
    context = playwright.chromium.launch_persistent_context(**options)
    page = context.pages[0] if context.pages else context.new_page()
    return "launch", None, context, page


def body_text(page, *, timeout: int = 10000) -> str:
    try:
        return page.locator("body").inner_text(timeout=timeout)
    except Exception:
        return ""


def collect_account(account: dict, *, visible: bool, wait_seconds: int) -> tuple[list[dict], dict]:
    pages = account.get("pages") or {}
    target_url = pages.get("promo_balance") or pages.get("home") or "https://e.waimai.meituan.com/"
    stores = account.get("stores") or [account.get("name") or account.get("id")]
    store_name = str(stores[0])
    account_payload: dict | None = None
    account_response_url = ""

    sync_playwright = require_playwright()
    with sync_playwright() as p:
        mode, browser, context, page = connect_account(p, account, visible=visible)

        def handle_response(response):
            nonlocal account_payload, account_response_url
            if ACCOUNT_INFO_API_KEY not in response.url:
                return
            try:
                payload = response.json()
            except Exception:
                return
            if isinstance(payload, dict):
                account_payload = payload
                account_response_url = response.url

        text = ""
        try:
            page.on("response", handle_response)
            page.goto(target_url, wait_until="domcontentloaded", timeout=90_000)
            deadline = time.time() + wait_seconds
            while time.time() < deadline:
                page.wait_for_timeout(1000)
                text = body_text(page, timeout=5000)
                if account_payload is not None or "账户余额" in text or "立即充值" in text:
                    break
        finally:
            try:
                page.remove_listener("response", handle_response)
            except Exception:
                pass
            if mode == "launch":
                context.close()

    balance = account_balance_from_payload(account_payload or {})
    source = "Chrome CDP接口读取"
    if balance is None:
        balance = balance_from_page_text(text)
        source = "Chrome CDP页面文本读取"

    if balance is None:
        return [
            {
                "platform": "美团",
                "store_name": store_name,
                "store_id": "",
                "balance": 0.0,
                "status": "warning",
                "source": source,
                "error": "页面文本未解析到账户余额",
                "page_url": target_url,
                "account_response_url": account_response_url.split("?")[0] if account_response_url else "",
                "api_seen": bool(account_payload),
                "page_text_preview": normalize_space(text)[:600],
            }
        ], {"connection_mode": mode, "url": target_url}

    return [
        {
            "platform": "美团",
            "store_name": store_name,
            "store_id": "",
            "balance": balance,
            "status": "warning" if balance < THRESHOLD else "normal",
            "source": source,
            "page_url": target_url,
            "account_response_url": account_response_url.split("?")[0] if account_response_url else "",
            "api_seen": bool(account_payload),
        }
    ], {"connection_mode": mode, "url": target_url}


def write_outputs(data: dict) -> None:
    OUTPUT_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUTPUT_DATA_JS.write_text(
        "window.DIRECT_MEITUAN_CDP_BALANCE_DATA = " + json.dumps(data, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="只读读取直营美团临时账号推广余额。")
    parser.add_argument("--account", default="direct_chaoyangmen", help="账号 ID；默认朝阳门。")
    parser.add_argument("--all", action="store_true", help="读取所有已启用直营美团账号。")
    parser.add_argument("--visible", action="store_true", help="显示浏览器窗口；默认 headless/附着现有 CDP。")
    parser.add_argument("--wait-seconds", type=int, default=25, help="每个账号等待余额页面加载秒数。")
    args = parser.parse_args(argv)

    accounts = enabled_accounts(None if args.all else args.account)
    items: list[dict] = []
    account_results = []
    errors = []
    for account in accounts:
        try:
            account_items, meta = collect_account(account, visible=args.visible, wait_seconds=args.wait_seconds)
            items.extend(account_items)
            account_results.append(
                {
                    "account_id": account.get("id"),
                    "account_name": account.get("name"),
                    "stores": account.get("stores") or [],
                    **meta,
                }
            )
        except Exception as exc:
            errors.append(f"{account.get('id')}: {exc}")

    data = apply_direct_coverage(build_result(items, THRESHOLD, "直营美团账号没有读取到账户余额。"), {"美团"})
    data["source"] = "direct_meituan_cdp_balance"
    data["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data["accounts"] = account_results
    if errors:
        data["message"] = "；".join(part for part in [data.get("message", ""), *errors] if part)
        data["status"] = "partial" if items else "failed"
    write_outputs(data)
    ok_items = [item for item in items if not item.get("error")]
    print(f"直营美团余额读取完成：{len(ok_items)}/{len(items)} 条成功，输出：{OUTPUT_JSON}")
    return 0 if ok_items and not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
