#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STORE_INSPECTION = ROOT / "store-inspection"
if str(STORE_INSPECTION) not in sys.path:
    sys.path.insert(0, str(STORE_INSPECTION))

PREVIEW_PATH = ROOT / "outputs" / "promo_budget_preview" / "latest.json"
MEITUAN_BUDGET_LOG_DIR = ROOT / "outputs" / "meituan_budget_automation"
OUTPUT_DIR = ROOT / "outputs" / "meituan_promo_spend"
LATEST_PATH = OUTPUT_DIR / "latest.json"


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_money(value: str) -> float | None:
    match = re.search(r"-?\d+(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?", str(value or ""))
    if not match:
        return None
    return float(match.group(0).replace(",", ""))


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def parse_spend_snapshot(text: str) -> dict[str, Any]:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    snapshot: dict[str, Any] = {
        "today_spend": None,
        "yesterday_spend": None,
        "seven_day_spend": None,
        "updated_at_hint": "",
        "source": "",
    }

    for line in lines:
        match = re.search(r"今日\s*([0-9]{2}-[0-9]{2}\s+[0-9]{2}:[0-9]{2})\s*更新", line)
        if match:
            snapshot["updated_at_hint"] = match.group(1)
            break

    def amount_after_label(start: int, stop_words: set[str]) -> tuple[float | None, float | None]:
        today = None
        yesterday = None
        for candidate in lines[start + 1 : start + 12]:
            if any(word in candidate for word in stop_words):
                break
            if "昨日" in candidate:
                yesterday = parse_money(candidate)
                continue
            if today is None and "元" in candidate:
                today = parse_money(candidate)
        return today, yesterday

    for index, line in enumerate(lines):
        if line != "推广实况":
            continue
        window = lines[index + 1 : index + 80]
        for offset, candidate in enumerate(window, start=index + 1):
            if candidate == "历史数据":
                break
            if candidate == "推广花费":
                today, yesterday = amount_after_label(offset, {"推广曝光量", "历史数据", "推广设置"})
                if today is not None:
                    snapshot.update(today_spend=today, yesterday_spend=yesterday, source="realtime")
                    return snapshot

    compact = "\n".join(lines)
    realtime_match = re.search(r"推广实况(?P<section>.*?)(?:历史数据|推广设置|$)", compact, re.S)
    realtime_section = realtime_match.group("section") if realtime_match else compact
    match = re.search(r"推广花费\s*([0-9,.]+)\s*元(?:\s*昨日\s*([0-9,.]+)\s*元)?", realtime_section, re.S)
    if match:
        snapshot.update(
            today_spend=parse_money(match.group(1)),
            yesterday_spend=parse_money(match.group(2) or ""),
            source="realtime_regex",
        )
        return snapshot

    for index, line in enumerate(lines):
        if line == "总推广花费":
            for candidate in lines[index + 1 : index + 8]:
                amount = parse_money(candidate)
                if amount is not None and "元" in candidate:
                    snapshot.update(today_spend=amount, source="homepage_total")
                    return snapshot

    budget_spend = parse_budget_spend(lines)
    if budget_spend.get("today_spend") is not None:
        snapshot.update(budget_spend)
        return snapshot

    for index, line in enumerate(lines):
        if line == "推广花费":
            today, yesterday = amount_after_label(index, {"推广曝光量", "排名数据", "推广设置"})
            if today is not None:
                snapshot.update(seven_day_spend=today, yesterday_spend=yesterday, source="fallback")
                return snapshot

    return snapshot


def parse_budget_spend(lines: list[str]) -> dict[str, Any]:
    compact = " ".join(lines)
    match = re.search(
        r"(?:推广预算|每日预算)(?:(?!推广出价|定向推广|计费规则).)*?已消耗\s*(\d+(?:\.\d+)?)\s*%\s*([0-9,.]+)\s*元",
        compact,
    )
    if match:
        percent = float(match.group(1))
        budget = parse_money(match.group(2))
        if budget is not None:
            return {"today_spend": round(budget * percent / 100, 2), "source": "budget_percent"}
    match = re.search(
        r"(?:推广预算|每日预算)(?:(?!推广出价|定向推广|计费规则).)*?预算已耗尽\s*([0-9,.]+)\s*元",
        compact,
    )
    if match:
        budget = parse_money(match.group(1))
        if budget is not None:
            return {"today_spend": budget, "source": "budget_exhausted"}

    for index, line in enumerate(lines):
        if line not in {"推广预算", "每日预算"}:
            continue
        window = lines[index + 1 : index + 12]
        budget = None
        percent = None
        exhausted = False
        for offset, candidate in enumerate(window):
            if any(word in candidate for word in {"推广出价", "定向推广", "计费规则", "预算设置"}):
                break
            percent_match = re.search(r"已消耗\s*(\d+(?:\.\d+)?)\s*%", candidate)
            if percent_match:
                percent = float(percent_match.group(1))
            if "预算已耗尽" in candidate:
                exhausted = True
            if "元" in candidate:
                amount = parse_money(candidate)
                if amount is not None:
                    budget = amount
                    break
            if offset + 1 < len(window) and window[offset + 1] == "元":
                amount = parse_money(candidate)
                if amount is not None:
                    budget = amount
                    break
        if budget is None:
            continue
        if exhausted:
            return {"today_spend": budget, "source": "budget_exhausted"}
        if percent is not None:
            return {"today_spend": round(budget * percent / 100, 2), "source": "budget_percent"}
    return {}


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_recent_wm_ids() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for path in sorted(MEITUAN_BUDGET_LOG_DIR.glob("meituan_cdp_*.json"), reverse=True):
        payload = read_json(path)
        for item in payload.get("results") or []:
            wm_id = str(item.get("wmPoiId") or item.get("wm_poi_id") or "").strip()
            if not wm_id:
                continue
            for key in ("keyword", "store"):
                value = str(item.get(key) or "").strip()
                if value and value not in mapping:
                    mapping[value] = wm_id
    return mapping


