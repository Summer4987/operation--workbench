from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from parse_balance_ocr import build_result
from balance_coverage import apply_direct_coverage


ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent
REPORT_DIR = WORKSPACE / "business-report-dashboard"
OUTPUT_JSON = ROOT / "eleme-cdp-latest.json"
OUTPUT_DATA_JS = ROOT / "eleme-cdp-latest-data.js"
ELEME_BALANCE_URL = "https://r.ele.me/doujin-isv-manage/index.html?__path__=accountChain/accountDetail"
BALANCE_API_KEY = "IGwShopInfoService.listLeafShopInfoPage"
THRESHOLD = 200.0
WORKING_NODE = "/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
if Path(WORKING_NODE).exists():
    os.environ.setdefault("PLAYWRIGHT_NODEJS_PATH", WORKING_NODE)

if str(REPORT_DIR) not in sys.path:
    sys.path.insert(0, str(REPORT_DIR))

import chrome_cdp_reports as cdp  # noqa: E402


def yuan_from_cents(value) -> float:
    try:
        return round(float(value) / 100, 2)
    except (TypeError, ValueError):
        return 0.0


def parse_shop_rows(payload: dict) -> list[dict]:
    rows = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    items = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ad_balance = row.get("adBalance") if isinstance(row.get("adBalance"), dict) else {}
        detail = ad_balance.get("detail") if isinstance(ad_balance.get("detail"), dict) else {}
        balance_cents = detail.get("balance")
        if balance_cents is None:
            balance_cents = ad_balance.get("balance")
        store_name = str(row.get("shopName") or "").strip()
        if not store_name:
            continue
        shop_id = row.get("shopId") or detail.get("shopId") or ""
        balance = yuan_from_cents(balance_cents)
        items.append(
            {
                "platform": "饿了么",
                "store_name": store_name,
                "store_id": str(shop_id),
                "balance": balance,
                "status": "warning" if balance < THRESHOLD else "normal",
                "source": "Chrome CDP接口读取",
            }
        )
    return items


def collect_balance_payload(timeout_seconds: int = 60) -> tuple[dict | None, str]:
    config = cdp.load_config()
    playwright, browser = cdp.connect_browser(config)
    response_payload: dict | None = None
    response_url = ""
    try:
        context = cdp.first_context(browser)
        page = cdp.reusable_page(context)

        def handle_response(response):
            nonlocal response_payload, response_url
            if BALANCE_API_KEY not in response.url:
                return
            try:
                payload = response.json()
            except Exception:
                return
            if isinstance(payload, dict) and isinstance(payload.get("result"), list):
                response_payload = payload
                response_url = response.url

        page.on("response", handle_response)
        try:
            cdp.goto_backend_page(page, ELEME_BALANCE_URL, timeout=90_000)
            deadline = time.time() + timeout_seconds
            while time.time() < deadline and response_payload is None:
                page.wait_for_timeout(1000)
                if response_payload is None and BALANCE_API_KEY not in page.url:
                    # Keep the page active without clicking any business controls.
                    page.evaluate("() => document.body && document.body.innerText")
        finally:
            page.remove_listener("response", handle_response)
        return response_payload, response_url
    finally:
        cdp.disconnect_browser(playwright, browser)


def write_test_outputs(data: dict) -> None:
    OUTPUT_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUTPUT_DATA_JS.write_text(
        "window.ELEME_CDP_BALANCE_DATA = " + json.dumps(data, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8",
    )


def main() -> int:
    payload, response_url = collect_balance_payload()
    items = parse_shop_rows(payload or {})
    data = apply_direct_coverage(build_result(items, THRESHOLD, "CDP接口没有读取到饿了么门店余额。"))
    data["source"] = "eleme_cdp_balance"
    data["response_url"] = response_url
    data["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    write_test_outputs(data)
    summary = data["summary"]
    print(
        f"饿了么 CDP 余额读取完成：{summary['store_count']} 家门店，"
        f"{summary['warning_count']} 家低于 {THRESHOLD:g} 元。"
    )
    print(f"测试输出：{OUTPUT_JSON}")
    return 0 if items else 1


if __name__ == "__main__":
    raise SystemExit(main())
