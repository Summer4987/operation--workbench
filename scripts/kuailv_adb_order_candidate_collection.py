from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from kuailv_adb_ranked_candidate_capture import (
    build_payload as build_capture_payload,
    capture_snapshot,
    scroll_results,
    tap_sort_control,
)
from kuailv_order_dry_run import (
    CHANNEL,
    DEFAULT_SERVER,
    DEFAULT_TOKEN,
    build_line_plan,
    build_plan,
    eligible_orders,
    run_adb_search,
)
from kuailv_purchase_decision import DEFAULT_MAX_SEARCH_PAGE, DEFAULT_SORT_MODES, build_payload as build_decision_payload


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "kuailv_adb_order_candidate_collection"
LATEST_PATH = OUTPUT_DIR / "latest.json"


def now_text() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S%z")


def read_json_url(url: str, timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "kuailv-adb-order-candidate-collection/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def admin_summary_url(server: str, token: str) -> str:
    query = urllib.parse.urlencode({"status": "all", "token": token})
    return f"{server.rstrip('/')}/daily-order/api/admin/summary?{query}"


def load_order_from_server(server: str, token: str, date_text: str, order_id: str, timeout: int) -> dict[str, Any]:
    payload = read_json_url(admin_summary_url(server, token), timeout)
    candidates = eligible_orders(payload, date_text, order_id)
    if not candidates:
        suffix = f"订单 {order_id}" if order_id else f"{date_text} 的快驴订单"
        raise RuntimeError(f"没有找到{suffix}。")
    return candidates[0]


def load_order(args: argparse.Namespace) -> dict[str, Any]:
    if args.order_file:
        return json.loads(Path(args.order_file).read_text(encoding="utf-8"))
    return load_order_from_server(args.server, args.token, args.date, args.order_id, args.timeout)


def kuailv_items(order: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in order.get("items") or [] if str(item.get("purchase_channel") or "") == CHANNEL]


def parse_modes(text: str) -> list[str]:
    values = [item.strip() for item in text.split(",") if item.strip()]
    return values or list(DEFAULT_SORT_MODES)


def collection_jobs(order: dict[str, Any], sort_modes: list[str], max_search_page: int) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for item in kuailv_items(order):
        line = build_line_plan(item)
        if line.get("action") != "search_and_add":
            continue
        for query in line.get("search_terms") or [line.get("name")]:
            if not query:
                continue
            for sort_mode in sort_modes:
                jobs.append(
                    {
                        "line_name": line.get("name"),
                        "query": query,
                        "sort_mode": sort_mode,
                        "pages": list(range(1, max_search_page + 1)),
                        "required_keywords": line.get("required_keywords") or [],
                        "excluded_keywords": line.get("excluded_keywords") or [],
                        "preferred_spec_keywords": line.get("preferred_spec_keywords") or [],
                    }
                )
    return jobs


def capture_current_page(
    serial: str,
    query: str,
    sort_mode: str,
    search_page: int,
    order: dict[str, Any],
    line_name: str,
    timeout: int,
) -> dict[str, Any]:
    snapshot = capture_snapshot(serial, timeout)
    return build_capture_payload(snapshot.get("xml_text") or "", query, sort_mode, search_page, order, line_name, snapshot)


def run_sort_and_page_captures(
    serial: str,
    query: str,
    sort_mode: str,
    order: dict[str, Any],
    line_name: str,
    max_search_page: int,
    timeout: int,
    sort_wait: float,
    scroll_wait: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    before_sort = capture_snapshot(serial, timeout)
    sort_tap = tap_sort_control(serial, before_sort.get("xml_text") or "", sort_mode, 1, timeout)
    if sort_tap.get("status") != "tapped":
        return [
            {
                "status": "blocked",
                "query": query,
                "sort_mode": sort_mode,
                "search_page": 1,
                "message": sort_tap.get("message") or "排序点击失败。",
                "capture": {"sort_tap": sort_tap},
                "items": [],
            }
        ]
    time.sleep(max(0.0, sort_wait))
    for page in range(1, max_search_page + 1):
        if page > 1:
            scroll_result = scroll_results(serial, 1, timeout)
            time.sleep(max(0.0, scroll_wait))
        else:
            scroll_result = None
        snapshot = capture_snapshot(serial, timeout)
        if scroll_result:
            snapshot["scroll"] = scroll_result
        snapshot["sort_tap"] = sort_tap
        rows.append(build_capture_payload(snapshot.get("xml_text") or "", query, sort_mode, page, order, line_name, snapshot))
    return rows


def flatten_items(captures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for capture in captures:
        for item in capture.get("items") or []:
            items.append(item)
    return items


def group_candidates(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        line_name = str(item.get("line_name") or "")
        if not line_name:
            continue
        grouped.setdefault(line_name, []).append(item)
    return grouped


def build_plan_payload(order: dict[str, Any], sort_modes: list[str], max_search_page: int) -> dict[str, Any]:
    jobs = collection_jobs(order, sort_modes, max_search_page)
    return {
        "generated_at": now_text(),
        "status": "needs_collection",
        "order": {
            "order_id": order.get("order_id"),
            "store_name": order.get("store_name"),
            "submitted_at": order.get("submitted_at"),
            "channel": CHANNEL,
        },
        "summary": {
            "line_count": len({job["line_name"] for job in jobs}),
            "job_count": len(jobs),
            "candidate_count": 0,
        },
        "collection_policy": {
            "sort_modes": sort_modes,
            "max_search_page": max_search_page,
            "supplier_reuse_allowed": False,
            "forbidden_actions": ["加购", "删除", "清空", "切换收货地址", "提交订单", "付款"],
        },
        "collection_jobs": jobs,
        "captures": [],
        "candidates": {},
        "message": "已生成快驴 ADB 逐品项排序候选采集计划；未连接安卓执行。",
    }


def build_adb_summary_payload(
    order: dict[str, Any],
    sort_modes: list[str],
    max_search_page: int,
    search_runs: list[dict[str, Any]],
    captures: list[dict[str, Any]],
    message: str,
) -> dict[str, Any]:
    items = flatten_items(captures)
    grouped = group_candidates(items)
    decision = build_decision_payload(order, grouped, max_search_page=max_search_page, sort_modes=sort_modes)
    blocked = [capture for capture in captures if capture.get("status") not in {"ready", "needs_review"}]
    return {
        "generated_at": now_text(),
        "status": "ready" if grouped and not blocked else "needs_review" if grouped else "blocked",
        "order": {
            "order_id": order.get("order_id"),
            "store_name": order.get("store_name"),
            "submitted_at": order.get("submitted_at"),
            "channel": CHANNEL,
        },
        "summary": {
            "line_count": len({build_line_plan(item).get("name") for item in kuailv_items(order) if build_line_plan(item).get("action") == "search_and_add"}),
            "search_run_count": len(search_runs),
            "capture_count": len(captures),
            "candidate_count": len(items),
            "blocked_capture_count": len(blocked),
        },
        "collection_policy": {
            "sort_modes": sort_modes,
            "max_search_page": max_search_page,
            "supplier_reuse_allowed": False,
            "forbidden_actions": ["加购", "删除", "清空", "切换收货地址", "提交订单", "付款"],
        },
        "search_runs": search_runs,
        "captures": captures,
        "candidates": grouped,
        "decision": decision,
        "message": message,
    }


def build_adb_payload(
    order: dict[str, Any],
    serial: str,
    sort_modes: list[str],
    max_search_page: int,
    timeout: int,
    search_pre_back_count: int,
    sort_wait: float,
    scroll_wait: float,
    line_limit: int,
) -> dict[str, Any]:
    plan = build_plan(order)
    captures: list[dict[str, Any]] = []
    search_runs: list[dict[str, Any]] = []
    items_to_collect = [item for item in kuailv_items(order) if build_line_plan(item).get("action") == "search_and_add"]
    if line_limit > 0:
        items_to_collect = items_to_collect[:line_limit]
    for item in items_to_collect:
        line = build_line_plan(item)
        query = str((line.get("search_terms") or [line.get("name")])[0] or "")
        if not query:
            continue
        search_result = run_adb_search(
            plan,
            serial,
            timeout,
            query,
            0,
            0,
            0,
            search_pre_back_count,
            True,
        )
        search_runs.append(
            {
                "line_name": line.get("name"),
                "query": query,
                "status": search_result.get("status"),
                "message": search_result.get("message"),
                "session_dir": search_result.get("session_dir"),
            }
        )
        print(f"搜索 {line.get('name')} / {query}: {search_result.get('status')}", flush=True)
        search_result_check = search_result.get("search_result_check") or {}
        search_can_capture = search_result.get("status") == "search_ready_for_manual_review" or bool(search_result_check.get("page_text_hit_count"))
        if not search_can_capture:
            for sort_mode in sort_modes:
                captures.append(
                    {
                        "status": "blocked",
                        "query": query,
                        "sort_mode": sort_mode,
                        "search_page": 1,
                        "line_name": line.get("name"),
                        "message": search_result.get("message") or "搜索未进入可采集状态。",
                        "items": [],
                    }
                )
            write_latest(
                build_adb_summary_payload(
                    order,
                    sort_modes,
                    max_search_page,
                    search_runs,
                    captures,
                    "快驴订单候选采集中；最近一次搜索被阻断，已写入增量结果。",
                )
            )
            continue
        if search_result.get("status") != "search_ready_for_manual_review":
            print(f"搜索 {line.get('name')} / {query}: 结果文本已命中，继续只读采集候选", flush=True)
        for sort_mode in sort_modes:
            sort_captures = run_sort_and_page_captures(
                serial,
                query,
                sort_mode,
                order,
                str(line.get("name") or ""),
                max_search_page,
                timeout,
                sort_wait,
                scroll_wait,
            )
            captures.extend(sort_captures)
            print(f"采集 {line.get('name')} / {query} / {sort_mode}: {sum(len(row.get('items') or []) for row in sort_captures)} 个候选", flush=True)
            write_latest(
                build_adb_summary_payload(
                    order,
                    sort_modes,
                    max_search_page,
                    search_runs,
                    captures,
                    "快驴订单候选采集中；已写入增量结果。",
                )
            )
    return build_adb_summary_payload(order, sort_modes, max_search_page, search_runs, captures, "已按订单逐品项采集快驴排序候选并生成决策；未加购、未提交、未付款。")


def write_latest(payload: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LATEST_PATH.chmod(0o644)


def print_summary(payload: dict[str, Any]) -> None:
    print(payload["message"])
    print(f"订单：{payload['order'].get('order_id')} / {payload['order'].get('store_name')}")
    print(f"状态：{payload['status']} / {payload['summary']}")
    for line_name, rows in (payload.get("candidates") or {}).items():
        print(f"- {line_name}: {len(rows)} 个候选")
    if payload.get("decision"):
        print(f"决策：{payload['decision'].get('status')} / {payload['decision'].get('summary')}")
    print(f"结果文件：{LATEST_PATH}")


def main() -> int:
    parser = argparse.ArgumentParser(description="按订单逐品项采集快驴 ADB 排序候选并汇总给决策引擎。")
    parser.add_argument("--mode", choices=["plan", "adb"], default="plan")
    parser.add_argument("--server", default=DEFAULT_SERVER)
    parser.add_argument("--token", default=DEFAULT_TOKEN)
    parser.add_argument("--date", default=datetime.now().astimezone().strftime("%Y-%m-%d"))
    parser.add_argument("--order-id", default="")
    parser.add_argument("--order-file", default="", help="本地订单 JSON；用于后台 auth 不可用时继续采集")
    parser.add_argument("--adb-serial", default="")
    parser.add_argument("--max-search-page", type=int, default=DEFAULT_MAX_SEARCH_PAGE)
    parser.add_argument("--sort-modes", default=",".join(DEFAULT_SORT_MODES))
    parser.add_argument("--search-pre-back-count", type=int, default=1)
    parser.add_argument("--sort-wait", type=float, default=2.0)
    parser.add_argument("--scroll-wait", type=float, default=1.2)
    parser.add_argument("--line-limit", type=int, default=0, help="只采集前 N 个快驴品项；0 表示全量")
    parser.add_argument("--timeout", type=int, default=25)
    args = parser.parse_args()

    try:
        order = load_order(args)
        sort_modes = parse_modes(args.sort_modes)
        max_page = max(1, args.max_search_page)
        if args.mode == "plan":
            payload = build_plan_payload(order, sort_modes, max_page)
        else:
            payload = build_adb_payload(
                order,
                args.adb_serial.strip(),
                sort_modes,
                max_page,
                args.timeout,
                max(0, args.search_pre_back_count),
                args.sort_wait,
                args.scroll_wait,
                max(0, args.line_limit),
            )
        write_latest(payload)
        print_summary(payload)
        return 0 if payload["status"] in {"ready", "needs_collection", "needs_review"} else 1
    except Exception as exc:
        payload = {
            "generated_at": now_text(),
            "status": "failed",
            "message": f"快驴订单候选批量采集失败：{exc}",
        }
        write_latest(payload)
        print(payload["message"], file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
