from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "business-report-dashboard"
sys.path.insert(0, str(REPORT_DIR))

from chrome_cdp_reports import (  # noqa: E402
    click_text,
    connect_browser,
    disconnect_browser,
    first_context,
    goto_backend_page,
    load_config,
)


ELEME_URL = "https://melody.shop.ele.me/app/chain/93331264/store-analysis#app.chainshop.store-analysis?path=1&dateType=realTime&orderCol=valid_ord_amt&orderType=DESC"
ELEME_STATS_CENTER_URL = "https://melody.shop.ele.me/app/chain/93331264/stats__center#app.chainshop.stats.center"
MEITUAN_URL = "https://e.waimai.meituan.com/#https://waimaieapp.meituan.com/igate/bizdata/business"
OUTPUT_DIR = ROOT / "outputs" / "realtime_order_income"
LATEST_PATH = OUTPUT_DIR / "latest.json"
FAILED_PATH = OUTPUT_DIR / "last_failed.json"
RULES_PATH = ROOT / "config" / "realtime_order_income_rules.json"

TARGET_STORES = {
    "中关村": ["中关村", "中关村店", "第2号档口", "利康金桥", "第3档口", "吉祥美食城"],
    "清河": ["清河", "清河店", "第5号档口", "川湘府"],
    "安贞": ["安贞", "安贞店"],
    "金融街": ["金融街", "金融街店"],
    "丽泽": ["丽泽", "丽泽店"],
    "双井": ["双井", "双井店"],
    "五一广场": ["五一广场", "五一广场店"],
    "光谷": ["光谷", "光谷店"],
}

STORE_NAME_KEYS = [
    "shop_name",
    "shopName",
    "store_name",
    "storeName",
    "wmPoiName",
    "poiName",
    "name",
    "门店",
    "门店名称",
]

ALLOWED_API_URL_TOKENS = {
    "饿了么": ["proteinStandardQuery/TG3gM96"],
    "美团": ["/gw/bizdata/chain/business/rank"],
}

ORDER_KEYS = [
    "valid_ord_cnt",
    "valid_ord_num",
    "validOrderCount",
    "validOrderNum",
    "valid_order_count",
    "order_count",
    "orderCount",
    "orderCnt",
    "orders",
    "有效订单",
    "单量",
]
INCOME_KEYS = [
    "valid_ord_amt",
    "validOrderAmount",
    "valid_order_amount",
    "turnover",
    "revenue",
    "income",
    "amount",
    "营业收入",
    "收入",
    "营收",
]
MEITUAN_API_INCOME_KEYS = [
    "营业收入",
    "收入",
    "营收",
    "businessIncome",
    "business_income",
    "bizIncome",
    "biz_income",
    "revenue",
    "income",
]

DEFAULT_RULES = {
    "closed_stores": {},
    "meituan_page_row_validation": {
        "min_ticket": 8,
        "max_ticket": 120,
    },
}


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(message: str) -> None:
    print(f"[{now_text()}] {message}", flush=True)


def compact_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def target_store(text: str) -> str | None:
    for store, aliases in sorted(TARGET_STORES.items(), key=lambda item: -max(len(alias) for alias in item[1])):
        for alias in sorted(aliases, key=len, reverse=True):
            if alias and alias in text:
                return store
    return None


def api_url_allowed(platform: str, url: str) -> bool:
    return any(token in url for token in ALLOWED_API_URL_TOKENS.get(platform, []))


def request_scope_allowed(platform: str, response) -> bool:
    if platform != "美团":
        return True
    try:
        post_data = response.request.post_data or ""
    except Exception:
        post_data = ""
    return "durationType=5" in post_data


def source_store_name(item: dict[str, Any]) -> str:
    for key in STORE_NAME_KEYS:
        value = item.get(key)
        if value:
            return compact_text(value)
    lowered = {str(key).lower(): value for key, value in item.items()}
    for key in STORE_NAME_KEYS:
        value = lowered.get(key.lower())
        if value:
            return compact_text(value)
    for key, value in item.items():
        key_text = str(key).lower()
        if any(candidate.lower() in key_text for candidate in STORE_NAME_KEYS) and value:
            return compact_text(value)
    return ""


def target_store_from_record(item: dict[str, Any]) -> tuple[str | None, str]:
    raw_name = source_store_name(item)
    if raw_name:
        store = target_store(raw_name)
        if store:
            return store, raw_name
    text = compact_text(" ".join(str(value) for value in item.values() if isinstance(value, (str, int, float))))
    return target_store(text), raw_name


def has_metric_key(item: dict[str, Any], keys: list[str], *, partial: bool = True) -> bool:
    lowered = {str(key).lower() for key in item}
    for key in keys:
        key_lower = key.lower()
        if key in item or key_lower in lowered:
            return True
        if partial and any(key_lower in item_key for item_key in lowered):
            return True
    return False


def api_income_keys(platform: str) -> list[str]:
    if platform == "美团":
        return MEITUAN_API_INCOME_KEYS
    return INCOME_KEYS


