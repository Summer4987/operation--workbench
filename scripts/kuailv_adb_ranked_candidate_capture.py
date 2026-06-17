from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from kuailv_order_dry_run import (
    ADB_COMMON_PATHS,
    CHANNEL,
    DEFAULT_SERVER,
    DEFAULT_TOKEN,
    analyze_cart_review_xml,
    bounds_center,
    build_line_plan,
    detect_page_text,
    eligible_orders,
    is_product_detail_page,
    node_text,
    parse_ui_nodes,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "kuailv_adb_ranked_candidates"
LATEST_PATH = OUTPUT_DIR / "latest.json"


EXCLUDED_TITLE_WORDS = [
    "搜索",
    "购物车",
    "去结算",
    "合计",
    "全选",
    "加入购物车",
    "选规格",
    "月售",
    "买过",
    "同品",
    "低价",
    "配送",
    "首页",
    "冻品",
    "分类",
    "推荐",
    "全部",
    "销量第",
    "回购率第",
    "口碑好货",
    "新鲜蔬菜",
    "热销精选",
    "蔬菜豆制品",
    "肉禽水产蛋",
]

SPEC_CONTROL_WORDS = ["选规格", "全部规格", "更多规格"]
SPEC_MODAL_BLOCK_WORDS = ["提交订单", "立即支付", "确认支付", "去支付", "切换地址", "收货地址"]


def now_text() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S%z")


def run_command(args: list[str], timeout: int) -> dict[str, Any]:
    try:
        result = subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)
        return {"args": args, "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
    except Exception as exc:
        return {"args": args, "returncode": -1, "stdout": "", "stderr": str(exc)}


def adb_executable() -> str:
    env_path = os.environ.get("ANDROID_ADB_BIN", "").strip()
    candidates = [Path(env_path)] if env_path else []
    found = shutil.which("adb")
    if found:
        candidates.append(Path(found))
    candidates.extend(ADB_COMMON_PATHS)
    for candidate in candidates:
        if candidate and candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return "adb"


def adb_base(serial: str) -> list[str]:
    base = [adb_executable()]
    if serial:
        base.extend(["-s", serial])
    return base


def read_json_url(url: str, timeout: int) -> dict[str, Any]:
    import urllib.parse
    import urllib.request

    request = urllib.request.Request(url, headers={"User-Agent": "kuailv-adb-ranked-candidate-capture/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def admin_summary_url(server: str, token: str) -> str:
    import urllib.parse

    query = urllib.parse.urlencode({"status": "all", "token": token})
    return f"{server.rstrip('/')}/daily-order/api/admin/summary?{query}"


def load_order(server: str, token: str, date_text: str, order_id: str, timeout: int) -> dict[str, Any]:
    payload = read_json_url(admin_summary_url(server, token), timeout)
    candidates = eligible_orders(payload, date_text, order_id)
    if not candidates:
        suffix = f"订单 {order_id}" if order_id else f"{date_text} 的快驴订单"
        raise RuntimeError(f"没有找到{suffix}。")
    return candidates[0]


def kuailv_items(order: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in order.get("items") or [] if str(item.get("purchase_channel") or "") == CHANNEL]


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def visible_nodes(xml_text: str) -> list[dict[str, Any]]:
    rows = []
    for node in parse_ui_nodes(xml_text):
        text = node_text(node)
        bounds = node.get("bounds") or []
        if not text or len(bounds) != 4:
            continue
        if bounds == [0, 0, 0, 0] or bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
            continue
        rows.append(node)
    rows.sort(key=lambda item: (item["bounds"][1], item["bounds"][0]))
    return rows


def display_text(node: dict[str, Any]) -> str:
    return str(node.get("text") or node.get("content-desc") or "").strip()


def looks_like_title(text: str, bounds: list[int]) -> bool:
    x1, y1, x2, y2 = bounds
    if not (40 <= x1 <= 650 and 250 <= y1 <= 2120 and x2 - x1 >= 90):
        return False
    if not re.search(r"[\u4e00-\u9fff]", text):
        return False
    if any(word in text for word in EXCLUDED_TITLE_WORDS):
        return False
    if "¥" in text or "￥" in text or re.fullmatch(r"\d+(?:\.\d+)?", text):
        return False
    if re.fullmatch(r"[\d.]+(?:斤|kg|g|克|袋|盒|箱|桶|瓶|个).*", normalize_text(text)):
        return False
    return True


def row_texts(nodes: list[dict[str, Any]], y1: int, y2: int) -> list[dict[str, Any]]:
    rows = []
    for node in nodes:
        bounds = node.get("bounds") or []
        if len(bounds) != 4:
            continue
        _cx, cy = bounds_center(tuple(bounds))
        if y1 <= cy <= y2 and 20 <= bounds[0] <= 1060:
            rows.append({"text": node_text(node), "bounds": bounds})
    rows.sort(key=lambda item: (item["bounds"][1], item["bounds"][0]))
    return rows


def clean_card_texts(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for node in nodes:
        text = display_text(node)
        bounds = node.get("bounds") or []
        if not text or len(bounds) != 4:
            continue
        if bounds == [0, 0, 0, 0] or bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
            continue
        if re.fullmatch(r"[\ue000-\uf8ff]+", text):
            continue
        rows.append({"text": text, "bounds": bounds})
    rows.sort(key=lambda item: (item["bounds"][1], item["bounds"][0]))
    return rows


def card_texts_in_bounds(nodes: list[dict[str, Any]], card_bounds: list[int]) -> list[dict[str, Any]]:
    rows = clean_card_texts(nodes)
    if len(card_bounds) != 4:
        return rows
    x1, y1, x2, y2 = card_bounds
    bounded = []
    for row in rows:
        cx, cy = bounds_center(tuple(row["bounds"]))
        if x1 <= cx <= x2 and y1 <= cy <= y2:
            bounded.append(row)
    return bounded


def looks_like_card_title(text: str, bounds: list[int]) -> bool:
    x1, _y1, x2, _y2 = bounds
    if not (240 <= x1 <= 760 and x2 - x1 >= 90):
        return False
    if not re.search(r"[\u4e00-\u9fff]", text):
        return False
    if any(word in text for word in EXCLUDED_TITLE_WORDS):
        return False
    if any(word in text for word in ["进店", "同品", "回购率第", "销量第", "低价", "客诉", "口碑"]):
        return False
    if "¥" in text or "￥" in text or re.fullmatch(r"\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?)?", text):
        return False
    if re.fullmatch(r"[\d.]+(?:斤|kg|g|克|袋|盒|箱|桶|瓶|个).*", normalize_text(text)):
        return False
    return True


def numeric_price_value(text: str) -> float:
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(?:-(\d+(?:\.\d+)?))?", text.strip())
    if not match:
        return 0.0
    return float(match.group(1))


def parse_card_best_offer(rows: list[dict[str, Any]]) -> tuple[str, float]:
    offers = parse_card_offer_rows(rows)
    if not offers:
        return "", parse_price([row["text"] for row in rows])
    best = min(offers, key=lambda item: item["price"])
    return str(best.get("spec") or ""), float(best.get("price") or 0)


def parse_card_offer_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    offers: list[dict[str, Any]] = []
    seen: set[tuple[str, float, int]] = set()
    for row in rows:
        price = numeric_price_value(row["text"])
        if price <= 0:
            continue
        _cx, cy = bounds_center(tuple(row["bounds"]))
        same_line = [candidate for candidate in rows if abs(bounds_center(tuple(candidate["bounds"]))[1] - cy) <= 42]
        if not any("/" in candidate["text"] for candidate in same_line):
            continue
        if not any(candidate["text"] in {"¥", "￥"} or "¥" in candidate["text"] or "￥" in candidate["text"] for candidate in same_line):
            continue
        spec = ""
        for candidate in same_line:
            if re.fullmatch(r"\d+(?:\.\d+)?(?:斤|kg|g|克|袋|盒|箱|桶|瓶|个)", normalize_text(candidate["text"])):
                spec = candidate["text"]
                break
        key = (spec, price, int(cy / 20))
        if spec and key not in seen:
            seen.add(key)
            offers.append({"spec": spec, "price": price, "bounds": row["bounds"]})
    return offers


def has_explicit_pack_text(text: str) -> bool:
    return bool(re.search(r"\d+(?:\.\d+)?\s*(?:斤|kg|g|克|袋|盒|箱|桶|瓶|个)", normalize_text(text)))


def row_text(row: dict[str, Any]) -> str:
    return str(row.get("text") or "")


def spec_modal_content_bounds(xml_text: str) -> list[int] | None:
    modal_bounds: list[list[int]] = []
    for node in parse_ui_nodes(xml_text):
        bounds = node.get("bounds") or []
        if len(bounds) != 4 or bounds == [0, 0, 0, 0] or bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
            continue
        resource_id = str(node.get("resource_id") or node.get("resource-id") or "")
        text = node_text(node)
        if "bottom_layout" in resource_id or text in {"规格", "选择规格", "商品规格"}:
            if bounds[3] - bounds[1] >= 80 and bounds[2] - bounds[0] >= 500:
                modal_bounds.append(bounds)
    if not modal_bounds:
        return None
    modal_bounds.sort(key=lambda item: ((item[3] - item[1]) * (item[2] - item[0]), item[1]), reverse=True)
    return modal_bounds[0]


def product_card_groups(xml_text: str) -> list[dict[str, Any]]:
    nodes = parse_ui_nodes(xml_text)
    cards: list[tuple[int, dict[str, Any]]] = []
    for index, node in enumerate(nodes):
        text = node_text(node)
        bounds = node.get("bounds") or []
        if "complex-card-goods" not in text:
            continue
        if len(bounds) != 4 or bounds == [0, 0, 0, 0] or bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
            continue
        if bounds[3] < 260 or bounds[1] > 2200:
            continue
        cards.append((index, node))
    groups = []
    for card_index, (start, card) in enumerate(cards):
        end = cards[card_index + 1][0] if card_index + 1 < len(cards) else len(nodes)
        groups.append({"card": card, "nodes": nodes[start + 1 : end]})
    return groups


def extract_card_candidates(
    xml_text: str,
    query: str,
    sort_mode: str,
    search_page: int,
    order: dict[str, Any] | None,
    line_name: str,
) -> list[dict[str, Any]]:
    title_terms = allowed_title_terms(query, order, line_name)
    candidates: list[dict[str, Any]] = []
    seen_titles: set[tuple[str, int]] = set()
    for group in product_card_groups(xml_text):
        card_bounds = group["card"].get("bounds") or []
        texts = card_texts_in_bounds(group["nodes"], card_bounds)
        title_rows = [
            row
            for row in texts
            if looks_like_card_title(row["text"], row["bounds"])
            and not row["text"].startswith(("同品", "查看剩余"))
        ]
        title_rows.sort(key=lambda row: (row["bounds"][1], row["bounds"][0]))
        title_row = None
        for row in title_rows:
            compact = normalize_text(row["text"])
            if not title_terms or any(term and term in compact for term in title_terms):
                title_row = row
                break
        if not title_row:
            continue
        title = title_row["text"]
        key = (title, int((card_bounds[1] if len(card_bounds) == 4 else title_row["bounds"][1]) / 30))
        if key in seen_titles:
            continue
        seen_titles.add(key)
        _title_cx, title_cy = bounds_center(tuple(title_row["bounds"]))
        candidate_rows = [row for row in texts if bounds_center(tuple(row["bounds"]))[1] >= title_cy - 8]
        row_values = [row["text"] for row in candidate_rows]
        sales = parse_sales(row_values)
        inferred_line = infer_line_name(title, query, order, line_name)
        if not inferred_line and order:
            continue
        offers = parse_card_offer_rows(candidate_rows)
        if offers:
            for offer in offers[:8]:
                candidates.append(
                    {
                        "line_name": inferred_line,
                        "query": query,
                        "sort_mode": sort_mode,
                        "search_page": search_page,
                        "title": title,
                        "spec": str(offer.get("spec") or ""),
                        "price": float(offer.get("price") or 0),
                        "monthly_sales": sales,
                        "available": True,
                        "source": "adb_xml_product_card_offer",
                        "bounds": offer.get("bounds") or title_row["bounds"],
                        "card_bounds": card_bounds,
                        "row_texts": row_values[:36],
                    }
                )
            continue
        spec, price = parse_card_best_offer(candidate_rows)
        if not spec and price <= 0:
            spec = parse_spec(title, row_values)
        candidates.append(
            {
                "line_name": inferred_line,
                "query": query,
                "sort_mode": sort_mode,
                "search_page": search_page,
                "title": title,
                "spec": spec,
                "price": price,
                "monthly_sales": sales,
                "available": True,
                "source": "adb_xml_product_card",
                "bounds": title_row["bounds"],
                "card_bounds": card_bounds,
                "row_texts": row_values[:36],
            }
        )
    return candidates[:30]


def find_spec_control_target(
    xml_text: str,
    query: str,
    order: dict[str, Any] | None,
    line_name: str,
    candidate_index: int,
) -> dict[str, Any]:
    title_terms = allowed_title_terms(query, order, line_name)
    matches: list[dict[str, Any]] = []
    for group in product_card_groups(xml_text):
        card_bounds = group["card"].get("bounds") or []
        texts = card_texts_in_bounds(group["nodes"], card_bounds)
        title_rows = [
            row
            for row in texts
            if looks_like_card_title(row["text"], row["bounds"])
            and not row["text"].startswith(("同品", "查看剩余"))
        ]
        title_rows.sort(key=lambda row: (row["bounds"][1], row["bounds"][0]))
        title_row = None
        for row in title_rows:
            compact = normalize_text(row["text"])
            if not title_terms or any(term and term in compact for term in title_terms):
                title_row = row
                break
        if not title_row:
            continue
        controls = [
            row
            for row in texts
            if any(word in row["text"] for word in SPEC_CONTROL_WORDS)
            and len(row.get("bounds") or []) == 4
        ]
        if not controls:
            continue
        controls.sort(key=lambda row: (row["bounds"][1], row["bounds"][0]))
        control = controls[-1]
        cx, cy = bounds_center(tuple(control["bounds"]))
        matches.append(
            {
                "title": title_row["text"],
                "title_bounds": title_row["bounds"],
                "control_text": control["text"],
                "control_bounds": control["bounds"],
                "card_bounds": card_bounds,
                "center": [cx, cy],
            }
        )
    if not matches:
        return {"status": "blocked", "message": "未找到匹配候选的规格控件。"}
    index = max(0, min(candidate_index, len(matches) - 1))
    return {"status": "ready", "index": index, "match_count": len(matches), "target": matches[index]}


def spec_modal_is_safe_to_read(xml_text: str) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    cart_details = analyze_cart_review_xml(xml_text, None)
    if cart_details.get("reached_cart"):
        reasons.append("识别到购物车/结算页")
    visible = [node_text(node) for node in parse_ui_nodes(xml_text)]
    joined = " ".join(visible)
    for word in SPEC_MODAL_BLOCK_WORDS:
        if word in joined:
            reasons.append(f"识别到高风险页面文本：{word}")
    return not reasons, reasons


def extract_spec_modal_candidates(
    xml_text: str,
    query: str,
    sort_mode: str,
    search_page: int,
    order: dict[str, Any] | None,
    line_name: str,
    parent_title: str,
    parent_bounds: list[int] | None = None,
) -> list[dict[str, Any]]:
    nodes = visible_nodes(xml_text)
    content_bounds = spec_modal_content_bounds(xml_text)
    if content_bounds is not None and content_bounds[3] - content_bounds[1] < 400:
        return []
    rows = [{"text": node_text(node), "bounds": node["bounds"]} for node in nodes]
    rows = [
        row
        for row in rows
        if row["text"]
        and len(row["bounds"]) == 4
        and row["bounds"][3] - row["bounds"][1] >= 8
        and (
            (
                content_bounds is not None
                and content_bounds[0] <= bounds_center(tuple(row["bounds"]))[0] <= content_bounds[2]
                and content_bounds[1] <= bounds_center(tuple(row["bounds"]))[1] <= content_bounds[3]
            )
            or (content_bounds is None and row["bounds"][1] >= 360)
        )
        and not re.fullmatch(r"[\ue000-\uf8ff]+", row["text"])
    ]
    global_sales = parse_sales([row_text(row) for row in rows])
    inferred_line = infer_line_name(parent_title or query, query, order, line_name)
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, float, int]] = set()
    for row in rows:
        price = numeric_price_value(row["text"])
        if price <= 0:
            continue
        _cx, cy = bounds_center(tuple(row["bounds"]))
        same_line = [candidate for candidate in rows if abs(bounds_center(tuple(candidate["bounds"]))[1] - cy) <= 48]
        near_above = [candidate for candidate in rows if 0 <= cy - bounds_center(tuple(candidate["bounds"]))[1] <= 110]
        near_below = [candidate for candidate in rows if 0 <= bounds_center(tuple(candidate["bounds"]))[1] - cy <= 80]
        price_marked = any(candidate["text"] in {"¥", "￥"} or "¥" in candidate["text"] or "￥" in candidate["text"] for candidate in same_line + near_above)
        if not price_marked:
            continue
        spec = ""
        for candidate in same_line + near_above + near_below:
            text = candidate["text"]
            if text == row["text"] or text in {"¥", "￥"}:
                continue
            if has_explicit_pack_text(text):
                spec = text
                break
        if not spec:
            continue
        key = (spec, price, int(cy / 20))
        if key in seen:
            continue
        seen.add(key)
        candidates.append(
            {
                "line_name": inferred_line,
                "query": query,
                "sort_mode": sort_mode,
                "search_page": search_page,
                "title": parent_title or query,
                "spec": spec,
                "price": price,
                "monthly_sales": global_sales,
                "available": True,
                "source": "adb_xml_spec_modal",
                "bounds": row["bounds"],
                "parent_bounds": parent_bounds or [],
                "row_texts": [item["text"] for item in same_line + near_above + near_below][:28],
            }
        )
    candidates.sort(key=lambda item: (item["price"], item["spec"]))
    return candidates[:30]


def parse_price(texts: list[str]) -> float:
    joined = " ".join(texts)
    match = re.search(r"[¥￥]\s*(\d+(?:\.\d+)?)", joined)
    if match:
        return float(match.group(1))
    for index, text in enumerate(texts[:-1]):
        if text in {"¥", "￥"} and re.fullmatch(r"\d+(?:\.\d+)?", texts[index + 1]):
            return float(texts[index + 1])
    return 0.0


def parse_sales(texts: list[str]) -> float:
    joined = " ".join(texts)
    match = re.search(r"月售\s*(\d+(?:\.\d+)?)(万)?\+?", joined)
    if not match:
        return 0.0
    value = float(match.group(1))
    return value * 10000 if match.group(2) else value


def parse_spec(title: str, texts: list[str]) -> str:
    for text in texts:
        if text == title:
            continue
        if any(word in text for word in ["¥", "￥", "月售", "买过", "同品", "低价", "选规格", "加入购物车"]):
            continue
        if re.search(r"\d", text) and any(unit in text for unit in ["斤", "kg", "g", "克", "袋", "盒", "箱", "桶", "瓶", "个"]):
            return text
    return ""


def infer_line_name(title: str, query: str, order: dict[str, Any] | None, explicit: str) -> str:
    if explicit:
        return explicit
    if not order:
        return ""
    haystack = normalize_text(f"{title} {query}")
    for item in kuailv_items(order):
        line = build_line_plan(item)
        terms = [line.get("name"), *(line.get("search_terms") or []), *(line.get("required_keywords") or [])]
        if any(normalize_text(term) and normalize_text(term) in haystack for term in terms):
            return str(line.get("name") or "")
    return ""


def allowed_title_terms(query: str, order: dict[str, Any] | None, line_name: str) -> list[str]:
    terms = [query, line_name]
    if order:
        for item in kuailv_items(order):
            line = build_line_plan(item)
            if line_name and line.get("name") != line_name:
                continue
            names = [line.get("name"), *(line.get("search_terms") or []), *(line.get("required_keywords") or [])]
            if not line_name and query:
                compact_query = normalize_text(query)
                compact_names = [normalize_text(name) for name in names if name]
                if not any(name and (name in compact_query or compact_query in name) for name in compact_names):
                    continue
            terms.extend(str(name) for name in names if name)
    return list(dict.fromkeys(normalize_text(term) for term in terms if normalize_text(term)))


def query_visible_in_search_header(xml_text: str, query: str) -> bool:
    compact_query = normalize_text(query)
    if not compact_query:
        return True
    for node in parse_ui_nodes(xml_text):
        text = normalize_text(node_text(node))
        bounds = node.get("bounds") or []
        if len(bounds) != 4 or bounds == [0, 0, 0, 0]:
            continue
        if bounds[1] > 420:
            continue
        if compact_query in text or text in compact_query:
            return True
    return False


def search_page_context(xml_text: str, query: str) -> dict[str, Any]:
    compact_query = normalize_text(query)
    header_texts: list[str] = []
    sort_hits: set[str] = set()
    blocking_reasons: list[str] = []
    promotion_top_hits: list[str] = []
    search_overlay_hits: list[str] = []

    for node in parse_ui_nodes(xml_text):
        text = node_text(node)
        display_text = str(node.get("text") or node.get("content-desc") or "").strip()
        bounds = node.get("bounds") or []
        if len(bounds) != 4 or bounds == [0, 0, 0, 0] or bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
            continue
        x1, y1, x2, y2 = bounds
        if y1 <= 280 and (
            text in {"promotion-navbar-container", "promotion-common", "输入商品名称", "分享"}
            or "promotion-navbar" in text
        ):
            promotion_top_hits.append(text)
        if y1 <= 900 and display_text in {"历史搜索", "猜你想搜"}:
            search_overlay_hits.append(display_text)
        if 80 <= y1 <= 245 and 80 <= x1 <= 930 and 160 <= x2 <= 930:
            ignored_header_terms = [
                "filter-item",
                "全部-",
                "商品分类",
                "是否带皮",
                "等级",
                "净重",
                "月售",
                "带皮",
                "新货上市",
                "袋装",
                "紫皮洋葱",
            ]
            if display_text and display_text not in {"搜索"}:
                if any(term in display_text for term in ignored_header_terms):
                    continue
                if not re.fullmatch(r"[\ue000-\uf8ff]+", display_text):
                    header_texts.append(display_text)
        if 230 <= y1 <= 760 and display_text in {"综合排序", "销量", "价格", "店铺", "筛选"}:
            sort_hits.add(display_text)

    unique_headers = list(dict.fromkeys(header_texts))
    matching_headers = [
        text for text in unique_headers if compact_query and (compact_query in normalize_text(text) or normalize_text(text) in compact_query)
    ]
    has_core_sort = {"综合排序", "销量", "价格"}.issubset(sort_hits)
    if promotion_top_hits:
        blocking_reasons.append("检测到详情/活动页顶层导航")
    if search_overlay_hits and not has_core_sort:
        blocking_reasons.append("检测到搜索输入/历史页")
    if compact_query and not matching_headers:
        blocking_reasons.append("顶部搜索区未匹配当前搜索词")
    if not has_core_sort:
        blocking_reasons.append("未识别到搜索结果排序栏")
    return {
        "blocking_reasons": blocking_reasons,
        "header_texts": unique_headers[:12],
        "matching_headers": matching_headers,
        "sort_hits": sorted(sort_hits),
        "promotion_top_hits": list(dict.fromkeys(promotion_top_hits)),
        "search_overlay_hits": list(dict.fromkeys(search_overlay_hits)),
    }


def extract_candidates(
    xml_text: str,
    query: str,
    sort_mode: str,
    search_page: int,
    order: dict[str, Any] | None,
    line_name: str,
) -> list[dict[str, Any]]:
    card_candidates = extract_card_candidates(xml_text, query, sort_mode, search_page, order, line_name)
    if card_candidates:
        return card_candidates
    nodes = visible_nodes(xml_text)
    title_terms = allowed_title_terms(query, order, line_name)
    titles = [node for node in nodes if looks_like_title(node_text(node), node["bounds"])]
    titles.sort(key=lambda item: (item["bounds"][1], item["bounds"][0]))
    candidates: list[dict[str, Any]] = []
    seen_titles: set[tuple[str, int]] = set()
    for index, title_node in enumerate(titles):
        title = node_text(title_node)
        compact_title = normalize_text(title)
        if title_terms and not any(term and term in compact_title for term in title_terms):
            continue
        y1 = max(0, int(title_node["bounds"][1]) - 80)
        next_y = int(titles[index + 1]["bounds"][1]) - 40 if index + 1 < len(titles) else int(title_node["bounds"][1]) + 360
        y2 = min(2300, max(next_y, int(title_node["bounds"][3]) + 160))
        rows = row_texts(nodes, y1, y2)
        texts = [row["text"] for row in rows]
        spec = parse_spec(title, texts)
        price = parse_price(texts)
        sales = parse_sales(texts)
        key = (title, int(title_node["bounds"][1] / 30))
        if key in seen_titles:
            continue
        seen_titles.add(key)
        inferred_line = infer_line_name(title, query, order, line_name)
        if not inferred_line and order:
            continue
        candidates.append(
            {
                "line_name": inferred_line,
                "query": query,
                "sort_mode": sort_mode,
                "search_page": search_page,
                "title": title,
                "spec": spec,
                "price": price,
                "monthly_sales": sales,
                "available": True,
                "source": "adb_xml_visible_search_page",
                "bounds": title_node["bounds"],
                "row_texts": texts[:28],
            }
        )
    return candidates[:30]


def capture_snapshot(serial: str, timeout: int) -> dict[str, Any]:
    session = datetime.now().strftime("%Y%m%d-%H%M%S")
    session_dir = OUTPUT_DIR / session
    session_dir.mkdir(parents=True, exist_ok=True)
    base = adb_base(serial)
    commands = []
    commands.append(run_command(base + ["shell", "uiautomator", "dump", "/sdcard/window_dump.xml"], timeout))
    commands.append(run_command(base + ["pull", "/sdcard/window_dump.xml", str(session_dir / "window_dump.xml")], timeout))
    commands.append(run_command(base + ["shell", "screencap", "-p", "/sdcard/kuailv_adb_ranked_candidates.png"], timeout))
    commands.append(run_command(base + ["pull", "/sdcard/kuailv_adb_ranked_candidates.png", str(session_dir / "screen.png")], timeout))
    xml_path = session_dir / "window_dump.xml"
    return {
        "session_dir": str(session_dir),
        "xml_path": str(xml_path),
        "screen_path": str(session_dir / "screen.png"),
        "commands": commands,
        "xml_text": xml_path.read_text(encoding="utf-8", errors="ignore") if xml_path.exists() else "",
    }


def sort_label_for_mode(sort_mode: str) -> str:
    if sort_mode == "sales_desc":
        return "销量"
    if sort_mode == "price_asc":
        return "价格"
    return "综合排序"


def find_sort_target(xml_text: str, sort_mode: str) -> dict[str, Any] | None:
    target_label = sort_label_for_mode(sort_mode)
    candidates = []
    for node in parse_ui_nodes(xml_text):
        text = display_text(node)
        bounds = node.get("bounds") or []
        if text != target_label or len(bounds) != 4:
            continue
        if bounds == [0, 0, 0, 0] or bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
            continue
        if not (190 <= bounds[1] <= 760):
            continue
        cx, cy = bounds_center(tuple(bounds))
        candidates.append({"text": text, "bounds": bounds, "center": [cx, cy]})
    candidates.sort(key=lambda item: (item["bounds"][1], item["bounds"][0]))
    return candidates[0] if candidates else None


def tap_sort_control(serial: str, xml_text: str, sort_mode: str, tap_count: int, timeout: int) -> dict[str, Any]:
    target = find_sort_target(xml_text, sort_mode)
    if not target:
        return {"status": "blocked", "message": f"未找到排序控件：{sort_label_for_mode(sort_mode)}"}
    base = adb_base(serial)
    commands = []
    x, y = target["center"]
    for _ in range(max(1, tap_count)):
        commands.append(run_command(base + ["shell", "input", "tap", str(x), str(y)], timeout))
        time.sleep(0.4)
    ok = all(command.get("returncode") == 0 for command in commands)
    return {"status": "tapped" if ok else "blocked", "target": target, "commands": commands}


def tap_spec_control(
    serial: str,
    xml_text: str,
    query: str,
    order: dict[str, Any] | None,
    line_name: str,
    candidate_index: int,
    timeout: int,
) -> dict[str, Any]:
    target = find_spec_control_target(xml_text, query, order, line_name, candidate_index)
    if target.get("status") != "ready":
        return target
    x, y = target["target"]["center"]
    command = run_command(adb_base(serial) + ["shell", "input", "tap", str(x), str(y)], timeout)
    status = "tapped" if command.get("returncode") == 0 else "blocked"
    return {"status": status, "target": target["target"], "match_count": target.get("match_count"), "command": command}


def close_current_overlay(serial: str, timeout: int) -> dict[str, Any]:
    command = run_command(adb_base(serial) + ["shell", "input", "keyevent", "4"], timeout)
    return {"status": "closed" if command.get("returncode") == 0 else "blocked", "command": command}


def build_spec_modal_payload(
    xml_text: str,
    query: str,
    sort_mode: str,
    search_page: int,
    order: dict[str, Any] | None,
    line_name: str,
    snapshot: dict[str, Any] | None,
    tap_result: dict[str, Any],
) -> dict[str, Any]:
    safe, reasons = spec_modal_is_safe_to_read(xml_text)
    target = tap_result.get("target") or {}
    if not safe:
        return {
            "generated_at": now_text(),
            "status": "blocked",
            "message": "规格弹窗采集被安全 guard 阻断；未加购、未提交、未付款。",
            "capture": {
                "query": query,
                "sort_mode": sort_mode,
                "search_page": search_page,
                "line_name": line_name,
                "source": "adb_xml_spec_modal",
                "snapshot_dir": (snapshot or {}).get("session_dir", ""),
                "screen": (snapshot or {}).get("screen_path", ""),
                "spec_tap": tap_result,
            },
            "summary": {"candidate_count": 0},
            "blocking_reasons": reasons,
            "items": [],
        }
    candidates = extract_spec_modal_candidates(
        xml_text,
        query,
        sort_mode,
        search_page,
        order,
        line_name,
        str(target.get("title") or ""),
        target.get("card_bounds") or [],
    )
    return {
        "generated_at": now_text(),
        "status": "ready" if candidates else "needs_review",
        "message": "已只读采集规格弹窗候选；未加购、未提交、未付款。",
        "capture": {
            "query": query,
            "sort_mode": sort_mode,
            "search_page": search_page,
            "line_name": line_name,
            "source": "adb_xml_spec_modal",
            "snapshot_dir": (snapshot or {}).get("session_dir", ""),
            "screen": (snapshot or {}).get("screen_path", ""),
            "spec_tap": tap_result,
        },
        "summary": {"candidate_count": len(candidates)},
        "items": candidates,
    }


def scroll_results(serial: str, scroll_count: int, timeout: int) -> dict[str, Any]:
    base = adb_base(serial)
    commands = []
    for _ in range(max(0, scroll_count)):
        commands.append(run_command(base + ["shell", "input", "swipe", "500", "1880", "500", "820", "700"], timeout))
        time.sleep(0.4)
    ok = all(command.get("returncode") == 0 for command in commands)
    return {"status": "scrolled" if ok else "blocked", "count": max(0, scroll_count), "commands": commands}


def build_payload(
    xml_text: str,
    query: str,
    sort_mode: str,
    search_page: int,
    order: dict[str, Any] | None,
    line_name: str,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cart_details = analyze_cart_review_xml(xml_text, None)
    if cart_details.get("reached_cart"):
        return {
            "generated_at": now_text(),
            "status": "blocked",
            "message": "当前识别为购物车页/结算检查页，拒绝抽取搜索候选；请先回到搜索结果页并切换排序。",
            "capture": {
                "query": query,
                "sort_mode": sort_mode,
                "search_page": search_page,
                "line_name": line_name,
                "source": "adb_xml",
                "snapshot_dir": (snapshot or {}).get("session_dir", ""),
                "screen": (snapshot or {}).get("screen_path", ""),
                "sort_tap": (snapshot or {}).get("sort_tap"),
                "scroll": (snapshot or {}).get("scroll"),
            },
            "summary": {"candidate_count": 0},
            "cart_review_details": {
                "keyword_hits": cart_details.get("keyword_hits"),
                "marker_hits": cart_details.get("marker_hits"),
                "visible_cart_items": cart_details.get("visible_cart_items"),
            },
            "items": [],
        }
    nodes = parse_ui_nodes(xml_text)
    if is_product_detail_page(nodes, detect_page_text(xml_text)):
        return {
            "generated_at": now_text(),
            "status": "blocked",
            "message": "当前识别为商品详情页，拒绝抽取搜索候选；请先返回搜索结果页并切换排序。",
            "capture": {
                "query": query,
                "sort_mode": sort_mode,
                "search_page": search_page,
                "line_name": line_name,
                "source": "adb_xml",
                "snapshot_dir": (snapshot or {}).get("session_dir", ""),
                "screen": (snapshot or {}).get("screen_path", ""),
                "sort_tap": (snapshot or {}).get("sort_tap"),
                "scroll": (snapshot or {}).get("scroll"),
            },
            "summary": {"candidate_count": 0},
            "items": [],
        }
    page_context = search_page_context(xml_text, query)
    if page_context["blocking_reasons"]:
        return {
            "generated_at": now_text(),
            "status": "blocked",
            "message": "当前页面不像单一搜索结果页，拒绝抽取候选；请先回到搜索结果页并切换排序。",
            "capture": {
                "query": query,
                "sort_mode": sort_mode,
                "search_page": search_page,
                "line_name": line_name,
                "source": "adb_xml",
                "snapshot_dir": (snapshot or {}).get("session_dir", ""),
                "screen": (snapshot or {}).get("screen_path", ""),
                "sort_tap": (snapshot or {}).get("sort_tap"),
                "scroll": (snapshot or {}).get("scroll"),
            },
            "summary": {"candidate_count": 0},
            "page_context": page_context,
            "items": [],
        }
    if not query_visible_in_search_header(xml_text, query):
        return {
            "generated_at": now_text(),
            "status": "blocked",
            "message": "顶部搜索区未识别到当前搜索词，拒绝抽取候选；请确认已进入该关键词的搜索结果页。",
            "capture": {
                "query": query,
                "sort_mode": sort_mode,
                "search_page": search_page,
                "line_name": line_name,
                "source": "adb_xml",
                "snapshot_dir": (snapshot or {}).get("session_dir", ""),
                "screen": (snapshot or {}).get("screen_path", ""),
                "sort_tap": (snapshot or {}).get("sort_tap"),
                "scroll": (snapshot or {}).get("scroll"),
            },
            "summary": {"candidate_count": 0},
            "items": [],
        }
    candidates = extract_candidates(xml_text, query, sort_mode, search_page, order, line_name)
    return {
        "generated_at": now_text(),
        "status": "ready" if candidates else "needs_review",
        "message": "已从当前安卓 XML 抽取可见快驴候选；未点击、未加购、未提交、未付款。",
        "capture": {
            "query": query,
            "sort_mode": sort_mode,
            "search_page": search_page,
            "line_name": line_name,
            "source": "adb_xml",
            "snapshot_dir": (snapshot or {}).get("session_dir", ""),
            "screen": (snapshot or {}).get("screen_path", ""),
            "sort_tap": (snapshot or {}).get("sort_tap"),
            "scroll": (snapshot or {}).get("scroll"),
        },
        "summary": {
            "candidate_count": len(candidates),
        },
        "items": candidates,
    }


def write_latest(payload: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LATEST_PATH.chmod(0o644)


def print_summary(payload: dict[str, Any]) -> None:
    print(payload["message"])
    print(f"状态：{payload['status']} / {payload['summary']}")
    for item in payload.get("items") or []:
        print(f"- {item.get('line_name') or '-'}: {item.get('title')} {item.get('spec') or ''} ¥{item.get('price')} 月售{item.get('monthly_sales')}")
    print(f"结果文件：{LATEST_PATH}")


def main() -> int:
    parser = argparse.ArgumentParser(description="从当前快驴安卓搜索结果页 XML 抽取排序候选；只读，不点击。")
    parser.add_argument("--server", default=DEFAULT_SERVER)
    parser.add_argument("--token", default=DEFAULT_TOKEN)
    parser.add_argument("--date", default=datetime.now().astimezone().strftime("%Y-%m-%d"))
    parser.add_argument("--order-id", default="")
    parser.add_argument("--line-name", default="")
    parser.add_argument("--query", required=True)
    parser.add_argument("--sort-mode", required=True, choices=["price_asc", "sales_desc", "default"])
    parser.add_argument("--search-page", type=int, default=1)
    parser.add_argument("--xml-file", default="", help="离线 XML 文件；为空时从 ADB 现场采集")
    parser.add_argument("--adb-serial", default=os.environ.get("ANDROID_ADB_SERIAL", ""))
    parser.add_argument("--timeout", type=int, default=25)
    parser.add_argument("--tap-sort", action="store_true", help="采集前先点击当前页排序栏；只点排序，不加购")
    parser.add_argument("--sort-wait", type=float, default=2.0, help="点击排序后等待刷新秒数")
    parser.add_argument("--sort-tap-count", type=int, default=1, help="排序控件点击次数，用于价格升降序切换")
    parser.add_argument("--scroll-count", type=int, default=0, help="采集前向下滚动结果列表次数；只滚动，不加购")
    parser.add_argument("--scroll-wait", type=float, default=1.0, help="滚动后等待刷新秒数")
    parser.add_argument("--tap-spec-modal", action="store_true", help="采集后点开一个候选的规格弹窗并只读抽取规格/价格")
    parser.add_argument("--spec-candidate-index", type=int, default=0, help="点开第 N 个匹配候选的规格控件，从 0 开始")
    parser.add_argument("--spec-wait", type=float, default=1.0, help="点开规格弹窗后等待秒数")
    parser.add_argument("--leave-spec-modal", action="store_true", help="调试用：采集后不按返回关闭规格弹窗")
    args = parser.parse_args()

    try:
        order = load_order(args.server, args.token, args.date, args.order_id, args.timeout) if args.order_id or args.date else None
        snapshot = None
        if args.xml_file:
            xml_text = Path(args.xml_file).read_text(encoding="utf-8", errors="ignore")
        else:
            snapshot = capture_snapshot(args.adb_serial.strip(), args.timeout)
            if args.tap_sort:
                sort_tap = tap_sort_control(args.adb_serial.strip(), snapshot.get("xml_text") or "", args.sort_mode, args.sort_tap_count, args.timeout)
                snapshot["sort_tap"] = sort_tap
                if sort_tap.get("status") != "tapped":
                    raise RuntimeError(sort_tap.get("message") or "排序点击失败。")
                time.sleep(max(0.0, args.sort_wait))
                snapshot = capture_snapshot(args.adb_serial.strip(), args.timeout) | {"sort_tap": sort_tap}
            if args.scroll_count > 0:
                scroll_result = scroll_results(args.adb_serial.strip(), args.scroll_count, args.timeout)
                snapshot["scroll"] = scroll_result
                if scroll_result.get("status") != "scrolled":
                    raise RuntimeError("列表滚动失败。")
                time.sleep(max(0.0, args.scroll_wait))
                snapshot = capture_snapshot(args.adb_serial.strip(), args.timeout) | {
                    "sort_tap": snapshot.get("sort_tap"),
                    "scroll": scroll_result,
                }
            xml_text = snapshot.get("xml_text") or ""
        payload = build_payload(xml_text, args.query.strip(), args.sort_mode, max(1, args.search_page), order, args.line_name.strip(), snapshot)
        if args.tap_spec_modal:
            if args.xml_file:
                raise RuntimeError("离线 XML 模式不能点击规格弹窗。")
            spec_tap = tap_spec_control(
                args.adb_serial.strip(),
                xml_text,
                args.query.strip(),
                order,
                args.line_name.strip(),
                max(0, args.spec_candidate_index),
                args.timeout,
            )
            payload["spec_modal_tap"] = spec_tap
            if spec_tap.get("status") != "tapped":
                payload["status"] = "needs_review"
                payload["message"] = f"{payload['message']} 规格弹窗未打开：{spec_tap.get('message') or spec_tap.get('status')}"
            else:
                time.sleep(max(0.0, args.spec_wait))
                spec_snapshot = capture_snapshot(args.adb_serial.strip(), args.timeout)
                spec_payload = build_spec_modal_payload(
                    spec_snapshot.get("xml_text") or "",
                    args.query.strip(),
                    args.sort_mode,
                    max(1, args.search_page),
                    order,
                    args.line_name.strip(),
                    spec_snapshot,
                    spec_tap,
                )
                payload["spec_modal_capture"] = spec_payload
                payload["items"].extend(spec_payload.get("items") or [])
                payload["summary"]["candidate_count"] = len(payload["items"])
                if spec_payload.get("status") == "blocked":
                    payload["status"] = "blocked"
                    payload["message"] = spec_payload.get("message") or payload["message"]
                elif spec_payload.get("items"):
                    payload["status"] = "ready"
                    payload["message"] = "已从当前搜索结果页和规格弹窗抽取候选；未加购、未提交、未付款。"
                else:
                    inline_payload = build_payload(
                        spec_snapshot.get("xml_text") or "",
                        args.query.strip(),
                        args.sort_mode,
                        max(1, args.search_page),
                        order,
                        args.line_name.strip(),
                        spec_snapshot,
                    )
                    inline_items = [
                        item
                        for item in inline_payload.get("items") or []
                        if item.get("source") == "adb_xml_product_card_offer" and item.get("spec")
                    ]
                    payload["spec_inline_capture"] = {
                        "status": inline_payload.get("status"),
                        "summary": {"candidate_count": len(inline_items)},
                        "items": inline_items,
                    }
                    payload["items"].extend(inline_items)
                    payload["summary"]["candidate_count"] = len(payload["items"])
                    if inline_items:
                        payload["status"] = "ready"
                        payload["message"] = "已从展开的商品卡片抽取规格候选；未加购、未提交、未付款。"
                    else:
                        payload["status"] = "needs_review"
                        payload["message"] = "已抽取搜索页候选，但规格弹窗/展开卡片没有可安全读取的规格候选；未加购、未提交、未付款。"
                if not args.leave_spec_modal:
                    payload["spec_modal_close"] = close_current_overlay(args.adb_serial.strip(), args.timeout)
        write_latest(payload)
        print_summary(payload)
        return 0 if payload["status"] in {"ready", "needs_review"} else 1
    except Exception as exc:
        payload = {
            "generated_at": now_text(),
            "status": "failed",
            "message": f"快驴安卓候选抽取失败：{exc}",
        }
        write_latest(payload)
        print(payload["message"])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
