from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "direct_meituan_accounts.json"
OUTPUT_DIR = ROOT / "outputs" / "direct_meituan_account_check"
WORKING_NODE = "/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
if Path(WORKING_NODE).exists():
    os.environ.setdefault("PLAYWRIGHT_NODEJS_PATH", WORKING_NODE)

PAGE_CHECKS = {
    "home": ["美团外卖", "门店", "商家", "工作台"],
    "daily_report": ["报表下载", "下载", "数据", "历史"],
    "reviews": ["评价", "评论", "用户", "回复"],
    "promo_balance": ["推广", "余额", "账户", "点金"],
}
BLOCKING_TEXTS = ["登录", "验证码", "安全验证", "请输入验证码", "手机验证码", "扫码登录"]


def require_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError:
        print("缺少 playwright。请先安装 business-report-dashboard/requirements.txt。")
        raise SystemExit(2)
    return sync_playwright


def load_account(account_id: str) -> dict:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    accounts = payload.get("accounts") or []
    account = next((item for item in accounts if item.get("id") == account_id), None)
    if not account:
        known = ", ".join(item.get("id", "") for item in accounts)
        raise SystemExit(f"没有找到账号 {account_id}。已配置：{known}")
    if not account.get("enabled", False):
        raise SystemExit(f"账号 {account_id} 尚未启用。")
    return account


def compact_text(value: str, limit: int = 500) -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    return text[:limit]


def check_page(page, page_key: str, url: str, wait_ms: int) -> dict:
    page.goto(url, wait_until="domcontentloaded", timeout=90_000)
    page.wait_for_timeout(wait_ms)
    title = page.title()
    current_url = page.url
    try:
        body = page.locator("body").inner_text(timeout=10_000)
    except Exception as exc:
        body = ""
        body_error = str(exc)
    else:
        body_error = ""

    matched = [text for text in PAGE_CHECKS.get(page_key, []) if text in title or text in body]
    blocking = [text for text in BLOCKING_TEXTS if text in body or text in title or text in current_url]
    status = "ok" if matched and not blocking else "needs_manual"
    return {
        "page": page_key,
        "url": current_url,
        "title": title,
        "status": status,
        "matched_texts": matched,
        "blocking_texts": blocking,
        "body_error": body_error,
        "text_sample": compact_text(body),
    }


def run_check(account_id: str, visible: bool, wait_ms: int) -> dict:
    account = load_account(account_id)
    profile_dir = Path(account["profile_dir"]).expanduser()
    profile_dir.mkdir(parents=True, exist_ok=True)
    pages = account.get("pages") or {}
    ordered_pages = [
        ("home", pages.get("home")),
        ("daily_report", pages.get("daily_report")),
        ("reviews", pages.get("reviews")),
        ("promo_balance", pages.get("promo_balance")),
    ]

    sync_playwright = require_playwright()
    results = []
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=not visible,
            accept_downloads=False,
            viewport={"width": 1440, "height": 950},
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            for page_key, url in ordered_pages:
                if not url:
                    continue
                results.append(check_page(page, page_key, url, wait_ms))
        finally:
            context.close()

    failed = [item for item in results if item["status"] != "ok"]
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "account_id": account_id,
        "account_name": account.get("name", account_id),
        "stores": account.get("stores") or [],
        "profile_dir": str(profile_dir),
        "mode": "visible" if visible else "headless",
        "status": "ok" if not failed else "needs_manual",
        "summary": {
            "page_count": len(results),
            "ok_count": len(results) - len(failed),
            "needs_manual_count": len(failed),
        },
        "pages": results,
    }


def write_result(payload: dict) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_DIR / "latest.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="只读检查直营美团临时账号页面登录状态。")
    parser.add_argument("--account", default="direct_chaoyangmen", help="账号 ID。")
    parser.add_argument("--visible", action="store_true", help="显示浏览器窗口；默认 headless。")
    parser.add_argument("--wait-ms", type=int, default=5000, help="每个页面打开后的等待毫秒数。")
    args = parser.parse_args()

    payload = run_check(args.account, args.visible, args.wait_ms)
    output = write_result(payload)
    print(f"直营美团账号只读检查：{payload['status']}，结果：{output}")
    for item in payload["pages"]:
        matched = " / ".join(item["matched_texts"]) or "未匹配"
        blocking = " / ".join(item["blocking_texts"]) or "无"
        print(f"- {item['page']}: {item['status']}；匹配：{matched}；阻塞：{blocking}")
    if payload["status"] != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