def looks_like_store_metric_row(item: dict[str, Any], platform: str) -> bool:
    if not isinstance(item, dict):
        return False
    store, raw_name = target_store_from_record(item)
    if not store:
        return False
    has_store_key = bool(raw_name) or has_metric_key(item, STORE_NAME_KEYS)
    has_order = has_metric_key(item, ORDER_KEYS)
    has_income = has_metric_key(item, api_income_keys(platform), partial=platform != "美团")
    return has_store_key and (has_order or has_income)


def record_sort_key(record: dict[str, Any]) -> tuple[str, str, str]:
    return (str(record.get("store") or ""), str(record.get("platform") or ""), str(record.get("source_store") or ""))


def load_realtime_rules() -> dict[str, Any]:
    rules = json.loads(json.dumps(DEFAULT_RULES, ensure_ascii=False))
    try:
        payload = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return rules
    except Exception as exc:
        raise RuntimeError(f"实时采集规则配置无法读取：{exc}") from exc
    if isinstance(payload.get("closed_stores"), dict):
        rules["closed_stores"] = payload["closed_stores"]
    if isinstance(payload.get("meituan_page_row_validation"), dict):
        rules["meituan_page_row_validation"].update(payload["meituan_page_row_validation"])
    return rules


def build_api_record(item: dict[str, Any], platform: str, url: str) -> dict[str, Any] | None:
    store, raw_name = target_store_from_record(item)
    if not store:
        return None
    orders = value_by_keys(item, ORDER_KEYS)
    income = value_by_keys(item, api_income_keys(platform), partial=platform != "美团")
    if orders is None and income is None:
        return None
    return {
        "platform": platform,
        "store": store,
        "source_store": raw_name or store,
        "orders": int(round(orders or 0)),
        "income": round(float(income or 0), 2),
        "income_status": "trusted" if income is not None else "missing",
        "source": "api",
        "source_url": url,
    }


def build_dom_record(row: str, platform: str) -> dict[str, Any] | None:
    source_name = source_store_from_text(row)
    store = target_store(source_name) if source_name else target_store(row)
    if not store:
        return None
    if platform == "美团":
        orders, income, parsed_source_name = infer_meituan_realtime_row(row)
        source_name = parsed_source_name or source_name
    else:
        orders, income = infer_from_row_text(row)
    if orders is None and income is None:
        return None
    return {
        "platform": platform,
        "store": store,
        "source_store": source_name or row[:80],
        "orders": int(round(orders or 0)),
        "income": round(float(income or 0), 2),
        "income_status": "trusted" if income is not None else "missing",
        "source": "page",
        "raw": row[:280],
    }


def to_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").replace("￥", "").replace("¥", "").strip()
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def value_by_keys(item: dict[str, Any], keys: list[str], *, partial: bool = True) -> float | None:
    lowered = {str(key).lower(): value for key, value in item.items()}
    for key in keys:
        if key in item:
            value = to_number(item[key])
            if value is not None:
                return value
        value = lowered.get(key.lower())
        if value is not None:
            parsed = to_number(value)
            if parsed is not None:
                return parsed
    for key, value in item.items():
        key_text = str(key).lower()
        if partial and any(candidate.lower() in key_text for candidate in keys):
            parsed = to_number(value)
            if parsed is not None:
                return parsed
    return None


def infer_from_row_text(text: str) -> tuple[float | None, float | None]:
    cleaned = text.replace(",", "")
    income = None
    order = None

    money_matches = re.findall(r"(?:¥|￥)?\s*(\d+(?:\.\d+)?)\s*(?:元)?", cleaned)
    labeled_income = re.search(r"(?:营业收入|收入|营收|有效订单金额|订单金额)[^\d¥￥]{0,12}(?:¥|￥)?\s*(\d+(?:\.\d+)?)", cleaned)
    labeled_order = re.search(r"(?:有效订单|订单数|单量|订单)[^\d]{0,12}(\d+)", cleaned)
    unit_order = re.search(r"(\d+)\s*单", cleaned)

    if labeled_income:
        income = to_number(labeled_income.group(1))
    elif money_matches:
        decimal_values = [to_number(item) for item in money_matches if "." in item]
        income = next((item for item in decimal_values if item is not None), None)
        if income is None:
            candidates = [to_number(item) for item in money_matches]
            income = max((item for item in candidates if item is not None), default=None)

    if labeled_order:
        order = to_number(labeled_order.group(1))
    elif unit_order:
        order = to_number(unit_order.group(1))
    else:
        integers = [int(item) for item in re.findall(r"(?<!\.)\b\d{1,4}\b(?!\.)", cleaned)]
        plausible = [item for item in integers if 0 <= item <= 2000]
        if plausible:
            order = float(plausible[0])
    return order, income


def source_store_from_text(text: str) -> str:
    match = re.search(r"熊小小牛排饭POKEBEAR[·A-Za-z]*[（(][^）)]+[）)]", text)
    if match:
        return compact_text(match.group(0))
    best = ""
    for aliases in TARGET_STORES.values():
        for alias in aliases:
            if alias in text and len(alias) > len(best):
                best = alias
    return best


