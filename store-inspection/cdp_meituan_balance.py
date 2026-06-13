from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from parse_balance_ocr import build_result
from one_click_meituan_balance import MEITUAN_WM_POI_IDS, STORES, recent_meituan_promo_url, url_with_wm_poi_id


ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent
REPORT_DIR = WORKSPACE / "business-report-dashboard"
OUTPUT_JSON = ROOT / "meituan-cdp-latest.json"
OUTPUT_DATA_JS = ROOT / "meituan-cdp-latest-data.js"
NETWORK_CANDIDATES_JSON = ROOT / "meituan-cdp-network-candidates.json"
FALLBACK_URL = "https://e.waimai.meituan.com/#https://waimaieapp.meituan.com/ad/v1/rpc"
THRESHOLD = 200.0
WORKING_NODE = "/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
if Path(WORKING_NODE).exists():
    os.environ.setdefault("PLAYWRIGHT_NODEJS_PATH", WORKING_NODE)

if str(REPORT_DIR) not in sys.path:
    sys.path.insert(0, str(REPORT_DIR))

import chrome_cdp_reports as cdp  # noqa: E402


def store_wm_poi_id(store: dict) -> str | None:
    joined = " ".join(str(store.get(key, "")) for key in ["name", "keyword"])
    for keyword, wm_poi_id in MEITUAN_WM_POI_IDS.items():
        if keyword in joined:
            return wm_poi_id
    return None


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def parse_money(text: str) -> float | None:
    cleaned = text.replace(",", "").replace("￥", "").replace("¥", "")
    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    if not match:
        return None
    return float(match.group(0))


def balance_from_page_text(text: str) -> float | None:
    compact = normalize_space(text)
    patterns = [
        r"账户余额\s*(?:\(元\)|（元）)?\s*([0-9]+(?:\.[0-9]+)?)\s*元?",
        r"余额\s*(?:\(元\)|（元）)?\s*([0-9]+(?:\.[0-9]+)?)\s*元",
        r"我的账户.*?([0-9]+(?:\.[0-9]+)?)\s*元",
    ]
    for pattern in patterns:
        match = re.search(pattern, compact, re.S)
        if match:
            return parse_money(match.group(1))
    return None


def response_candidate(url: str) -> bool:
    lowered = url.lower()
    keywords = [
        "balance",
        "account",
        "wallet",
        "fund",
        "budget",
        "rpc",
        "ad",
        "poi",
        "wm",
    ]
    return any(keyword in lowered for keyword in keywords)


def safe_response_preview(response) -> dict | None:
    if not response_candidate(response.url):
        return None
    try:
        body = response.text()
    except Exception:
        return None
    if not body:
        return None
    snippet = body[:1200]
    if not any(word in snippet for word in ["余额", "balance", "budget", "账户", "wmPoiId", "poi"]):
        return None
    return {
        "url": response.url.split("?")[0],
        "status": response.status,
        "snippet": snippet,
    }


def collect_store(page, store: dict, base_url: str) -> tuple[dict | None, list[dict]]:
    wm_poi_id = store_wm_poi_id(store)
    if not wm_poi_id:
        return None, []
    target_url = url_with_wm_poi_id(base_url, wm_poi_id)
    candidates: list[dict] = []

    def handle_response(response):
        candidate = safe_response_preview(response)
        if candidate:
            candidates.append(candidate)

    page.on("response", handle_response)
    try:
        cdp.goto_backend_page(page, target_url, timeout=90_000)
        for _ in range(20):
            page.wait_for_timeout(1000)
            text = page.locator("body").inner_text(timeout=5000)
            if "账户余额" in text or "推广首页" in text or "点金推广" in text:
                break
        text = page.locator("body").inner_text(timeout=10000)
    finally:
        page.remove_listener("response", handle_response)

    balance = balance_from_page_text(text)
    if balance is None:
        return {
            "platform": "美团",
            "store_name": store["name"],
            "store_id": wm_poi_id,
            "balance": 0.0,
            "status": "warning",
            "source": "Chrome CDP页面文本读取",
            "error": "页面文本未解析到账户余额",
            "page_text_preview": normalize_space(text)[:600],
        }, candidates
    return {
        "platform": "美团",
        "store_name": store["name"],
        "store_id": wm_poi_id,
        "balance": balance,
        "status": "warning" if balance < THRESHOLD else "normal",
        "source": "Chrome CDP页面文本读取",
    }, candidates


def collect_balances() -> tuple[list[dict], list[dict], str]:
    base_url = recent_meituan_promo_url() or FALLBACK_URL
    config = cdp.load_config()
    playwright, browser = cdp.connect_browser(config)
    try:
        context = cdp.first_context(browser)
        page = cdp.reusable_page(context)
        items = []
        network_candidates = []
        for store in STORES:
            item, candidates = collect_store(page, store, base_url)
            network_candidates.extend(candidates)
            if item:
                items.append(item)
        return items, network_candidates, base_url
    finally:
        cdp.disconnect_browser(playwright, browser)


def write_test_outputs(data: dict, network_candidates: list[dict]) -> None:
    OUTPUT_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUTPUT_DATA_JS.write_text(
        "window.MEITUAN_CDP_BALANCE_DATA = " + json.dumps(data, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8",
    )
    NETWORK_CANDIDATES_JSON.write_text(json.dumps(network_candidates[:80], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    items, network_candidates, base_url = collect_balances()
    ok_items = [item for item in items if not item.get("error")]
    data = build_result(items, THRESHOLD, "CDP页面文本没有读取到美团门店余额。")
    data["source"] = "meituan_cdp_balance"
    data["base_url"] = base_url.split("?")[0]
    data["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if ok_items and len(ok_items) < len(items):
        data["status"] = "partial"
        data["message"] = f"{len(ok_items)} 家门店读取成功，{len(items) - len(ok_items)} 家门店未解析到账户余额。"
    write_test_outputs(data, network_candidates)
    summary = data["summary"]
    print(
        f"美团 CDP 余额读取完成：{len(ok_items)}/{summary['store_count']} 家门店成功，"
        f"{summary['warning_count']} 家低于 {THRESHOLD:g} 元。"
    )
    print(f"测试输出：{OUTPUT_JSON}")
    print(f"候选接口输出：{NETWORK_CANDIDATES_JSON}")
    return 0 if ok_items else 1


if __name__ == "__main__":
    raise SystemExit(main())
