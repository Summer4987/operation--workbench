from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from one_click_meituan_balance import recent_meituan_promo_url


ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent
REPORT_DIR = WORKSPACE / "business-report-dashboard"
OUTPUT_JSON = ROOT / "meituan-cdp-route-probe.json"
FALLBACK_URL = "https://e.waimai.meituan.com/#https://waimaieapp.meituan.com/ad/v1/rpc"
WORKING_NODE = "/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
if Path(WORKING_NODE).exists():
    os.environ.setdefault("PLAYWRIGHT_NODEJS_PATH", WORKING_NODE)

if str(REPORT_DIR) not in sys.path:
    sys.path.insert(0, str(REPORT_DIR))

import chrome_cdp_reports as cdp  # noqa: E402


KEYWORDS = [
    "账户",
    "余额",
    "充值",
    "提现",
    "account",
    "balance",
    "wallet",
    "recharge",
    "withdraw",
    "fund",
    "asset",
    "finance",
]


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def relevant(text: str) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in KEYWORDS)


def collect_dom_candidates(page) -> dict:
    return page.evaluate(
        """(keywords) => {
            const norm = (text) => (text || "").replace(/\\s+/g, " ").trim();
            const relevant = (text) => {
                const lowered = (text || "").toLowerCase();
                return keywords.some((keyword) => lowered.includes(String(keyword).toLowerCase()));
            };
            const nodes = Array.from(document.querySelectorAll("a, button, [role=button], [class], [data-*]"));
            const candidates = [];
            for (const el of nodes) {
                const rect = el.getBoundingClientRect();
                const text = norm(el.innerText || el.textContent || el.getAttribute("aria-label") || el.getAttribute("title") || "");
                const href = el.href || el.getAttribute("href") || "";
                const attrs = {};
                for (const attr of el.attributes || []) {
                    if (relevant(attr.name) || relevant(attr.value)) attrs[attr.name] = attr.value;
                }
                const combined = [text, href, JSON.stringify(attrs), el.className || "", el.id || ""].join(" ");
                if (!relevant(combined)) continue;
                candidates.push({
                    tag: el.tagName,
                    text,
                    href,
                    id: el.id || "",
                    className: String(el.className || ""),
                    attrs,
                    visible: rect.width > 0 && rect.height > 0,
                    rect: {x: rect.x, y: rect.y, width: rect.width, height: rect.height},
                });
            }
            const anchors = Array.from(document.querySelectorAll("a[href]")).map((el) => ({
                text: norm(el.innerText || el.textContent || ""),
                href: el.href,
            })).filter((item) => relevant(item.text + " " + item.href));
            const storage = {};
            for (const storageName of ["localStorage", "sessionStorage"]) {
                const store = window[storageName];
                storage[storageName] = [];
                for (let i = 0; i < store.length; i++) {
                    const key = store.key(i);
                    const value = store.getItem(key) || "";
                    if (relevant(key + " " + value)) {
                        storage[storageName].push({key, value: value.slice(0, 1000)});
                    }
                }
            }
            const resources = performance.getEntriesByType("resource").map((item) => item.name)
                .filter((url) => /\\.js(\\?|$)/.test(url) || relevant(url));
            return {
                title: document.title,
                url: location.href,
                bodyTextPreview: norm(document.body ? document.body.innerText : "").slice(0, 2000),
                candidates: candidates.slice(0, 200),
                anchors: anchors.slice(0, 100),
                storage,
                resources: resources.slice(-120),
            };
        }""",
        KEYWORDS,
    )


def route_matches_from_resource(page, url: str) -> list[dict]:
    try:
        response = page.request.get(url, timeout=8000)
        if not response.ok:
            return []
        text = response.text()
    except Exception:
        return []
    if not relevant(text):
        return []
    matches = []
    patterns = [
        r"[/#][A-Za-z0-9_./?=&%-]*(?:account|balance|wallet|recharge|withdraw|fund|asset|finance)[A-Za-z0-9_./?=&%-]*",
        r"(?:账户|余额|充值|提现)[^'\\\"`\\s<>{}]{0,80}",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.I):
            start = max(match.start() - 120, 0)
            end = min(match.end() + 120, len(text))
            matches.append(
                {
                    "match": match.group(0),
                    "context": text[start:end],
                }
            )
            if len(matches) >= 30:
                return matches
    return matches


def main() -> int:
    base_url = recent_meituan_promo_url() or FALLBACK_URL
    config = cdp.load_config()
    playwright, browser = cdp.connect_browser(config)
    try:
        context = cdp.first_context(browser)
        page = cdp.reusable_page(context)
        cdp.goto_backend_page(page, base_url, timeout=90_000)
        page.wait_for_timeout(8000)
        dom = collect_dom_candidates(page)
        route_matches = []
        for url in dom.get("resources", []):
            matches = route_matches_from_resource(page, url)
            if matches:
                route_matches.append({"url": url, "matches": matches[:20]})
            if len(route_matches) >= 20:
                break
        result = {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "base_url": base_url,
            "current_url": page.url,
            "dom": dom,
            "route_matches": route_matches,
        }
        OUTPUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"美团 CDP 路由探针完成：{OUTPUT_JSON}")
        print(f"候选元素：{len(dom.get('candidates', []))}，路由命中资源：{len(route_matches)}")
        return 0
    finally:
        cdp.disconnect_browser(playwright, browser)


if __name__ == "__main__":
    raise SystemExit(main())
