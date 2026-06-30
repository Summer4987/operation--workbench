from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from kuailv_order_dry_run import (
    DEFAULT_SERVER,
    DEFAULT_TOKEN,
    LATEST_PATH as DRY_RUN_LATEST_PATH,
    OUTPUT_DIR as DRY_RUN_OUTPUT_DIR,
    admin_summary_url,
    auto_add_pack_steps,
    build_plan,
    kuailv_items,
    read_json_url,
    today_text,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "kuailv_order_agent"
LATEST_PATH = OUTPUT_DIR / "latest.json"


def now_text() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S%z")


def order_day(order: dict[str, Any]) -> str:
    return str(order.get("submitted_at") or order.get("order_day") or "")[:10]


def walk_orders(payload: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        if isinstance(payload.get("items"), list) and payload.get("store_name") and (payload.get("order_id") or payload.get("order_ids")):
            found.append(payload)
        for value in payload.values():
            found.extend(walk_orders(value))
    elif isinstance(payload, list):
        for value in payload:
            found.extend(walk_orders(value))
    return found


def select_order(payload: dict[str, Any], date_text: str, store_name: str = "", order_id: str = "") -> dict[str, Any]:
    candidates = []
    for order in walk_orders(payload):
        if order_id and order.get("order_id") != order_id:
            continue
        if date_text and order_day(order) != date_text:
            continue
        if store_name and store_name not in str(order.get("store_name") or ""):
            continue
        if not kuailv_items(order):
            continue
        candidates.append(order)
    if not candidates:
        target = order_id or f"{date_text} {store_name}".strip()
        raise RuntimeError(f"没有找到可执行的快驴订单：{target}")
    candidates.sort(key=lambda order: str(order.get("submitted_at") or ""), reverse=True)
    return candidates[0]


def load_payload(args: argparse.Namespace) -> tuple[dict[str, Any], str]:
    if args.summary_json:
        path = Path(args.summary_json)
        return json.loads(path.read_text(encoding="utf-8")), str(path)
    payload = read_json_url(admin_summary_url(args.server, args.token), args.timeout)
    return payload, admin_summary_url(args.server, "***")


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def run_child(args: list[str], timeout: int) -> dict[str, Any]:
    completed = subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)
    result = {
        "args": args,
        "returncode": completed.returncode,
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
    }
    if DRY_RUN_LATEST_PATH.exists():
        try:
            result["latest_summary"] = summarize_dry_run_latest(json.loads(DRY_RUN_LATEST_PATH.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            result["latest_error"] = f"无法解析 {DRY_RUN_LATEST_PATH}"
    return result


def summarize_dry_run_latest(latest: dict[str, Any]) -> dict[str, Any]:
    adb = latest.get("adb") or {}
    detected: list[str] = []
    for key in ("snapshot", "before", "after"):
        snap = adb.get(key) or {}
        detected.extend(str(text) for text in snap.get("detected_text") or [])
    if not detected:
        for value in adb.values():
            if isinstance(value, dict):
                for key in ("before", "after"):
                    snap = value.get(key) or {}
                    detected.extend(str(text) for text in snap.get("detected_text") or [])
    return {
        "status": latest.get("status"),
        "mode": latest.get("mode"),
        "message": latest.get("message"),
        "adb_status": adb.get("status"),
        "adb_message": adb.get("message"),
        "session_dir": adb.get("session_dir"),
        "detected_text_sample": detected[:80],
        "cart_expectation": adb.get("cart_expectation"),
    }


def latest_summary_status(child: dict[str, Any]) -> str:
    return str((child.get("latest_summary") or {}).get("adb_status") or "")


def latest_summary_message(child: dict[str, Any]) -> str:
    return str((child.get("latest_summary") or {}).get("adb_message") or "")


def latest_saw_empty_cart(child: dict[str, Any]) -> bool:
    text = " ".join(str(item) for item in (child.get("latest_summary") or {}).get("detected_text_sample") or [])
    return "购物车为空" in text


def cart_clear_assessment(cart_open: dict[str, Any] | None, cart_clear: dict[str, Any] | None) -> dict[str, Any]:
    clear_status = latest_summary_status(cart_clear or {})
    open_empty = latest_saw_empty_cart(cart_open or {})
    clear_empty = latest_saw_empty_cart(cart_clear or {})
    passed_by_status = clear_status in {"cart_already_empty", "cart_cleared_for_manual_review"}
    return {
        "ok": bool(passed_by_status or open_empty or clear_empty),
        "clear_status": clear_status,
        "open_saw_empty_cart": open_empty,
        "clear_saw_empty_cart": clear_empty,
    }


def run_dry_tool(order_path: Path, mode: str, args: argparse.Namespace, extra: list[str] | None = None) -> dict[str, Any]:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "kuailv_order_dry_run.py"),
        "--order-json",
        str(order_path),
        "--mode",
        mode,
        "--adb-serial",
        args.adb_serial,
        "--timeout",
        str(args.timeout),
        "--max-runtime",
        str(args.max_runtime),
    ]
    command.extend(extra or [])
    return run_child(command, args.max_runtime + 30)


def run_agent(args: argparse.Namespace) -> dict[str, Any]:
    payload, source = load_payload(args)
    order = select_order(payload, args.date, args.store_name, args.order_id)
    order = dict(order)
    order["items"] = kuailv_items(order)

    run_dir = OUTPUT_DIR / datetime.now().strftime("%Y%m%d-%H%M%S")
    order_path = run_dir / "selected_order.json"
    write_json(order_path, order)
    plan = build_plan(order)
    steps = auto_add_pack_steps(plan)
    report: dict[str, Any] = {
        "generated_at": now_text(),
        "status": "planned",
        "source": source,
        "run_dir": str(run_dir),
        "selected_order": {
            "order_id": order.get("order_id"),
            "store_name": order.get("store_name"),
            "store_address": order.get("store_address"),
            "submitted_at": order.get("submitted_at"),
            "kuailv_item_count": len(order.get("items") or []),
        },
        "order_json": str(order_path),
        "planned_steps": steps,
        "manual_only_lines": [line for line in plan.get("lines") or [] if line.get("action") != "search_and_add"],
        "safety": {
            "execute": bool(args.execute),
            "clear_cart_first": bool(args.clear_cart_first),
            "forbidden_actions": ["提交订单", "付款", "切换收货地址", "自动替换缺货商品"],
        },
    }
    if not args.execute:
        write_json(run_dir / "report.json", report)
        write_json(LATEST_PATH, report)
        return report

    if args.clear_cart_first:
        report["cart_open"] = run_dry_tool(
            order_path,
            "adb-cart-open",
            args,
            ["--cart-pre-back-count", str(args.cart_pre_back_count)],
        )
        report["cart_clear"] = run_dry_tool(order_path, "adb-cart-clear", args)
        report["cart_clear_assessment"] = cart_clear_assessment(report["cart_open"], report["cart_clear"])
        if not report["cart_clear_assessment"]["ok"]:
            report["status"] = "blocked"
            report["message"] = "购物车清空步骤未通过，已停止整单加购。"
            write_json(run_dir / "report.json", report)
            write_json(LATEST_PATH, report)
            return report

    auto_search_pre_back_count = max(args.search_pre_back_count, args.cart_pre_back_count if args.clear_cart_first else 0)
    report["auto_add"] = run_dry_tool(
        order_path,
        "adb-auto-add-cart",
        args,
        [
            "--confirm-auto-add-cart",
            "--auto-search-pre-back-count",
            str(auto_search_pre_back_count),
            "--auto-cart-pre-back-count",
            str(args.cart_pre_back_count),
        ],
    )
    latest = report["auto_add"].get("latest_summary") or {}
    report["status"] = "ready" if latest.get("adb_status") == "auto_add_cart_ready" else "blocked"
    report["message"] = latest.get("adb_message") or "快驴 agent 已完成执行。"
    write_json(run_dir / "report.json", report)
    write_json(LATEST_PATH, report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="快驴订货 agent：读取订单、清空购物车、自动加购并停在购物车核对。")
    parser.add_argument("--date", default=os.environ.get("ORDER_DATE", today_text()))
    parser.add_argument("--store-name", default=os.environ.get("ORDER_STORE_NAME", ""))
    parser.add_argument("--order-id", default=os.environ.get("ORDER_ID", ""))
    parser.add_argument("--summary-json", default=os.environ.get("DAILY_ORDER_SUMMARY_JSON", ""))
    parser.add_argument("--server", default=os.environ.get("DAILY_ORDER_SERVER", DEFAULT_SERVER))
    parser.add_argument("--token", default=os.environ.get("DAILY_ORDER_ADMIN_TOKEN", DEFAULT_TOKEN))
    parser.add_argument("--adb-serial", default=os.environ.get("ADB_SERIAL", ""))
    parser.add_argument("--execute", action="store_true", help="执行 ADB 自动加购；未指定时只生成计划。")
    parser.add_argument("--clear-cart-first", action="store_true", help="执行前先打开并清空购物车。")
    parser.add_argument("--search-pre-back-count", type=int, default=3)
    parser.add_argument("--cart-pre-back-count", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=12)
    parser.add_argument("--max-runtime", type=int, default=900)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        report = run_agent(args)
    except Exception as exc:  # noqa: BLE001
        report = {"generated_at": now_text(), "status": "blocked", "message": str(exc)}
        write_json(LATEST_PATH, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("status") in {"planned", "ready"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
