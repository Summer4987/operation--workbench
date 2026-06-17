from __future__ import annotations

import argparse
import json
import math
import re
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from kuailv_order_dry_run import CHANNEL, DEFAULT_SERVER, DEFAULT_TOKEN, PACK_RULES, build_line_plan, eligible_orders


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "kuailv_purchase_decision"
LATEST_PATH = OUTPUT_DIR / "latest.json"
DEFAULT_MAX_SEARCH_PAGE = 2
DEFAULT_SORT_MODES = ["price_asc", "sales_desc"]
MAX_COMBINATION_OPTIONS = 6
MAX_COMBINATION_STATES = 5000
MAX_AUTO_CLICK_COUNT = 12
GLOBAL_REJECT_KEYWORDS = ["食堂菜"]


UNIT_ALIASES = {
    "斤": ["斤", "500g", "0.5kg"],
    "盒": ["盒"],
    "袋": ["袋"],
    "份": ["份"],
}


def now_text() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S%z")


def read_json_url(url: str, timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "kuailv-purchase-decision/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def admin_summary_url(server: str, token: str) -> str:
    query = urllib.parse.urlencode({"status": "all", "token": token})
    return f"{server.rstrip('/')}/daily-order/api/admin/summary?{query}"


def order_day(order: dict[str, Any]) -> str:
    return str(order.get("submitted_at") or "")[:10]


def kuailv_items(order: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in order.get("items") or [] if str(item.get("purchase_channel") or "") == CHANNEL]


def load_order(server: str, token: str, date_text: str, order_id: str, timeout: int) -> dict[str, Any]:
    payload = read_json_url(admin_summary_url(server, token), timeout)
    candidates = eligible_orders(payload, date_text, order_id)
    if not candidates:
        suffix = f"订单 {order_id}" if order_id else f"{date_text} 的快驴订单"
        raise RuntimeError(f"没有找到{suffix}。")
    return candidates[0]


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return default


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def item_identity_text(item: dict[str, Any]) -> str:
    return normalize_text(" ".join(str(item.get(key) or "") for key in ["title", "name", "spec", "subtitle", "description"]))


def pack_label_to_quantity(label: str, unit: str) -> float | None:
    text = normalize_text(label)
    if not text:
        return None
    if unit == "斤":
        match = re.search(r"(\d+(?:\.\d+)?)\s*斤", text)
        if match:
            return safe_float(match.group(1))
        match = re.search(r"(\d+(?:\.\d+)?)\s*kg", text)
        if match:
            return safe_float(match.group(1)) * 2
        match = re.search(r"(\d+(?:\.\d+)?)\s*g", text)
        if match:
            return safe_float(match.group(1)) / 500
    match = re.search(r"(\d+(?:\.\d+)?)\s*" + re.escape(unit), text)
    if match:
        return safe_float(match.group(1))
    return None


def candidate_pack_quantity(candidate: dict[str, Any], unit: str) -> float:
    explicit = safe_float(candidate.get("pack_quantity"), 0)
    if explicit > 0:
        return explicit
    for key in ["spec", "pack_label", "title", "name"]:
        parsed = pack_label_to_quantity(str(candidate.get(key) or ""), unit)
        if parsed and parsed > 0:
            return parsed
    if unit == "斤":
        return 0.0
    return 1.0


def candidate_unit_price(candidate: dict[str, Any], unit: str, pack_quantity: float) -> float:
    explicit = safe_float(candidate.get("unit_price"), 0)
    if explicit > 0:
        return explicit
    price = safe_float(candidate.get("price") or candidate.get("sale_price") or candidate.get("final_price"), 0)
    if price <= 0:
        return 999999.0
    if pack_quantity <= 0:
        return price
    return price / pack_quantity


@dataclass
class CandidateScore:
    candidate: dict[str, Any]
    allowed: bool
    score: float
    pack_quantity: float
    unit_price: float
    sales: float
    page: int
    sort_mode: str
    value_score: float
    reasons: list[str]
    risk_flags: list[str]


def candidate_search_page(candidate: dict[str, Any]) -> int:
    page = int(safe_float(candidate.get("search_page") or candidate.get("page"), 1))
    return max(1, page)


def candidate_sort_mode(candidate: dict[str, Any]) -> str:
    return normalize_text(candidate.get("sort_mode") or candidate.get("ranking") or candidate.get("ranking_mode") or "")


def allowed_sort_modes(line: dict[str, Any]) -> list[str]:
    modes = line.get("allowed_sort_modes")
    if isinstance(modes, str):
        modes = [item.strip() for item in modes.split(",")]
    if not modes:
        modes = DEFAULT_SORT_MODES
    return [normalize_text(mode) for mode in modes if normalize_text(mode)]


def candidate_sales(candidate: dict[str, Any]) -> float:
    for key in ["monthly_sales", "month_sales", "sales", "sold_count", "sale_count"]:
        value = safe_float(candidate.get(key), -1)
        if value >= 0:
            return value
    text = item_identity_text(candidate)
    match = re.search(r"月售(\d+(?:\.\d+)?)(万)?\+?", text)
    if match:
        value = safe_float(match.group(1))
        return value * 10000 if match.group(2) else value
    return 0.0


def candidate_value_score(unit_price: float, sales: float) -> float:
    if unit_price >= 999999:
        return -999999.0
    return math.log1p(max(sales, 0)) * 2.5 - unit_price * 4


def score_candidate(candidate: dict[str, Any], line: dict[str, Any]) -> CandidateScore:
    text = item_identity_text(candidate)
    requested_unit = str(line.get("unit") or "")
    required = [normalize_text(word) for word in line.get("required_keywords") or [] if word]
    preferred = [normalize_text(word) for word in line.get("preferred_spec_keywords") or [] if word]
    excluded = [normalize_text(word) for word in [*(line.get("excluded_keywords") or []), *GLOBAL_REJECT_KEYWORDS] if word]
    pack_labels = [normalize_text(item.get("label")) for item in line.get("pack_strategy") or [] if item.get("label")]

    required_hits = [word for word in required if word and word in text]
    preferred_hits = [word for word in preferred if word and word in text]
    excluded_hits = [word for word in excluded if word and word in text]
    pack_hits = [word for word in pack_labels if word and word.replace("x", "")[:2] in text]

    pack_quantity = candidate_pack_quantity(candidate, requested_unit)
    unit_price = candidate_unit_price(candidate, requested_unit, pack_quantity)
    page = candidate_search_page(candidate)
    sort_mode = candidate_sort_mode(candidate)
    sales = candidate_sales(candidate)
    value_score = candidate_value_score(unit_price, sales)
    stock = safe_float(candidate.get("stock"), math.inf)
    min_order = safe_float(candidate.get("min_order") or candidate.get("min_count"), 1)
    is_available = bool(candidate.get("available", True)) and stock != 0

    reasons: list[str] = []
    risk_flags: list[str] = []
    allowed = True
    score = value_score

    max_page = int(safe_float(line.get("max_search_page"), DEFAULT_MAX_SEARCH_PAGE))
    allowed_modes = allowed_sort_modes(line)
    if page > max_page:
        allowed = False
        risk_flags.append("outside_ranked_first_pages")
        reasons.append(f"不在排序后前 {max_page} 页：第 {page} 页")
    if sort_mode not in allowed_modes:
        allowed = False
        risk_flags.append("unsupported_sort_mode")
        reasons.append(f"不是允许的排序来源：{sort_mode or '未标注'}")

    if pack_quantity <= 0:
        allowed = False
        risk_flags.append("missing_pack_quantity")
        reasons.append("缺少明确包装规格，不能自动组合数量")

    if required_hits:
        score += 70 + 12 * len(required_hits)
        reasons.append(f"命中品类词：{', '.join(required_hits)}")
    else:
        allowed = False
        risk_flags.append("missing_required_keyword")
        reasons.append("未命中必需品类词")

    if excluded_hits:
        allowed = False
        score -= 180
        risk_flags.append("excluded_keyword_seen")
        reasons.append(f"命中排除词：{', '.join(excluded_hits)}")

    global_reject_hits = [word for word in [normalize_text(item) for item in GLOBAL_REJECT_KEYWORDS] if word and word in text]
    if global_reject_hits:
        allowed = False
        score -= 240
        risk_flags.append("canteen_dish_keyword_seen")
        reasons.append("命中全局禁用词：食堂菜")

    if preferred_hits:
        score += 8 * len(preferred_hits)
        reasons.append(f"命中偏好词：{', '.join(preferred_hits)}")

    if pack_hits:
        score += 10
        reasons.append("规格命中计划拆分")

    if not is_available:
        allowed = False
        score -= 150
        risk_flags.append("unavailable_or_no_stock")
        reasons.append("不可售或库存为 0")

    if min_order > 1:
        score -= min_order * 2
        reasons.append(f"起订量 {min_order:g}")

    if candidate.get("bought_before") or candidate.get("purchased_before") or "买过" in text:
        reasons.append("历史买过，仅作参考，不作为复用依据")
    if candidate.get("self_operated") or "自营" in text:
        score += 5
        reasons.append("自营")

    if unit_price < 999999:
        reasons.append(f"折算单价 {unit_price:.2f}/{requested_unit or '单位'}")
    else:
        allowed = False
        risk_flags.append("missing_price")
        reasons.append("缺少价格，需人工复核")

    reasons.append(f"排序 {sort_mode or '未标注'} 第 {page} 页，销量 {sales:g}，性价比分 {value_score:.2f}")

    return CandidateScore(candidate, allowed, round(score, 3), pack_quantity, round(unit_price, 4), round(sales, 2), page, sort_mode, round(value_score, 3), reasons, risk_flags)


def candidate_id(candidate: dict[str, Any]) -> str:
    for key in ["sku_id", "sku", "spu_id", "id", "item_id"]:
        value = candidate.get(key)
        if value:
            return str(value)
    return normalize_text(candidate.get("title") or candidate.get("name") or "")


def choose_combination(scores: list[CandidateScore], line: dict[str, Any]) -> dict[str, Any]:
    allowed = [score for score in scores if score.allowed and score.pack_quantity > 0]
    requested = safe_float(line.get("requested_quantity"), 0)
    unit = str(line.get("unit") or "")
    allowed_overage = safe_float(line.get("allowed_overage"), 0)
    if not allowed:
        return {
            "status": "blocked",
            "message": "没有安全候选，不能加购。",
            "selection": [],
            "risk_flags": ["no_safe_candidate"],
        }

    max_overage = allowed_overage
    if max_overage <= 0:
        max_overage = 0.0001
    best: tuple[float, float, float, list[dict[str, Any]]] | None = None
    top_allowed = sorted(allowed, key=lambda item: (-item.value_score, item.unit_price, -item.sales))[:MAX_COMBINATION_OPTIONS]
    visited_states = 0

    def search(index: int, current: list[dict[str, Any]]) -> None:
        nonlocal best, visited_states
        visited_states += 1
        if visited_states > MAX_COMBINATION_STATES:
            return
        total_qty = sum(row["pack_quantity"] * row["count"] for row in current)
        click_count = sum(row["count"] for row in current)
        if click_count > MAX_AUTO_CLICK_COUNT:
            return
        if total_qty >= requested:
            overage = total_qty - requested
            if overage <= max_overage:
                total_cost = sum(row["unit_price"] * row["pack_quantity"] * row["count"] for row in current)
                avg_value_score = sum(row["value_score"] * row["count"] for row in current) / max(click_count, 1)
                score_tuple = (round(overage, 4), -round(avg_value_score, 4), round(total_cost, 4))
                if best is None or score_tuple < best[:3]:
                    best = (score_tuple[0], score_tuple[1], score_tuple[2], [dict(row) for row in current])
            return
        if index >= len(top_allowed):
            return
        option = top_allowed[index]
        max_count = max(0, int(math.ceil((requested + max_overage) / option.pack_quantity)) + 1)
        max_count = min(max_count, MAX_AUTO_CLICK_COUNT - click_count)
        for count in range(max_count + 1):
            next_current = [dict(row) for row in current]
            if count:
                next_current.append(
                    {
                        "candidate_id": candidate_id(option.candidate),
                        "title": option.candidate.get("title") or option.candidate.get("name"),
                        "spec": option.candidate.get("spec") or option.candidate.get("pack_label"),
                        "count": count,
                        "pack_quantity": option.pack_quantity,
                        "unit_price": option.unit_price,
                        "score": option.score,
                        "sales": option.sales,
                        "search_page": option.page,
                        "sort_mode": option.sort_mode,
                        "value_score": option.value_score,
                    }
                )
            search(index + 1, next_current)

    search(0, [])
    if best is None:
        cheapest = min(top_allowed, key=lambda item: item.unit_price)
        count = max(1, int(math.ceil(requested / cheapest.pack_quantity)))
        if count > MAX_AUTO_CLICK_COUNT:
            return {
                "status": "needs_review",
                "message": f"最低价候选需要点击 {count} 次，超过自动组合上限 {MAX_AUTO_CLICK_COUNT} 次；需继续寻找大规格或人工确认。",
                "selection": [],
                "planned_quantity": 0,
                "overage": 0 - requested,
                "risk_flags": ["excessive_click_count", "missing_large_pack_candidate"],
            }
        selection = [
            {
                "candidate_id": candidate_id(cheapest.candidate),
                "title": cheapest.candidate.get("title") or cheapest.candidate.get("name"),
                "spec": cheapest.candidate.get("spec") or cheapest.candidate.get("pack_label"),
                "count": count,
                "pack_quantity": cheapest.pack_quantity,
                "unit_price": cheapest.unit_price,
                "score": cheapest.score,
                "sales": cheapest.sales,
                "search_page": cheapest.page,
                "sort_mode": cheapest.sort_mode,
                "value_score": cheapest.value_score,
            }
        ]
        planned = sum(row["pack_quantity"] * row["count"] for row in selection)
        return {
            "status": "needs_review",
            "message": f"没有满足超量规则的组合；最低价候选会采购 {planned:g}{unit}，需人工确认。",
            "selection": selection,
            "planned_quantity": planned,
            "overage": planned - requested,
            "risk_flags": ["overage_out_of_policy"],
        }

    selection = best[3]
    planned = sum(row["pack_quantity"] * row["count"] for row in selection)
    return {
        "status": "ready",
        "message": f"已选择 {planned:g}{unit}，超量 {planned - requested:g}{unit}。",
        "selection": selection,
        "planned_quantity": planned,
        "overage": planned - requested,
        "estimated_cost": round(best[2], 2),
        "risk_flags": [],
    }


def candidates_for_line(candidates: dict[str, Any], line: dict[str, Any]) -> list[dict[str, Any]]:
    name = str(line.get("name") or "")
    sku = str(line.get("sku") or "")
    if isinstance(candidates.get(name), list):
        return candidates[name]
    if sku and isinstance(candidates.get(sku), list):
        return candidates[sku]
    items = candidates.get("items")
    if isinstance(items, list):
        terms = [normalize_text(name), *(normalize_text(term) for term in line.get("search_terms") or [])]
        return [item for item in items if any(term and term in item_identity_text(item) for term in terms)]
    return []


def decision_for_line(line: dict[str, Any], raw_candidates: list[dict[str, Any]], max_search_page: int, sort_modes: list[str]) -> dict[str, Any]:
    line = dict(line)
    line["max_search_page"] = max_search_page
    line["allowed_sort_modes"] = sort_modes
    if line.get("action") != "search_and_add":
        return {
            "name": line.get("name"),
            "sku": line.get("sku"),
            "status": "manual_note_only",
            "message": line.get("note") or "该品项不执行快驴自动采集/加购。",
            "selection": [],
            "risk_flags": [],
            "candidate_count": 0,
            "safe_candidate_count": 0,
            "top_candidates": [],
        }
    if not raw_candidates:
        return {
            "name": line.get("name"),
            "status": "needs_candidates",
            "message": "缺少实时候选，需要先搜索/抓接口采集。",
            "search_terms": line.get("search_terms") or [],
            "required_keywords": line.get("required_keywords") or [],
            "excluded_keywords": line.get("excluded_keywords") or [],
            "pack_strategy": line.get("pack_strategy") or [],
            "candidate_collection_policy": f"每天实时搜索，先切换排序 {', '.join(sort_modes)}，各采集前 {max_search_page} 页，不复用前一天供应商。",
            "candidates": [],
        }

    normalized_modes = [normalize_text(mode) for mode in sort_modes]
    filtered_candidates = [
        candidate
        for candidate in raw_candidates
        if candidate_search_page(candidate) <= max_search_page and candidate_sort_mode(candidate) in normalized_modes
    ]
    scores = [score_candidate(candidate, line) for candidate in raw_candidates]
    scores.sort(key=lambda item: (item.allowed, item.score), reverse=True)
    combination = choose_combination(scores, line)
    return {
        "name": line.get("name"),
        "sku": line.get("sku"),
        "requested_quantity": line.get("requested_quantity"),
        "unit": line.get("unit"),
        "status": combination["status"],
        "message": combination["message"],
        "selection": combination.get("selection") or [],
        "planned_quantity": combination.get("planned_quantity"),
        "overage": combination.get("overage"),
        "estimated_cost": combination.get("estimated_cost"),
        "risk_flags": combination.get("risk_flags") or [],
        "candidate_count": len(raw_candidates),
        "eligible_first_pages_candidate_count": len(filtered_candidates),
        "allowed_sort_modes": sort_modes,
        "safe_candidate_count": sum(1 for score in scores if score.allowed),
        "top_candidates": [
            {
                "candidate_id": candidate_id(score.candidate),
                "title": score.candidate.get("title") or score.candidate.get("name"),
                "spec": score.candidate.get("spec") or score.candidate.get("pack_label"),
                "price": score.candidate.get("price") or score.candidate.get("sale_price") or score.candidate.get("final_price"),
                "pack_quantity": score.pack_quantity,
                "unit_price": score.unit_price,
                "sales": score.sales,
                "search_page": score.page,
                "sort_mode": score.sort_mode,
                "value_score": score.value_score,
                "allowed": score.allowed,
                "score": score.score,
                "reasons": score.reasons,
                "risk_flags": score.risk_flags,
            }
            for score in scores[:8]
        ],
    }


def build_payload(
    order: dict[str, Any],
    candidate_payload: dict[str, Any],
    max_search_page: int = DEFAULT_MAX_SEARCH_PAGE,
    sort_modes: list[str] | None = None,
) -> dict[str, Any]:
    sort_modes = sort_modes or DEFAULT_SORT_MODES
    lines = []
    for item in kuailv_items(order):
        line = build_line_plan(item)
        rule = PACK_RULES.get(str(item.get("name") or "")) or {}
        line["allowed_overage"] = safe_float(rule.get("allowed_overage"), 0)
        line["prefer_single_pack"] = safe_float(rule.get("prefer_single_pack"), 0)
        lines.append(line)
    decisions = [decision_for_line(line, candidates_for_line(candidate_payload, line), max_search_page, sort_modes) for line in lines]
    blocking = [row for row in decisions if row["status"] in {"blocked", "needs_candidates"}]
    review = [row for row in decisions if row["status"] == "needs_review"]
    status = "ready" if not blocking and not review else "needs_review" if not blocking else "needs_candidates"
    return {
        "generated_at": now_text(),
        "status": status,
        "order": {
            "order_id": order.get("order_id"),
            "store_name": order.get("store_name"),
            "submitted_at": order.get("submitted_at"),
            "channel": CHANNEL,
        },
        "summary": {
            "line_count": len(decisions),
            "ready_count": sum(1 for row in decisions if row["status"] == "ready"),
            "needs_review_count": len(review),
            "needs_candidates_count": sum(1 for row in decisions if row["status"] == "needs_candidates"),
            "blocked_count": sum(1 for row in decisions if row["status"] == "blocked"),
            "estimated_cost": round(sum(safe_float(row.get("estimated_cost")) for row in decisions), 2),
        },
        "decisions": decisions,
        "safety": {
            "dry_run": True,
            "forbidden_actions": ["提交订单", "付款", "切换地址"],
            "supplier_policy": f"每天供应商不固定；必须当天实时搜索，按 {', '.join(sort_modes)} 排序后分别采集前 {max_search_page} 页，再按价格和销量择优。",
            "sku_cache_policy": "SKU 只能作为当天候选标识；不得复用前一天供应商/SKU 直接加购。",
        },
        "message": "快驴采购决策已生成；只做择优计划，不执行加购。",
    }


def read_candidates(path_text: str) -> dict[str, Any]:
    if not path_text:
        return {}
    path = Path(path_text)
    return json.loads(path.read_text(encoding="utf-8"))


def write_latest(payload: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LATEST_PATH.chmod(0o644)


def print_summary(payload: dict[str, Any]) -> None:
    print(payload["message"])
    print(f"订单：{payload['order'].get('order_id')} / {payload['order'].get('store_name')}")
    print(f"状态：{payload['status']} / {payload['summary']}")
    for row in payload["decisions"]:
        print(f"- {row['name']}: {row['status']} - {row['message']}")
        for selected in row.get("selection") or []:
            print(f"  选：{selected.get('title')} {selected.get('spec') or ''} x {selected.get('count')}")
    print(f"结果文件：{LATEST_PATH}")


def main() -> int:
    parser = argparse.ArgumentParser(description="快驴采购决策引擎：基于实时候选择优，不执行加购。")
    parser.add_argument("--server", default=DEFAULT_SERVER)
    parser.add_argument("--token", default=DEFAULT_TOKEN)
    parser.add_argument("--date", default=datetime.now().astimezone().strftime("%Y-%m-%d"))
    parser.add_argument("--order-id", default="")
    parser.add_argument("--candidates", default="", help="候选商品 JSON；为空时输出需要采集的搜索规格计划")
    parser.add_argument("--max-search-page", type=int, default=DEFAULT_MAX_SEARCH_PAGE, help="只允许使用搜索结果前 N 页候选，默认 2")
    parser.add_argument("--sort-modes", default=",".join(DEFAULT_SORT_MODES), help="候选必须来自这些排序模式，逗号分隔；默认 price_asc,sales_desc")
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()

    try:
        order = load_order(args.server, args.token, args.date, args.order_id, args.timeout)
        sort_modes = [item.strip() for item in args.sort_modes.split(",") if item.strip()]
        payload = build_payload(order, read_candidates(args.candidates), max(1, args.max_search_page), sort_modes or DEFAULT_SORT_MODES)
        write_latest(payload)
        print_summary(payload)
        return 0 if payload["status"] in {"ready", "needs_candidates", "needs_review"} else 1
    except Exception as exc:
        payload = {
            "generated_at": now_text(),
            "status": "failed",
            "message": f"快驴采购决策生成失败：{exc}",
            "decisions": [],
        }
        write_latest(payload)
        print(payload["message"], file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
