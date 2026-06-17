from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from kuailv_order_dry_run import CHANNEL, DEFAULT_SERVER, DEFAULT_TOKEN, build_line_plan, eligible_orders
from kuailv_purchase_decision import DEFAULT_MAX_SEARCH_PAGE, DEFAULT_SORT_MODES, build_payload as build_decision_payload


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "kuailv_ranked_candidates"
LATEST_PATH = OUTPUT_DIR / "latest.json"


FIELD_ALIASES = {
    "title": ["title", "name", "goods_name", "product_name", "spu_name"],
    "spec": ["spec", "sku_spec", "pack_label", "standard", "规格"],
    "price": ["price", "sale_price", "final_price", "activity_price", "current_price"],
    "monthly_sales": ["monthly_sales", "month_sales", "sales", "sold_count", "sale_count"],
    "sku_id": ["sku_id", "sku", "skuId", "skuID"],
    "spu_id": ["spu_id", "spu", "spuId", "spuID"],
    "stock": ["stock", "stock_count", "inventory"],
    "available": ["available", "saleable", "in_stock"],
    "sort_mode": ["sort_mode", "ranking", "ranking_mode"],
    "search_page": ["search_page", "page", "page_no", "pageNo"],
    "query": ["query", "search_query", "keyword"],
    "line_name": ["line_name", "item_name", "target_name"],
}


def now_text() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S%z")