def infer_meituan_realtime_row(text: str) -> tuple[float | None, float | None, str]:
    source_name = source_store_from_text(text)
    tail = text
    if source_name and source_name in text:
        tail = text.split(source_name, 1)[1]
    cleaned = tail.replace(",", "")
    numbers = [to_number(item) for item in re.findall(r"-?\d+(?:\.\d+)?", cleaned)]
    numbers = [item for item in numbers if item is not None]
    if len(numbers) >= 7:
        return numbers[6], numbers[0], source_name
    orders, income = infer_from_row_text(tail)
    return orders, income, source_name


def walk_json_records(payload: Any, platform: str, url: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            if looks_like_store_metric_row(node, platform):
                record = build_api_record(node, platform, url)
                if record:
                    found.append(record)
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(payload)
    return found


def visible_store_rows(target) -> list[str]:
    return target.evaluate(
        """
        (aliases) => {
          const visible = (el) => {
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
          };
          const selector = [
            'tr',
            '[class*="table-row"]',
            '[class*="TableRow"]',
            '[class*="ant-table-row"]',
            '[class*="semi-table-row"]',
            '[class*="row"]',
            '[class*="card"]'
          ].join(',');
          const rows = [];
          const seen = new Set();
          for (const el of Array.from(document.querySelectorAll(selector))) {
            if (!visible(el)) continue;
            const text = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
            if (!text || text.length > 900) continue;
            if (!aliases.some((alias) => text.includes(alias))) continue;
            if (seen.has(text)) continue;
            seen.add(text);
            rows.push(text);
          }
          return rows;
        }
        """,
        [alias for aliases in TARGET_STORES.values() for alias in aliases],
    )


def parse_dom_records(target, platform: str) -> list[dict[str, Any]]:
    records = []
    try:
        rows = visible_store_rows(target)
    except Exception:
        return records
    for row in rows:
        record = build_dom_record(row, platform)
        if record:
            records.append(record)
    return records


def merge_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for record in records:
        store = record.get("store")
        platform = record.get("platform")
        if store not in TARGET_STORES or platform not in {"饿了么", "美团"}:
            continue
        key = (platform, store)
        current = merged.get(key)
        if not current:
            merged[key] = record
            continue
        current_score = (
            1 if current.get("income_status", "trusted") == "trusted" else 0,
            1 if int(current.get("orders") or 0) > 0 else 0,
            1 if float(current.get("income") or 0) > 0 else 0,
            1 if current.get("source") == "api" else 0,
            1 if current.get("source_store") else 0,
            float(current.get("income") or 0),
        )
        new_score = (
            1 if record.get("income_status", "trusted") == "trusted" else 0,
            1 if int(record.get("orders") or 0) > 0 else 0,
            1 if float(record.get("income") or 0) > 0 else 0,
            1 if record.get("source") == "api" else 0,
            1 if record.get("source_store") else 0,
            float(record.get("income") or 0),
        )
        if new_score >= current_score:
            merged[key] = record
    return sorted(merged.values(), key=record_sort_key)


def apply_closed_store_rules(records: list[dict[str, Any]], rules: dict[str, Any]) -> list[dict[str, Any]]:
    closed_stores = rules.get("closed_stores") or {}
    normalized = []
    for record in records:
        item = dict(record)
        store_rule = closed_stores.get(item.get("store"))
        platforms = set((store_rule or {}).get("platforms") or [])
        if store_rule and (not platforms or item.get("platform") in platforms):
            original_orders = int(item.get("orders") or 0)
            original_income = round(float(item.get("income") or 0), 2)
            if original_orders or original_income:
                item["original_orders"] = original_orders
                item["original_income"] = original_income
            item["orders"] = 0
            item["income"] = 0
            item["income_status"] = "trusted"
            item["validation_note"] = store_rule.get("reason") or "门店配置为闭店，实时订单和营业额强制为 0。"
        normalized.append(item)
    return normalized


def realtime_validation_errors(records: list[dict[str, Any]], rules: dict[str, Any]) -> list[str]:
    validation = rules.get("meituan_page_row_validation") or {}
    min_ticket = float(validation.get("min_ticket") or 0)
    max_ticket = float(validation.get("max_ticket") or 0)
    errors = []
    for item in records:
        if item.get("platform") != "美团" or item.get("source") != "page":
            continue
        orders = int(item.get("orders") or 0)
        income = float(item.get("income") or 0)
        if orders == 0 and income == 0:
            continue
        if orders == 0 or income == 0:
            errors.append(f"美团实时行疑似错列：{item.get('store')} 订单 {orders}，收入 {income:.2f}，raw={item.get('raw')}")
            continue
        ticket = income / orders
        if (min_ticket and ticket < min_ticket) or (max_ticket and ticket > max_ticket):
            errors.append(f"美团实时行客单价异常：{item.get('store')} {ticket:.2f} 元/单，订单 {orders}，收入 {income:.2f}，raw={item.get('raw')}")
    return errors


def page_for_platform(context, url: str, url_markers: list[str]):
    for page in context.pages:
        if page.is_closed():
            continue
        current_url = page.url or ""
        if any(marker in current_url for marker in url_markers):
            return page, False
    page = context.new_page()
    return page, True


def closed_page_error(exc: Exception) -> bool:
    text = str(exc)
    return any(
        marker in text
        for marker in [
            "Target page, context or browser has been closed",
            "has been closed",
            "Browser closed",
            "Target closed",
        ]
    )


def new_platform_page(context):
    page = context.new_page()
    page.set_default_timeout(10_000)
    return page


def close_platform_pages(context, url_markers: list[str]) -> None:
    for page in list(context.pages):
        try:
            if any(marker in (page.url or "") for marker in url_markers):
                page.close()
        except Exception:
            pass


def platform_target_count(items: list[dict[str, Any]], platform: str) -> int:
    merged = merge_records(items)
    return len(
        {
            item.get("store")
            for item in merged
            if item.get("platform") == platform and item.get("store") in TARGET_STORES
        }
    )


def collect_api_responses(page, platform: str) -> tuple[list[dict[str, Any]], Any]:
    records: list[dict[str, Any]] = []

    def on_response(response) -> None:
        if not api_url_allowed(platform, response.url):
            return
        if not request_scope_allowed(platform, response):
            return
        ctype = (response.headers or {}).get("content-type", "")
        if "json" not in ctype and "proteinStandardQuery" not in response.url and "/gw/bizdata/" not in response.url:
            return
        try:
            payload = response.json()
        except Exception:
            return
        records.extend(walk_json_records(payload, platform, response.url))

    page.on("response", on_response)
    return records, on_response


def click_next_page(target) -> bool:
    try:
        return bool(
            target.evaluate(
                """
                () => {
                  const disabled = (el) =>
                    el.disabled ||
                    el.getAttribute('aria-disabled') === 'true' ||
                    /disabled/.test(el.className || '');
                  const visible = (el) => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
                  };
                  const candidates = Array.from(document.querySelectorAll('button,li,a,span')).filter(visible);
                  const next = candidates.find((el) => {
                    const text = (el.innerText || el.textContent || el.getAttribute('title') || el.getAttribute('aria-label') || '').trim();
                    return !disabled(el) && /下一页|Next|next|›|>/.test(text);
                  });
                  if (!next) return false;
                  const target = next.closest('button,li,a') || next;
                  if (disabled(target)) return false;
                  target.click();
                  return true;
                }
                """
            )
        )
    except Exception:
        return False


def dismiss_eleme_blocking_overlays(page) -> None:
    try:
        page.evaluate(
            """
            () => {
              for (const selector of ['[class*="updateBtn"]', '[class*="close"]', '[aria-label="Close"]']) {
                const el = document.querySelector(selector);
                if (el) {
                  el.click();
                  return;
                }
              }
              document.querySelectorAll('[class*="updateModal"]').forEach((el) => el.remove());
            }
            """
        )
    except Exception:
        pass


def click_eleme_store_analysis(page) -> None:
    dismiss_eleme_blocking_overlays(page)
    try:
        page.get_by_text("门店分析", exact=True).last.click(timeout=5000, force=True)
        return
    except Exception:
        pass
    try:
        page.locator("li").filter(has_text="门店分析").last.click(timeout=5000, force=True)
    except Exception:
        click_text(page, "门店分析", timeout=3000)


def scrape_eleme(context, timeout_ms: int) -> list[dict[str, Any]]:
    page, is_new = page_for_platform(context, ELEME_URL, ["melody.shop.ele.me", "lsycm.alibaba.com"])
    page.set_default_timeout(10_000)
    page.set_default_navigation_timeout(min(timeout_ms, 30_000))
    api_records, handler = collect_api_responses(page, "饿了么")
    captured_rank_request: dict[str, Any] = {}
    dom_records: list[dict[str, Any]] = []

    def on_request(request) -> None:
        if "proteinStandardQuery/TG3gM96" not in request.url:
            return
        post_data = request.post_data
        if not post_data:
            return
        try:
            payload = json.loads(post_data)
        except Exception:
            return
        captured_rank_request["url"] = request.url
        captured_rank_request["payload"] = payload
        captured_rank_request["headers"] = {
            key: value
            for key, value in (request.headers or {}).items()
            if key.lower() not in {"accept-encoding", "content-length", "cookie", "host"}
        }

    try:
        log("饿了么：开始")
        page.on("request", on_request)
        log("饿了么：进入实时门店页")
        try:
            page.goto("about:blank", wait_until="commit", timeout=10_000)
            page.wait_for_timeout(800)
        except Exception:
            pass
        page.goto(ELEME_URL, wait_until="commit", timeout=min(timeout_ms, 45_000))
        try:
            page.reload(wait_until="commit", timeout=min(timeout_ms, 45_000))
        except Exception:
            pass
        page.wait_for_timeout(18_000)
        dismiss_eleme_blocking_overlays(page)
        if not captured_rank_request:
            try:
                log("饿了么：未捕获门店接口，尝试进入门店分析")
                page.goto(ELEME_STATS_CENTER_URL, wait_until="commit", timeout=min(timeout_ms, 30_000))
                page.wait_for_timeout(5000)
                click_eleme_store_analysis(page)
                page.wait_for_timeout(18_000)
            except Exception:
                page.wait_for_timeout(3000)
        if captured_rank_request:
            try:
                log("饿了么：用登录态补拉分页接口")
                page_payloads = fetch_eleme_rank_pages(context, captured_rank_request)
                for payload in page_payloads:
                    api_records.extend(walk_json_records(payload, "饿了么", captured_rank_request["url"]))
            except Exception:
                pass
        for page_index in range(2, 7):
            if not click_next_page(page):
                break
            log(f"饿了么：自动翻到第 {page_index} 页")
            page.wait_for_timeout(6000)
            dom_records.extend(parse_dom_records(page, "饿了么"))
        log(f"饿了么：捕获 {len(api_records)} 条接口记录")
        dom_records.extend(parse_dom_records(page, "饿了么"))
    finally:
        try:
            page.remove_listener("response", handler)
        except Exception:
            pass
        try:
            page.remove_listener("request", on_request)
        except Exception:
            pass
    result = merge_records([*api_records, *dom_records])
    log(f"饿了么：完成 {len(result)} 个目标门店")
    return result


def fetch_eleme_rank_pages(context, captured_request: dict[str, Any]) -> list[dict[str, Any]]:
    cookies = context.cookies("https://lsycm.alibaba.com")
    cookie_header = "; ".join(f"{item['name']}={item['value']}" for item in cookies)
    headers = {
        key: value
        for key, value in (captured_request.get("headers") or {}).items()
        if key.lower() not in {"accept-encoding", "content-length", "host", "cookie"}
    }
    headers["cookie"] = cookie_header
    headers["content-type"] = "application/json"
    payloads: list[dict[str, Any]] = []
    base_payload = captured_request.get("payload") or {}
    for current in [1, 2, 3, 4]:
        body = dict(base_payload)
        body["current"] = current
        body["pageSize"] = 10
        data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(captured_request["url"], data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=12) as response:
                text = response.read().decode("utf-8", "replace")
            payload = json.loads(text)
        except Exception:
            continue
        payloads.append(payload)
    return payloads


MEITUAN_REALTIME_ACTIVE_SCRIPT = """
() => {
  const normalize = (value) => String(value || '').replace(/\\s+/g, '').trim();
  const visible = (el) => {
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
  };
  const hasSelectedMarker = (el) => {
    let node = el;
    for (let depth = 0; node && depth < 5; depth += 1, node = node.parentElement) {
      const classText = String(node.className || '').toLowerCase();
      const classTokens = classText.split(/\\s+/).filter(Boolean);
      if (classTokens.some((token) => (
        token === 'active' ||
        token === 'selected' ||
        token === 'current' ||
        token === 'checked' ||
        token === 'is-active' ||
        token === 'is-selected' ||
        token === 'ant-radio-button-wrapper-checked'
      ))) {
        return true;
      }
      for (const attr of ['aria-selected', 'aria-pressed', 'aria-current', 'checked', 'selected', 'data-selected', 'data-active', 'data-current']) {
        const value = node.getAttribute && node.getAttribute(attr);
        if (value && !['false', '0', 'none'].includes(String(value).toLowerCase())) {
          return true;
        }
      }
    }
    return false;
  };
  return Array.from(document.querySelectorAll('.selector-item,[role="tab"],[role="button"],button,div,span'))
    .some((el) => visible(el) && normalize(el.innerText || el.textContent) === '今日实时' && hasSelectedMarker(el));
}
"""


def meituan_realtime_active(page) -> bool:
    for target in [page, *page.frames]:
        try:
            active = target.evaluate(MEITUAN_REALTIME_ACTIVE_SCRIPT)
            if active:
                return True
        except Exception:
            pass
    return False


def meituan_realtime_switch_diagnostics(page) -> str:
    snapshots: list[str] = []
    script = """
    () => Array.from(document.querySelectorAll('.selector-item,[role="tab"],[role="button"],button'))
      .map((el) => ({
        text: String(el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 40),
        className: String(el.className || '').slice(0, 120),
        ariaSelected: el.getAttribute('aria-selected') || '',
        ariaPressed: el.getAttribute('aria-pressed') || '',
        dataSelected: el.getAttribute('data-selected') || '',
        dataActive: el.getAttribute('data-active') || '',
      }))
      .filter((item) => item.text.includes('今日') || item.text.includes('实时'))
      .slice(0, 8)
    """
    for index, target in enumerate([page, *page.frames]):
        try:
            url = getattr(target, "url", "") or ""
            items = target.evaluate(script)
        except Exception:
            continue
        if items:
            snapshots.append(f"frame{index} url={url} controls={json.dumps(items, ensure_ascii=False)}")
    if not snapshots:
        return "未找到包含今日/实时的可见切换控件。"
    return "；".join(snapshots)[:1200]


def page_requires_login(page, platform: str) -> bool:
    login_markers = ["账号登录", "验证码登录", "忘记密码", "登录", "安全验证", "验证码", "身份核实", "拖动滑块"]
    platform_markers = {
        "美团": ["美团外卖商家版", "e.waimai.meituan.com/new_fe/login", "verify.meituan.com"],
        "饿了么": ["饿了么", "melody.shop.ele.me"],
    }
    for target in [page, *page.frames]:
        try:
            text = target.evaluate("() => document.body ? document.body.innerText.slice(0, 1200) : ''")
            url = getattr(target, "url", "") or ""
        except Exception:
            continue
        if any(marker in url or marker in text for marker in platform_markers.get(platform, [])) and any(
            marker in text for marker in login_markers
        ):
            return True
    return False


def page_snapshot_text(page, limit: int = 6000) -> str:
    parts: list[str] = []
    for target in [page, *page.frames]:
        try:
            text = target.evaluate("() => document.body ? document.body.innerText : ''")
        except Exception:
            continue
        if text:
            parts.append(compact_text(text))
    return "\n".join(parts)[:limit]


def click_meituan_realtime(target) -> bool:
    try:
        return bool(
            target.evaluate(
                """
                () => {
                  const visible = (el) => {
                    const rect = el.getBoundingClientRect();
                    const style = getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
                  };
                  const button = Array.from(document.querySelectorAll('.selector-item,button,div,span'))
                    .find((el) => visible(el) && (el.innerText || el.textContent || '').replace(/\\s+/g, '').trim() === '今日实时');
                  if (!button) return false;
                  button.scrollIntoView({ block: 'center', inline: 'center' });
                  for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
                    button.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window }));
                  }
                  return true;
                }
                """
            )
        )
    except Exception:
        return False


MEITUAN_ALL_STORES_ACTIVE_SCRIPT = """
() => {
  const visible = (el) => {
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
  };
  const normalize = (value) => String(value || '').replace(/\\s+/g, '').trim();
  const isAllStores = (value) => {
    const text = normalize(value);
    return text === '全部门店' || /^全部门店（共\\d+家）$/.test(text) || /^全部门店\\(共\\d+家\\)$/.test(text);
  };
  const headerActive = Array.from(document.querySelectorAll('[class*="current-poi"],[class*="container_2x38j6"]'))
    .some((el) => visible(el) && isAllStores(el.innerText || el.textContent || el.getAttribute('title')));
  const body = document.body ? document.body.innerText : '';
  return headerActive || /^全部门店(?:（共\\d+家）|\\(共\\d+家\\))?\\s*xxxnpf/m.test(body);
}
"""


def meituan_all_stores_active(page) -> bool:
    for target in [page, *page.frames]:
        try:
            if target.evaluate(MEITUAN_ALL_STORES_ACTIVE_SCRIPT):
                return True
        except Exception:
            pass
    return False


def click_meituan_store_dropdown(target) -> bool:
    for selector in ['[class*="current-poi"]', '[class*="container_2x38j6"]']:
        try:
            target.locator(selector).first.click(timeout=3000, force=True)
            return True
        except Exception:
            pass
    try:
        return bool(
            target.evaluate(
                """
                () => {
                  const visible = (el) => {
                    const rect = el.getBoundingClientRect();
                    const style = getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
                  };
                  const current = Array.from(document.querySelectorAll('[class*="current-poi"],[class*="container_2x38j6"]'))
                    .find((el) => visible(el) && /熊小小|全部门店/.test(el.innerText || el.textContent || el.getAttribute('title') || ''));
                  if (!current) return false;
                  current.scrollIntoView({ block: 'center', inline: 'center' });
                  for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
                    current.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window }));
                  }
                  return true;
                }
                """
            )
        )
    except Exception:
        return False


def click_meituan_all_stores_option(target) -> bool:
    option_texts = ["全部门店（共9家）", "全部门店"]
    for text in option_texts:
        try:
            target.get_by_text(text, exact=True).first.click(timeout=5000, force=True)
            return True
        except Exception:
            pass
        try:
            target.locator(f'[title="{text}"]').first.click(timeout=5000, force=True)
            return True
        except Exception:
            pass
    try:
        return bool(
            target.evaluate(
                """
                () => {
                  const visible = (el) => {
                    const rect = el.getBoundingClientRect();
                    const style = getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
                  };
                  const normalize = (value) => String(value || '').replace(/\\s+/g, '').trim();
                  const isAllStores = (value) => {
                    const text = normalize(value);
                    return text === '全部门店' || /^全部门店（共\\d+家）$/.test(text) || /^全部门店\\(共\\d+家\\)$/.test(text);
                  };
                  const option = Array.from(document.querySelectorAll('li,div,span,[role="button"],button'))
                    .find((el) => visible(el) && isAllStores(el.innerText || el.textContent || el.getAttribute('title')));
                  if (!option) return false;
                  option.scrollIntoView({ block: 'center', inline: 'center' });
                  for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
                    option.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window }));
                  }
                  return true;
                }
                """
            )
        )
    except Exception:
        return False


def click_meituan_all_stores(page) -> None:
    if meituan_all_stores_active(page):
        return
    for attempt in range(3):
        for target in [page, *page.frames]:
            if click_meituan_store_dropdown(target):
                page.wait_for_timeout(1200)
                break
        for target in [page, *page.frames]:
            if click_meituan_all_stores_option(target):
                page.wait_for_timeout(5000 + attempt * 1000)
                if meituan_all_stores_active(page):
                    return
                break
        if meituan_all_stores_active(page):
            return
    body = page_snapshot_text(page)
    single_store = re.search(r"熊小小牛排饭POKEBEAR[（(]([^）)]+店)[）)]", body)
    if single_store:
        raise RuntimeError(
            f"美团当前停留在单店上下文：{single_store.group(1)}，"
            "未能自动切回全部门店，无法采集 8 家门店。"
        )
    raise RuntimeError("美团未能自动切回全部门店，无法采集 8 家门店。")


def click_meituan_realtime_and_scroll(page) -> None:
    for target in [page, *page.frames]:
        try:
            target.get_by_text("营收", exact=False).first.click(timeout=2000)
            page.wait_for_timeout(1000)
            break
        except Exception:
            pass
    for attempt in range(3):
        for target in [page, *page.frames]:
            if click_meituan_realtime(target):
                page.wait_for_timeout(3000 + attempt * 1000)
                if meituan_realtime_active(page):
                    break
            try:
                target.locator(".selector-item", has_text="今日实时").first.click(timeout=3000)
                page.wait_for_timeout(3000 + attempt * 1000)
                if meituan_realtime_active(page):
                    break
            except Exception:
                pass
        if meituan_realtime_active(page):
            break
    if not meituan_realtime_active(page):
        diagnostics = meituan_realtime_switch_diagnostics(page)
        raise RuntimeError(f"美团页面未确认切换到今日实时：{diagnostics}")
    for _ in range(8):
        for target in [page, *page.frames]:
            try:
                target.evaluate("() => window.scrollBy(0, Math.max(700, window.innerHeight * 0.85))")
            except Exception:
                pass
        page.mouse.wheel(0, 900)
        page.wait_for_timeout(900)


def scrape_meituan_once(context, timeout_ms: int) -> list[dict[str, Any]]:
    page = new_platform_page(context)
    page.set_default_timeout(10_000)
    page.set_default_navigation_timeout(min(timeout_ms, 30_000))
    api_records, handler = collect_api_responses(page, "美团")
    dom_records: list[dict[str, Any]] = []
    try:
        log("美团：开始")
        log("美团：进入实时经营页")
        page.goto(MEITUAN_URL, wait_until="commit", timeout=min(timeout_ms, 45_000))
        page.wait_for_timeout(7000)
        if page_requires_login(page, "美团"):
            raise RuntimeError("美团登录态失效：当前打开的是登录/验证码页面")
        click_meituan_all_stores(page)
        click_meituan_realtime_and_scroll(page)
        for target in [page, *page.frames]:
            dom_records.extend(parse_dom_records(target, "美团"))
    finally:
        try:
            page.remove_listener("response", handler)
        except Exception:
            pass
    result = merge_records([*api_records, *dom_records])
    log(f"美团：完成 {len(result)} 个目标门店")
    if not result:
        body = page_snapshot_text(page)
        single_store = re.search(r"熊小小牛排饭POKEBEAR[（(]([^）)]+店)[）)]", body)
        if single_store and ("今日实时数据" in body or "营业收入" in body or "订单量" in body):
            raise RuntimeError(
                f"美团当前停留在单店上下文：{single_store.group(1)}，"
                "未进入连锁/全部门店实时排行，无法采集 8 家门店。"
            )
    return result


def scrape_meituan(context, timeout_ms: int) -> list[dict[str, Any]]:
    last_error: Exception | None = None
    for attempt in range(1, 3):
        try:
            if attempt > 1:
                log("美团：页面被平台关闭，重开页面后重试")
            return scrape_meituan_once(context, timeout_ms)
        except Exception as exc:
            last_error = exc
            if not closed_page_error(exc) or attempt >= 2:
                break
            time.sleep(2)
    if last_error:
        raise last_error
    return []


def build_payload(items: list[dict[str, Any]], errors: list[str]) -> dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    by_store: dict[str, dict[str, Any]] = {}
    for store in TARGET_STORES:
        store_items = [item for item in items if item.get("store") == store]
        by_store[store] = {
            "store": store,
            "orders": sum(int(item.get("orders") or 0) for item in store_items),
            "income": round(sum(float(item.get("income") or 0) for item in store_items), 2),
            "platforms": {
                item["platform"]: {
                    "orders": int(item.get("orders") or 0),
                    "income": round(float(item.get("income") or 0), 2),
                    "income_status": item.get("income_status") or "trusted",
                    "source": item.get("source"),
                    "source_store": item.get("source_store"),
                    "validation_note": item.get("validation_note"),
                    "original_orders": item.get("original_orders"),
                    "original_income": item.get("original_income"),
                }
                for item in store_items
            },
        }
    missing = [
        {"platform": platform, "store": store}
        for store in TARGET_STORES
        for platform in ["饿了么", "美团"]
        if not any(item.get("store") == store and item.get("platform") == platform for item in items)
    ]
    income_missing = [
        {"platform": item.get("platform"), "store": item.get("store"), "source": item.get("source")}
        for item in items
        if item.get("income_status", "trusted") != "trusted"
    ]
    payload = {
        "generated_at": now_text(),
        "status": "ok" if not errors and not missing and not income_missing else "partial",
        "source_urls": {"饿了么": ELEME_URL, "美团": MEITUAN_URL},
        "target_stores": list(TARGET_STORES),
        "summary": {
            "store_count": len([store for store, item in by_store.items() if item["platforms"]]),
            "platform_store_count": len(items),
            "total_orders": sum(item["orders"] for item in by_store.values()),
            "total_income": round(sum(item["income"] for item in by_store.values()), 2),
            "missing_count": len(missing),
            "income_missing_count": len(income_missing),
        },
        "stores": list(by_store.values()),
        "items": items,
        "missing": missing,
        "income_missing": income_missing,
        "errors": errors,
    }
    return payload


def save_payload(items: list[dict[str, Any]], errors: list[str]) -> dict[str, Any]:
    payload = build_payload(items, errors)
    summary = payload["summary"]
    if (
        errors
        or summary["missing_count"] > 0
        or summary.get("income_missing_count", 0) > 0
        or summary["platform_store_count"] < len(TARGET_STORES) * 2
    ):
        payload["status"] = "failed"
        FAILED_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        history_path = OUTPUT_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.failed.jsonl"
        with history_path.open("a", encoding="utf-8") as history:
            history.write(json.dumps(payload, ensure_ascii=False) + "\n")
        raise RuntimeError("未采集齐全部真实平台门店数据或可信收入，已拒绝覆盖 latest.json")

    LATEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    history_path = OUTPUT_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.jsonl"
    with history_path.open("a", encoding="utf-8") as history:
        history.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return payload


def read_existing_items() -> list[dict[str, Any]]:
    try:
        payload = json.loads(LATEST_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    items = payload.get("items")
    return items if isinstance(items, list) else []


def main() -> int:
    parser = argparse.ArgumentParser(description="采集双平台实时单量和收入")
    parser.add_argument("--platform", choices=["all", "eleme", "meituan"], default="all")
    parser.add_argument("--timeout-ms", type=int, default=90_000)
    args = parser.parse_args()

    config = load_config()
    rules = load_realtime_rules()
    playwright, browser = connect_browser(config)
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        context = first_context(browser)
        if args.platform in {"all", "eleme"}:
            eleme_records: list[dict[str, Any]] = []
            for attempt in range(1, 3):
                try:
                    eleme_records = scrape_eleme(context, args.timeout_ms)
                    completed = platform_target_count(eleme_records, "饿了么")
                    if completed >= len(TARGET_STORES):
                        break
                    log(f"饿了么：仅完成 {completed} 个目标门店，重开页面重试")
                    close_platform_pages(context, ["melody.shop.ele.me", "lsycm.alibaba.com"])
                    context = first_context(browser)
                except Exception as exc:
                    if attempt >= 2:
                        errors.append(f"饿了么采集失败：{exc}")
                    else:
                        log(f"饿了么：采集异常，重开页面重试：{exc}")
                        close_platform_pages(context, ["melody.shop.ele.me", "lsycm.alibaba.com"])
                        context = first_context(browser)
            records.extend(eleme_records)
            completed = platform_target_count(eleme_records, "饿了么")
            if completed < len(TARGET_STORES):
                errors.append(f"饿了么采集不完整：仅完成 {completed}/{len(TARGET_STORES)} 个目标门店")
        if args.platform in {"all", "meituan"}:
            try:
                records.extend(scrape_meituan(context, args.timeout_ms))
            except Exception as exc:
                if closed_page_error(exc):
                    try:
                        log("美团：浏览器连接已关闭，重新连接后再试一次")
                        disconnect_browser(playwright, browser)
                        playwright, browser = connect_browser(config)
                        context = first_context(browser)
                        records.extend(scrape_meituan(context, args.timeout_ms))
                    except Exception as retry_exc:
                        errors.append(f"美团采集失败：{retry_exc}")
                else:
                    errors.append(f"美团采集失败：{exc}")
    finally:
        disconnect_browser(playwright, browser)

    merged_records = apply_closed_store_rules(merge_records(records), rules)
    if args.platform != "all":
        existing = read_existing_items()
        other_platform = "美团" if args.platform == "eleme" else "饿了么"
        merged_records = apply_closed_store_rules(merge_records([*merged_records, *[item for item in existing if item.get("platform") == other_platform]]), rules)
    errors.extend(realtime_validation_errors(merged_records, rules))
    payload = save_payload(merged_records, errors)
    summary = payload["summary"]
    print(f"实时单量收入已更新：{LATEST_PATH}")
    print(f"覆盖 {summary['platform_store_count']} 个平台门店，合计 {summary['total_orders']} 单，收入 {summary['total_income']:.2f} 元")
    if errors:
        print("；".join(errors), file=sys.stderr)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
