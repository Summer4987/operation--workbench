from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from one_click_meituan_balance import recent_meituan_promo_url


ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent
REPORT_DIR = WORKSPACE / "business-report-dashboard"
OUTPUT_JSON = ROOT / "meituan-cdp-recharge-probe.json"
FALLBACK_URL = "https://e.waimai.meituan.com/#https://waimaieapp.meituan.com/ad/v1/rpc"
WORKING_NODE = "/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
if Path(WORKING_NODE).exists():
    os.environ.setdefault("PLAYWRIGHT_NODEJS_PATH", WORKING_NODE)

if str(REPORT_DIR) not in sys.path:
    sys.path.insert(0, str(REPORT_DIR))

import chrome_cdp_reports as cdp  # noqa: E402


ROUTE_CANDIDATES = [
    "/subapp/isomor_recharge/pages/index/index",
    "/subapp/isomor_recharge/pages/account/index",
    "/subapp/isomor_recharge/pages/recharge/index",
    "/subapp/account/pages/index/index",
    "/subapp/account/pages/recharge/index",
    "/activity/recharge",
]
KEYWORDS = [
    "余额",
    "账户",
    "充值",
    "提现",
    "account",
    "balance",
    "wallet",
    "fund",
    "asset",
    "finance",
    "recharge",
    "withdraw",
    "money",
    "amount",
]


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def relevant(text: str) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in KEYWORDS)


def url_with_route(base_url: str, route: str) -> str:
    parts = urlsplit(base_url)
    fragment = parts.fragment
    if "waimaieapp.meituan.com" in fragment:
        inner = urlsplit(fragment)
        query = dict(parse_qsl(inner.query, keep_blank_values=True))
        inner_url = urlunsplit((inner.scheme, inner.netloc, inner.path, urlencode(query), route))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, inner_url))
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), route))


def parse_response_json(body: str):
    try:
        return json.loads(body)
    except Exception:
        pass
    jsonp_match = re.search(r"^[^(]+\((.*)\)\s*;?$", body, re.S)
    if jsonp_match:
        try:
            return json.loads(jsonp_match.group(1))
        except Exception:
            return None
    return None


def interesting_json_paths(value, *, path: str = "$", depth: int = 0) -> list[dict]:
    if depth > 8:
        return []
    matches = []
    key_pattern = re.compile(r"(balance|account|wallet|fund|amount|money|asset|finance|budget|charge|recharge|withdraw|余额|账户|充值|提现)", re.I)
    if isinstance(value, dict):
        for key, item in value.items():
            child_path = f"{path}.{key}"
            key_interesting = bool(key_pattern.search(str(key)))
            if key_interesting and (isinstance(item, (str, int, float, bool)) or item is None):
                matches.append({"path": child_path, "value": item})
            matches.extend(interesting_json_paths(item, path=child_path, depth=depth + 1))
    elif isinstance(value, list):
        for index, item in enumerate(value[:20]):
            matches.extend(interesting_json_paths(item, path=f"{path}[{index}]", depth=depth + 1))
    return matches


def response_candidate(response) -> dict | None:
    url = response.url
    if not relevant(url):
        return None
    try:
        body = response.text()
    except Exception:
        return None
    if not body or not relevant(body[:3000]):
        return None
    payload = parse_response_json(body)
    matches = interesting_json_paths(payload) if payload is not None else []
    return {
        "url": url.split("?")[0],
        "status": response.status,
        "matches": matches[:40],
        "snippet": body[:1200],
    }


def collect_route(page, base_url: str, route: str) -> dict:
    url = url_with_route(base_url, route)
    responses: list[dict] = []

    def handle_response(response):
        candidate = response_candidate(response)
        if candidate:
            responses.append(candidate)

    page.on("response", handle_response)
    try:
        cdp.goto_backend_page(page, url, timeout=90_000)
        page.wait_for_timeout(10_000)
        text = page.locator("body").inner_text(timeout=10_000)
        current_url = page.url
    finally:
        page.remove_listener("response", handle_response)
    return {
        "route": route,
        "target_url": url,
        "current_url": current_url,
        "title": page.title(),
        "body_text_preview": normalize_space(text)[:2000],
        "responses": responses[:80],
    }


def main() -> int:
    base_url = recent_meituan_promo_url() or FALLBACK_URL
    config = cdp.load_config()
    playwright, browser = cdp.connect_browser(config)
    try:
        context = cdp.first_context(browser)
        page = cdp.reusable_page(context)
        route_results = [collect_route(page, base_url, route) for route in ROUTE_CANDIDATES]
        result = {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "base_url": base_url,
            "routes": route_results,
        }
        OUTPUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"美团充值/账户路由探针完成：{OUTPUT_JSON}")
        for item in route_results:
            print(f"{item['route']}: responses={len(item.get('responses', []))} url={item.get('current_url')}")
        return 0
    finally:
        cdp.disconnect_browser(playwright, browser)


if __name__ == "__main__":
    raise SystemExit(main())