def load_meituan_tasks(period: str) -> list[dict[str, Any]]:
    payload = read_json(PREVIEW_PATH)
    if not payload:
        raise RuntimeError("没有找到推广预算预览文件，先运行推广预算预览或上午运营采集。")
    keys = ["meituan_lunch", "meituan_dinner"] if period == "all" else [f"meituan_{period}"]
    tasks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key in keys:
        for item in payload.get(key) or []:
            if item.get("status") not in {"auto", "scheduled"}:
                continue
            unique = str(item.get("keyword") or item.get("store") or item.get("wmPoiId") or "")
            if not unique or unique in seen:
                continue
            seen.add(unique)
            tasks.append(item)
    if not tasks:
        raise RuntimeError("推广预算预览里没有找到美团门店。")
    wm_ids = load_recent_wm_ids()
    hydrated = []
    for task in tasks:
        item = dict(task)
        if not (item.get("wmPoiId") or item.get("wm_poi_id")):
            for key in ("keyword", "store"):
                value = str(item.get(key) or "").strip()
                if value in wm_ids:
                    item["wmPoiId"] = wm_ids[value]
                    break
        hydrated.append(item)
    return hydrated


def require_helpers() -> dict[str, Any]:
    try:
        from meituan_budget_cdp import (  # noqa: PLC0415
            base_url_for_task,
            classify_failure,
            context_for_task,
            enter_dianjin_with_recovery,
            load_direct_meituan_accounts,
            page_text,
            recent_meituan_promo_url,
            save_failure_evidence,
            sync_playwright,
            url_for_store,
            wait_setting_ready,
            wm_poi_id,
        )
    except ModuleNotFoundError as exc:
        if exc.name == "playwright":
            raise RuntimeError("Mac mini 当前 Python 缺少 Playwright，不能读取美团后台。") from exc
        raise
    return locals()