def read_json_url(url: str, timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "kuailv-ranked-candidate-collector/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def admin_summary_url(server: str, token: str) -> str:
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


def first_value(row: dict[str, Any], field: str, default: Any = "") -> Any:
    for key in FIELD_ALIASES.get(field, [field]):
        if key in row and row.get(key) not in (None, ""):
            return row.get(key)
    return default


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return default


def parse_sales(value: Any, text: str = "") -> float:
    explicit = safe_float(value, -1)
    if explicit >= 0:
        return explicit
    match = re.search(r"月售\s*(\d+(?:\.\d+)?)(万)?\+?", text)
    if match:
        amount = safe_float(match.group(1))
        return amount * 10000 if match.group(2) else amount
    return 0.0


def sort_modes_from_text(text: str) -> list[str]:
    return [item.strip() for item in text.split(",") if item.strip()]


def build_collection_jobs(order: dict[str, Any], max_search_page: int, sort_modes: list[str]) -> list[dict[str, Any]]:
    jobs = []
    for item in kuailv_items(order):
        line = build_line_plan(item)
        for query in line.get("search_terms") or [line.get("name")]:
            if not query:
                continue
            jobs.append(
                {
                    "line_name": line.get("name"),
                    "sku": line.get("sku"),
                    "query": query,
                    "sort_modes": sort_modes,
                    "pages": list(range(1, max_search_page + 1)),
                    "required_keywords": line.get("required_keywords") or [],
                    "excluded_keywords": line.get("excluded_keywords") or [],
                    "preferred_spec_keywords": line.get("preferred_spec_keywords") or [],
                    "pack_strategy": line.get("pack_strategy") or [],
                    "capture_policy": "先搜索，再切换价格升序/销量降序排序；每种排序只采集前 N 页候选。",
                }
            )
    return jobs


def flatten_raw_candidates(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ["items", "candidates", "rows", "products", "goods"]:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    flattened: list[dict[str, Any]] = []
    for value in payload.values():
        if isinstance(value, list):
            flattened.extend(item for item in value if isinstance(item, dict))
    return flattened


def normalize_candidate(row: dict[str, Any], fallback_line_name: str = "") -> dict[str, Any]:
    title = str(first_value(row, "title"))
    spec = str(first_value(row, "spec"))
    text = " ".join(str(row.get(key) or "") for key in ["title", "name", "goods_name", "product_name", "spec", "subtitle", "description", "sales_text"])
    sort_mode = str(first_value(row, "sort_mode", "")).strip()
    search_page = int(max(1, safe_float(first_value(row, "search_page", 1), 1)))
    normalized = {
        "sku_id": str(first_value(row, "sku_id", "")),
        "spu_id": str(first_value(row, "spu_id", "")),
        "title": title,
        "spec": spec,
        "price": safe_float(first_value(row, "price", 0), 0),
        "monthly_sales": parse_sales(first_value(row, "monthly_sales", -1), text),
        "stock": first_value(row, "stock", ""),
        "available": bool(first_value(row, "available", True)),
        "sort_mode": sort_mode,
        "search_page": search_page,
        "query": str(first_value(row, "query", "")),
        "source": row.get("source", "ranked_candidate_collector"),
    }
    line_name = str(first_value(row, "line_name", fallback_line_name))
    if line_name:
        normalized["line_name"] = line_name
    return normalized


def infer_line_name(candidate: dict[str, Any], lines: list[dict[str, Any]]) -> str:
    explicit = str(candidate.get("line_name") or "")
    if explicit:
        return explicit
    text = normalize_text(" ".join(str(candidate.get(key) or "") for key in ["title", "spec", "query"]))
    for line in lines:
        terms = [line.get("name"), *(line.get("search_terms") or []), *(line.get("required_keywords") or [])]
        if any(normalize_text(term) and normalize_text(term) in text for term in terms):
            return str(line.get("name") or "")
    return ""


def normalize_candidates(raw_payload: Any, order: dict[str, Any], max_search_page: int, sort_modes: list[str]) -> dict[str, list[dict[str, Any]]]:
    lines = [build_line_plan(item) for item in kuailv_items(order)]
    allowed_modes = {normalize_text(mode) for mode in sort_modes}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for raw in flatten_raw_candidates(raw_payload):
        candidate = normalize_candidate(raw)
        line_name = infer_line_name(candidate, lines)
        if not line_name:
            continue
        candidate["line_name"] = line_name
        if normalize_text(candidate.get("sort_mode")) not in allowed_modes:
            candidate["collector_warning"] = "sort_mode_not_requested"
        if int(candidate.get("search_page") or 1) > max_search_page:
            candidate["collector_warning"] = "page_outside_collection_window"
        grouped.setdefault(line_name, []).append(candidate)
    for values in grouped.values():
        values.sort(key=lambda item: (str(item.get("sort_mode") or ""), int(item.get("search_page") or 1), safe_float(item.get("price"), 999999)))
    return grouped


def build_payload(order: dict[str, Any], raw_candidates: Any, max_search_page: int, sort_modes: list[str], include_decision: bool) -> dict[str, Any]:
    normalized = normalize_candidates(raw_candidates, order, max_search_page, sort_modes) if raw_candidates is not None else {}
    jobs = build_collection_jobs(order, max_search_page, sort_modes)
    payload: dict[str, Any] = {
        "generated_at": now_text(),
        "status": "ready" if normalized else "needs_collection",
        "order": {
            "order_id": order.get("order_id"),
            "store_name": order.get("store_name"),
            "submitted_at": order.get("submitted_at"),
            "channel": CHANNEL,
        },
        "collection_policy": {
            "sort_modes": sort_modes,
            "max_search_page": max_search_page,
            "supplier_reuse_allowed": False,
            "description": "每天实时搜索；按价格升序和销量降序等指定排序分别采集前 N 页候选。",
        },
        "summary": {
            "job_count": len(jobs),
            "line_count": len({job["line_name"] for job in jobs}),
            "normalized_candidate_count": sum(len(items) for items in normalized.values()),
        },
        "collection_jobs": jobs,
        "candidates": normalized,
        "message": "快驴排序候选采集计划已生成；未执行加购、提交或付款。",
    }
    if include_decision and normalized:
        payload["decision"] = build_decision_payload(order, normalized, max_search_page=max_search_page, sort_modes=sort_modes)
    return payload


def read_raw_candidates(path_text: str) -> Any:
    if not path_text:
        return None
    return json.loads(Path(path_text).read_text(encoding="utf-8"))


def write_latest(payload: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LATEST_PATH.chmod(0o644)


def print_summary(payload: dict[str, Any]) -> None:
    print(payload["message"])
    print(f"订单：{payload['order'].get('order_id')} / {payload['order'].get('store_name')}")
    print(f"状态：{payload['status']} / {payload['summary']}")
    for job in payload["collection_jobs"][:12]:
        print(f"- {job['line_name']}: 搜索 {job['query']}，排序 {', '.join(job['sort_modes'])}，页码 {job['pages']}")
    if payload.get("decision"):
        print(f"决策状态：{payload['decision'].get('status')} / {payload['decision'].get('summary')}")
    print(f"结果文件：{LATEST_PATH}")


def main() -> int:
    parser = argparse.ArgumentParser(description="快驴排序候选采集计划/规范化工具。")
    parser.add_argument("--server", default=DEFAULT_SERVER)
    parser.add_argument("--token", default=DEFAULT_TOKEN)
    parser.add_argument("--date", default=datetime.now().astimezone().strftime("%Y-%m-%d"))
    parser.add_argument("--order-id", default="")
    parser.add_argument("--raw-candidates", default="", help="接口/页面采集到的原始候选 JSON；为空时只生成采集计划")
    parser.add_argument("--max-search-page", type=int, default=DEFAULT_MAX_SEARCH_PAGE)
    parser.add_argument("--sort-modes", default=",".join(DEFAULT_SORT_MODES))
    parser.add_argument("--with-decision", action="store_true", help="有候选时同时运行采购决策")
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()

    try:
        order = load_order(args.server, args.token, args.date, args.order_id, args.timeout)
        sort_modes = sort_modes_from_text(args.sort_modes) or DEFAULT_SORT_MODES
        payload = build_payload(order, read_raw_candidates(args.raw_candidates), max(1, args.max_search_page), sort_modes, args.with_decision)
        write_latest(payload)
        print_summary(payload)
        return 0
    except Exception as exc:
        payload = {
            "generated_at": now_text(),
            "status": "failed",
            "message": f"快驴排序候选采集计划生成失败：{exc}",
        }
        write_latest(payload)
        print(payload["message"], file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