def query_task(task: dict[str, Any], helpers: dict[str, Any], playwright, contexts: dict[str, Any], launched_contexts: list[Any], base_url: str, direct_accounts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    keyword = task.get("keyword") or task.get("sourceStore") or task.get("store") or "未命名门店"
    record: dict[str, Any] = {
        "platform": "美团",
        "store": task.get("store") or "",
        "keyword": keyword,
        "wmPoiId": task.get("wmPoiId") or task.get("wm_poi_id") or "",
        "directMeituanAccountId": task.get("directMeituanAccountId") or "",
        "ok": False,
        "today_spend": None,
        "yesterday_spend": None,
        "seven_day_spend": None,
        "updated_at_hint": "",
        "source": "",
    }
    page = None
    created_page = False
    try:
        context = helpers["context_for_task"](playwright, contexts, launched_contexts, task, direct_accounts)
        task_base_url = helpers["base_url_for_task"](base_url, task, direct_accounts, context)
        wm_id = helpers["wm_poi_id"](task)
        target_url = helpers["url_for_store"](task_base_url, wm_id)
        record["wmPoiId"] = wm_id
        page = context.new_page()
        created_page = True
        page.goto(target_url, wait_until="domcontentloaded", timeout=45_000)
        time.sleep(4)
        helpers["enter_dianjin_with_recovery"](page, target_url)
        helpers["wait_setting_ready"](page, timeout_seconds=20)
        text = helpers["page_text"](page)
        snapshot = parse_spend_snapshot(text)
        record.update(snapshot)
        record["ok"] = record.get("today_spend") is not None or record.get("seven_day_spend") is not None
        if record["ok"]:
            amount = record.get("today_spend") if record.get("today_spend") is not None else record.get("seven_day_spend")
            record["message"] = f"{keyword} 推广消耗 {amount:g} 元。"
        else:
            record["error"] = "页面已打开，但没有解析到推广花费。"
            record["text_preview"] = normalize_space(text)[:500]
    except Exception as exc:
        record["error"] = str(exc)
        try:
            record["failure_type"] = helpers["classify_failure"](str(exc))
        except Exception:
            record["failure_type"] = "execution_failed"
        if page is not None:
            try:
                record["evidence"] = helpers["save_failure_evidence"](page, task, record["failure_type"])
            except Exception:
                pass
    finally:
        if created_page and page is not None:
            try:
                page.close()
            except Exception:
                pass
    return record


def build_payload(period: str, stores: list[str], limit: int | None) -> dict[str, Any]:
    helpers = require_helpers()
    tasks = load_meituan_tasks(period)
    if stores:
        needles = [normalize_space(item).lower() for item in stores]
        tasks = [
            task for task in tasks
            if any(needle in normalize_space(" ".join(str(task.get(key, "")) for key in ("keyword", "store", "sourceStore"))).lower() for needle in needles)
        ]
        if not tasks:
            raise RuntimeError("没有匹配到指定美团门店：" + "、".join(stores))
    if limit is not None:
        tasks = tasks[:limit]

    direct_accounts = helpers["load_direct_meituan_accounts"]()
    base_url = helpers["recent_meituan_promo_url"]()
    if not base_url and any(not task.get("directMeituanAccountId") for task in tasks):
        raise RuntimeError("没有找到本机 Chrome 最近的美团点金推广页，请先在 Mac mini 打开一次美团点金推广。")
    base_url = base_url or ""

    results: list[dict[str, Any]] = []
    with helpers["sync_playwright"]() as playwright:
        contexts: dict[str, Any] = {}
        launched_contexts: list[Any] = []
        try:
            for task in tasks:
                print(f"读取美团推广消耗：{task.get('keyword') or task.get('store')}", flush=True)
                results.append(query_task(task, helpers, playwright, contexts, launched_contexts, base_url, direct_accounts))
        finally:
            for context in launched_contexts:
                try:
                    context.close()
                except Exception:
                    pass

    ok_items = [item for item in results if item.get("ok")]
    failed_items = [item for item in results if not item.get("ok")]
    total = sum(float(item.get("today_spend") or 0) for item in ok_items if item.get("today_spend") is not None)
    return {
        "generated_at": now_text(),
        "status": "ok" if ok_items and not failed_items else "partial" if ok_items else "failed",
        "period": period,
        "summary": {
            "store_count": len(results),
            "success_count": len(ok_items),
            "failed_count": len(failed_items),
            "today_spend_total": round(total, 2),
        },
        "items": results,
        "message": format_human(results),
    }


def write_latest(payload: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LATEST_PATH.chmod(0o600)


def money(value: Any) -> str:
    if value in (None, ""):
        return "未知"
    return f"{float(value):.2f}".rstrip("0").rstrip(".")


def format_human(items: list[dict[str, Any]]) -> str:
    ok_items = [item for item in items if item.get("ok")]
    failed_items = [item for item in items if not item.get("ok")]
    total = sum(float(item.get("today_spend") or 0) for item in ok_items if item.get("today_spend") is not None)
    lines = [f"查到了 {len(ok_items)}/{len(items)} 家美团门店的推广消耗，今日合计 {money(total)} 元。"]
    for item in ok_items:
        keyword = item.get("keyword") or item.get("store") or "未命名门店"
        detail = f"{keyword}：今日 {money(item.get('today_spend'))} 元"
        if item.get("yesterday_spend") is not None:
            detail += f"，昨日 {money(item.get('yesterday_spend'))} 元"
        if item.get("updated_at_hint"):
            detail += f"，页面更新时间 {item.get('updated_at_hint')}"
        lines.append(detail + "。")
    if failed_items:
        lines.append("没查到的门店：" + "；".join(f"{item.get('keyword') or item.get('store')}：{item.get('error') or '未知错误'}" for item in failed_items[:8]) + "。")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="只读查询美团点金推广消耗。")
    parser.add_argument("--period", choices=["lunch", "dinner", "all"], default="lunch", help="读取哪组美团门店配置；默认午餐门店。")
    parser.add_argument("--stores", default="", help="只查指定门店/关键词，逗号分隔。")
    parser.add_argument("--limit", type=int, default=0, help="调试用：最多读取多少家；0 表示不限制。")
    parser.add_argument("--json", action="store_true", help="输出 JSON。")
    args = parser.parse_args(argv)
    stores = [item.strip() for item in args.stores.split(",") if item.strip()]
    payload = build_payload(args.period, stores, args.limit or None)
    write_latest(payload)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(payload["message"])
    return 0 if payload["status"] in {"ok", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
