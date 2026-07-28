#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parents[1]
STORE_INSPECTION = ROOT / "store-inspection"
if str(STORE_INSPECTION) not in sys.path:
    sys.path.insert(0, str(STORE_INSPECTION))
os.environ.setdefault("NODE_NO_WARNINGS", "1")

PREVIEW_PATH = ROOT / "outputs" / "promo_budget_preview" / "latest.json"
MEITUAN_BUDGET_LOG_DIR = ROOT / "outputs" / "meituan_budget_automation"
OUTPUT_DIR = ROOT / "outputs" / "meituan_promo_spend"
LATEST_PATH = OUTPUT_DIR / "latest.json"
HEADQUARTERS_HOME_URL = "https://e.waimai.meituan.com/"
DIANJIN_SUBAPP_FRAGMENT = "/subapp/isomor_cpc/pages/index/index"
STORE_ALIASES = {
    "第3档口": ["第3档口", "吉祥美食城"],
    "川湘府": ["川湘府", "第5号档口"],
    "金融街": ["金融街"],
    "光谷": ["光谷"],
    "双井": ["双井"],
    "丽泽": ["丽泽"],
    "保利中心": ["保利中心"],
    "安贞": ["安贞"],
    "五一广场": ["五一广场"],
    "望京": ["望京"],
}


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_money(value: str) -> float | None:
    match = re.search(r"-?\d+(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?", str(value or ""))
    if not match:
        return None
    return float(match.group(0).replace(",", ""))


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def visible_page_text(page, timeout: int = 3000) -> str:
    try:
        return page.locator("body").inner_text(timeout=timeout)
    except Exception:
        return ""


def fast_page_text(page, timeout: int = 2500) -> str:
    texts: list[str] = []
    for frame in page.frames:
        try:
            text = frame.locator("body").inner_text(timeout=timeout)
        except Exception:
            continue
        if text:
            texts.append(text)
    return "\n".join(texts)


def wait_parseable_spend_snapshot(
    page,
    *,
    configured_budget: float | None = None,
    timeout_seconds: float = 14,
    interval_seconds: float = 1.0,
) -> tuple[dict[str, Any], str]:
    deadline = time.monotonic() + timeout_seconds
    last_text = ""
    last_snapshot: dict[str, Any] = {}
    while True:
        raise_if_meituan_verify_page(page)
        text = fast_page_text(page)
        if text:
            last_text = text
            snapshot = parse_spend_snapshot(text)
            apply_budget_fields(snapshot, configured_budget)
            last_snapshot = snapshot
            if snapshot_is_current_enough(snapshot, configured_budget):
                return snapshot, text
        if time.monotonic() >= deadline:
            return last_snapshot or parse_spend_snapshot(last_text), last_text
        time.sleep(interval_seconds)


def read_parseable_spend_snapshot(
    page,
    helpers: dict[str, Any],
    *,
    configured_budget: float | None = None,
    attempts: int = 3,
    interval_seconds: float = 2.0,
) -> tuple[dict[str, Any], str]:
    last_text = ""
    last_snapshot: dict[str, Any] = {}
    for attempt in range(max(1, attempts)):
        raise_if_meituan_verify_page(page)
        text = helpers["page_text"](page)
        if text:
            last_text = text
            snapshot = parse_spend_snapshot(text)
            apply_budget_fields(snapshot, configured_budget)
            last_snapshot = snapshot
            if snapshot_is_current_enough(snapshot, configured_budget):
                return snapshot, text
        if attempt + 1 < attempts:
            time.sleep(interval_seconds)
    return last_snapshot or parse_spend_snapshot(last_text), last_text


def snapshot_is_current_enough(snapshot: dict[str, Any], configured_budget: float | None = None) -> bool:
    if snapshot.get("today_spend") is None and snapshot.get("seven_day_spend") is None:
        return False
    source = str(snapshot.get("source") or "")
    if source.startswith("realtime") or source == "homepage_total":
        return True
    page_budget = snapshot.get("budget")
    if source in {"budget_percent", "budget_exhausted"}:
        if page_budget not in (None, "") and float(page_budget) > 0:
            return True
        if configured_budget not in (None, 0, ""):
            return False
    return bool(snapshot.get("updated_at_hint"))


def task_store_aliases(task: dict[str, Any]) -> list[str]:
    values = [
        normalize_space(str(task.get(key) or ""))
        for key in ("keyword", "store", "sourceStore")
    ]
    aliases: list[str] = []
    joined = " ".join(values)
    for value in values:
        if value and value not in aliases:
            aliases.append(value)
    for key, extra_aliases in STORE_ALIASES.items():
        if key in joined:
            for alias in extra_aliases:
                if alias not in aliases:
                    aliases.append(alias)
    return aliases


def parse_spend_snapshot(text: str) -> dict[str, Any]:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    snapshot: dict[str, Any] = {
        "today_spend": None,
        "yesterday_spend": None,
        "seven_day_spend": None,
        "updated_at_hint": "",
        "source": "",
    }
    budget_snapshot = parse_budget_spend(lines)

    def with_budget(payload: dict[str, Any]) -> dict[str, Any]:
        if budget_snapshot.get("budget") is not None and payload.get("budget") is None:
            payload["budget"] = budget_snapshot["budget"]
            payload["budget_source"] = "page"
        if budget_snapshot.get("budget_percent") is not None and payload.get("budget_percent") is None:
            payload["budget_percent"] = budget_snapshot["budget_percent"]
        return payload

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
                    return with_budget(snapshot)

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
        return with_budget(snapshot)

    for index, line in enumerate(lines):
        if line == "总推广花费":
            for candidate in lines[index + 1 : index + 8]:
                amount = parse_money(candidate)
                if amount is not None and "元" in candidate:
                    snapshot.update(today_spend=amount, source="homepage_total")
                    return with_budget(snapshot)

    budget_spend = parse_budget_spend(lines)
    if budget_spend.get("today_spend") is not None:
        snapshot.update(budget_spend)
        snapshot["budget_source"] = "page"
        return snapshot

    for index, line in enumerate(lines):
        if line == "推广花费":
            today, yesterday = amount_after_label(index, {"推广曝光量", "排名数据", "推广设置"})
            if today is not None:
                snapshot.update(seven_day_spend=today, yesterday_spend=yesterday, source="fallback")
                return with_budget(snapshot)

    return with_budget(snapshot)


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
            return {
                "today_spend": round(budget * percent / 100, 2),
                "budget": budget,
                "budget_percent": percent,
                "source": "budget_percent",
            }
    match = re.search(
        r"(?:推广预算|每日预算)(?:(?!推广出价|定向推广|计费规则).)*?预算已耗尽\s*([0-9,.]+)\s*元",
        compact,
    )
    if match:
        budget = parse_money(match.group(1))
        if budget is not None:
            return {
                "today_spend": budget,
                "budget": budget,
                "budget_percent": 100.0,
                "source": "budget_exhausted",
            }

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
            return {
                "today_spend": budget,
                "budget": budget,
                "budget_percent": 100.0,
                "source": "budget_exhausted",
            }
        if percent is not None:
            return {
                "today_spend": round(budget * percent / 100, 2),
                "budget": budget,
                "budget_percent": percent,
                "source": "budget_percent",
            }
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


def is_meituan_ad_url(value: str) -> bool:
    return "waimaieapp.meituan.com/ad/v1" in str(value or "") and "token=" in str(value or "")


def dianjin_url_for_store(base_url: str, wm_id: str, helpers: dict[str, Any] | None = None) -> str:
    """Build a store-specific Meituan Dianjin subapp URL from a recent promo URL."""
    if helpers and "url_for_store" in helpers:
        store_url = helpers["url_for_store"](base_url, wm_id)
    else:
        store_url = replace_wm_poi_id(base_url, wm_id)
    outer = urlsplit(store_url)
    if "waimaieapp.meituan.com/ad/v1" in outer.fragment:
        inner = urlsplit(outer.fragment)
        inner_url = urlunsplit((inner.scheme, inner.netloc, inner.path, inner.query, DIANJIN_SUBAPP_FRAGMENT))
        return urlunsplit((outer.scheme, outer.netloc, outer.path, outer.query, inner_url))
    if "waimaieapp.meituan.com/ad/v1" in outer.netloc + outer.path:
        return urlunsplit((outer.scheme, outer.netloc, outer.path, outer.query, DIANJIN_SUBAPP_FRAGMENT))
    return store_url


def replace_wm_poi_id(raw_url: str, wm_id: str) -> str:
    parts = urlsplit(raw_url)
    if "waimaieapp.meituan.com" in parts.fragment:
        inner = urlsplit(parts.fragment)
        query = dict(parse_qsl(inner.query, keep_blank_values=True))
        query["wmPoiId"] = wm_id
        inner_url = urlunsplit((inner.scheme, inner.netloc, inner.path, urlencode(query), inner.fragment))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, inner_url))
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["wmPoiId"] = wm_id
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def load_meituan_tasks(period: str) -> list[dict[str, Any]]:
    payload = read_json(PREVIEW_PATH)
    if not payload:
        raise RuntimeError("没有找到推广预算预览文件，先运行推广预算预览或上午运营采集。")
    keys = meituan_task_keys(period)
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


def meituan_task_keys(period: str, *, hour: int | None = None) -> list[str]:
    if period != "all":
        return [f"meituan_{period}"]
    current_hour = datetime.now().hour if hour is None else hour
    return ["meituan_dinner", "meituan_lunch"] if current_hour >= 15 else ["meituan_lunch", "meituan_dinner"]


def require_helpers() -> dict[str, Any]:
    try:
        from meituan_budget_cdp import (  # noqa: PLC0415
            base_url_for_task,
            classify_failure,
            click_visible_text,
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


def select_headquarters_store(page, task: dict[str, Any]) -> str:
    aliases = task_store_aliases(task)
    if not aliases:
        raise RuntimeError("总部账号缺少可匹配的分门店关键词。")

    current_page = normalize_space(visible_page_text(page))
    current_url = page.url or ""
    task_wm_id = str(task.get("wmPoiId") or task.get("wm_poi_id") or "").strip()
    current_url_matches_task = bool(task_wm_id and f"wmPoiId={task_wm_id}" in current_url)
    current_text_matches_task = any(alias in current_page for alias in aliases)
    if (
        "waimaieapp.meituan.com/ad/v1" in current_url
        and (current_url_matches_task or (not task_wm_id and current_text_matches_task))
        and ("推广预算" in current_page or "推广首页" in current_page)
    ):
        return next((alias for alias in aliases if alias in current_page), aliases[0])
    if "waimaieapp.meituan.com/ad/v1" in current_url and not current_url_matches_task:
        page.goto(HEADQUARTERS_HOME_URL, wait_until="domcontentloaded", timeout=45_000)
        time.sleep(4)
        dismiss_common_modals(page)

    current = ""
    try:
        current = normalize_space(page.locator(".current-poi_31GHxd").first.inner_text(timeout=3000))
    except Exception:
        current = ""
    if current and any(alias in current for alias in aliases):
        return current

    popup_items = page.locator(".roo-popup.bottom li")
    if popup_items.count() == 0:
        selector = page.locator(".current-poi_31GHxd").first
        if selector.count() == 0:
            raise_if_meituan_verify_page(page)
            try:
                preview = normalize_space(page.locator("body").inner_text(timeout=3000))[:180]
            except Exception:
                preview = ""
            raise RuntimeError(
                "总部账号页面没有找到“全部门店”选择器。"
                f" 当前URL：{page.url or '-'}；页面片段：{preview or '-'}"
            )
        click_after_dismissing_overlay(page, selector)
        popup_items = wait_headquarters_store_menu(page)

    items = popup_items
    available: list[str] = []
    for index in range(items.count()):
        item = items.nth(index)
        text = normalize_space(item.inner_text(timeout=3000))
        available.append(text)
        if "全部门店" in text:
            continue
        if any(alias in text for alias in aliases):
            item.click(timeout=8000)
            for _ in range(18):
                time.sleep(1)
                try:
                    current = normalize_space(page.locator(".current-poi_31GHxd").first.inner_text(timeout=3000))
                except Exception:
                    current = ""
                if current and any(alias in current for alias in aliases):
                    return current
                body = normalize_space(visible_page_text(page, timeout=3000))
                if any(alias in body for alias in aliases):
                    return text
            raise RuntimeError(f"点击门店 {text} 后，页面没有确认切换到目标门店。")
    raise RuntimeError(
        "总部账号门店下拉里没有匹配项："
        + " / ".join(aliases)
        + "；可选："
        + "；".join(available[:12])
    )


def wait_headquarters_store_menu(page):
    items = page.locator(".roo-popup.bottom li")
    for _ in range(10):
        if items.count() > 0:
            return items
        time.sleep(0.5)
    return items


def click_after_dismissing_overlay(page, locator) -> None:
    try:
        locator.click(timeout=8000)
        return
    except Exception as exc:
        if "intercepts pointer events" not in str(exc) and "backdrop" not in str(exc):
            raise
    dismiss_common_modals(page)
    try:
        page.keyboard.press("Escape")
        time.sleep(0.8)
    except Exception:
        pass
    try:
        locator.click(timeout=8000)
    except Exception as exc:
        if "intercepts pointer events" not in str(exc) and "backdrop" not in str(exc):
            raise
        locator.click(timeout=8000, force=True)


def dismiss_common_modals(page) -> None:
    for label in ("稍后处理", "我知道了", "知道了", "确定"):
        try:
            locator = page.get_by_text(label)
            for index in range(min(locator.count(), 4)):
                item = locator.nth(index)
                try:
                    if item.is_visible():
                        item.click(timeout=3000)
                        time.sleep(0.8)
                except Exception:
                    continue
        except Exception:
            continue


def is_meituan_verify_page(page) -> bool:
    url = page.url or ""
    if "verify.meituan.com" in url:
        return True
    try:
        text = normalize_space(page.locator("body").inner_text(timeout=3000))
    except Exception:
        text = ""
    return "安全验证" in text or "验证" in text[:200]


def raise_if_meituan_verify_page(page) -> None:
    if is_meituan_verify_page(page):
        raise RuntimeError("美团触发安全验证，请先在 Mac mini 的对应 Chrome 窗口完成验证后重试。")


def headquarters_page_for_context(context) -> tuple[Any, bool]:
    for page in context.pages:
        if "e.waimai.meituan.com" in (page.url or ""):
            return page, False
    return context.new_page(), True


def open_headquarters_promo_page(page, task: dict[str, Any], helpers: dict[str, Any]) -> str:
    if "e.waimai.meituan.com" not in (page.url or ""):
        page.goto(HEADQUARTERS_HOME_URL, wait_until="domcontentloaded", timeout=45_000)
        time.sleep(4)
    dismiss_common_modals(page)
    selected = ""
    last_select_error = None
    for attempt in range(2):
        try:
            selected = select_headquarters_store(page, task)
            last_select_error = None
            break
        except Exception as exc:
            last_select_error = exc
            if attempt != 0 or "没有确认切换到目标门店" not in str(exc):
                raise
            page.goto(HEADQUARTERS_HOME_URL, wait_until="domcontentloaded", timeout=45_000)
            time.sleep(4)
            dismiss_common_modals(page)
    if last_select_error is not None:
        raise last_select_error
    dismiss_common_modals(page)
    text = helpers["page_text"](page)
    if "waimaieapp.meituan.com/ad/v1" in (page.url or "") and ("推广预算" in text or "推广首页" in text):
        return selected
    if "门店推广" not in text:
        time.sleep(4)
        dismiss_common_modals(page)
        text = helpers["page_text"](page)
    if "门店推广" not in text:
        raise RuntimeError(f"总部账号已切到分门店 {selected}，但页面没有出现门店推广入口。")
    if not helpers["click_visible_text"](page, "门店推广"):
        raise RuntimeError(f"总部账号已切到分门店 {selected}，但点击门店推广失败。")
    for _ in range(20):
        time.sleep(1)
        raise_if_meituan_verify_page(page)
        if any("waimaieapp.meituan.com/ad/v1" in (frame.url or "") for frame in page.frames):
            return selected
    raise RuntimeError(f"总部账号已切到分门店 {selected}，但门店推广内层页面没有加载完成。")


def query_task(task: dict[str, Any], helpers: dict[str, Any], playwright, contexts: dict[str, Any], launched_contexts: list[Any], base_url: str, direct_accounts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    keyword = task.get("keyword") or task.get("sourceStore") or task.get("store") or "未命名门店"
    display_name = task_display_name(task)
    record: dict[str, Any] = {
        "platform": "美团",
        "store": task.get("store") or "",
        "sourceStore": task.get("sourceStore") or "",
        "displayName": display_name,
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
    started_at = time.monotonic()
    configured_budget = task_budget(task)
    if configured_budget is not None:
        record["configured_budget"] = configured_budget
    page = None
    created_page = False
    direct_dianjin_target = False
    try:
        context = helpers["context_for_task"](playwright, contexts, launched_contexts, task, direct_accounts)
        if task.get("directMeituanAccountId"):
            page = context.new_page()
            created_page = True
            task_base_url = helpers["base_url_for_task"](base_url, task, direct_accounts, context)
            try:
                wm_id = helpers["wm_poi_id"](task)
            except RuntimeError:
                wm_id = ""
            target_url = dianjin_url_for_store(task_base_url, wm_id, helpers) if wm_id else task_base_url
            direct_dianjin_target = DIANJIN_SUBAPP_FRAGMENT in target_url
            record["wmPoiId"] = wm_id
            page.goto(target_url, wait_until="domcontentloaded", timeout=30_000)
            time.sleep(1.5)
        else:
            page, created_page = headquarters_page_for_context(context)
            try:
                wm_id = helpers["wm_poi_id"](task)
            except RuntimeError:
                wm_id = ""
            if wm_id and is_meituan_ad_url(base_url):
                target_url = dianjin_url_for_store(base_url, wm_id, helpers)
                direct_dianjin_target = DIANJIN_SUBAPP_FRAGMENT in target_url
                record["wmPoiId"] = wm_id
                page.goto(target_url, wait_until="domcontentloaded", timeout=30_000)
                time.sleep(1.5)
                record["selected_store"] = task_display_name(task)
            else:
                selected_store = open_headquarters_promo_page(page, task, helpers)
                target_url = page.url
                record["selected_store"] = selected_store
        raise_if_meituan_verify_page(page)
        if direct_dianjin_target:
            snapshot, text = wait_parseable_spend_snapshot(
                page,
                configured_budget=configured_budget,
                timeout_seconds=4,
                interval_seconds=0.8,
            )
            if snapshot.get("today_spend") is None and snapshot.get("seven_day_spend") is None:
                snapshot, text = read_parseable_spend_snapshot(
                    page,
                    helpers,
                    configured_budget=configured_budget,
                    attempts=3,
                    interval_seconds=2,
                )
        else:
            helpers["enter_dianjin_with_recovery"](page, target_url)
            helpers["wait_setting_ready"](page, timeout_seconds=20)
            text = helpers["page_text"](page)
            snapshot = parse_spend_snapshot(text)
        record.update(snapshot)
        apply_budget_fields(record, configured_budget)
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
        record["elapsed_seconds"] = round(time.monotonic() - started_at, 2)
        if created_page and page is not None:
            try:
                page.close()
            except Exception:
                pass
    return record


def should_retry_query(record: dict[str, Any]) -> bool:
    if record.get("ok"):
        return False
    message = str(record.get("error") or "")
    if any(token in message for token in ("Target page, context or browser has been closed", "点击门店")):
        return True
    return str(record.get("failure_type") or "") in {"dianjin_entry_missing", "timeout"}


def task_display_name(task: dict[str, Any]) -> str:
    source_store = normalize_space(str(task.get("sourceStore") or ""))
    if task.get("directMeituanAccountId") and source_store:
        return source_store
    return normalize_space(str(task.get("keyword") or task.get("sourceStore") or task.get("store") or "未命名门店"))


def item_display_name(item: dict[str, Any]) -> str:
    return (
        normalize_space(str(item.get("displayName") or ""))
        or normalize_space(str(item.get("sourceStore") or ""))
        or normalize_space(str(item.get("keyword") or ""))
        or normalize_space(str(item.get("store") or ""))
        or "未命名门店"
    )


def task_budget(task: dict[str, Any]) -> float | None:
    for key in ("targetBudget", "budget", "currentBudget"):
        value = task.get(key)
        if value in (None, ""):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def apply_budget_fields(record: dict[str, Any], configured_budget: float | None) -> None:
    if (record.get("budget") in (None, 0, 0.0, "")) and configured_budget is not None:
        record["budget"] = configured_budget
        record["budget_source"] = "configured"
    spend = record.get("today_spend")
    budget = record.get("budget")
    if spend is None or budget in (None, 0, ""):
        return
    spend_value = float(spend)
    budget_value = float(budget)
    record["remaining_budget"] = round(max(budget_value - spend_value, 0), 2)
    record["budget_percent"] = round(spend_value / budget_value * 100, 1)


def filter_tasks(tasks: list[dict[str, Any]], stores: list[str]) -> list[dict[str, Any]]:
    if not stores:
        return tasks
    needles = [normalize_space(item).lower() for item in stores]
    filtered = [
        task for task in tasks
        if any(needle in normalize_space(" ".join(str(task.get(key, "")) for key in ("keyword", "store", "sourceStore"))).lower() for needle in needles)
    ]
    if not filtered:
        raise RuntimeError("没有匹配到指定美团门店：" + "、".join(stores))
    return filtered


def split_evenly(items: list[dict[str, Any]], workers: int) -> list[list[dict[str, Any]]]:
    buckets = [[] for _ in range(max(1, workers))]
    for index, item in enumerate(items):
        buckets[index % len(buckets)].append(item)
    return [bucket for bucket in buckets if bucket]


def split_safe_parallel_groups(items: list[dict[str, Any]], workers: int) -> list[list[dict[str, Any]]]:
    headquarters = [item for item in items if not item.get("directMeituanAccountId")]
    direct = [item for item in items if item.get("directMeituanAccountId")]
    groups: list[list[dict[str, Any]]] = []
    if headquarters:
        groups.append(headquarters)
    direct_workers = max(1, workers - len(groups))
    groups.extend(split_evenly(direct, direct_workers))
    return groups


def task_filter_name(task: dict[str, Any]) -> str:
    return (
        normalize_space(str(task.get("keyword") or ""))
        or normalize_space(str(task.get("sourceStore") or ""))
        or normalize_space(str(task.get("store") or ""))
    )


def merge_payloads(period: str, payloads: list[dict[str, Any]], ordered_tasks: list[dict[str, Any]]) -> dict[str, Any]:
    item_by_name: dict[str, dict[str, Any]] = {}
    for payload in payloads:
        for item in payload.get("items") or []:
            if not isinstance(item, dict):
                continue
            for key in (item_display_name(item), str(item.get("keyword") or ""), str(item.get("sourceStore") or ""), str(item.get("store") or "")):
                name = normalize_space(key)
                if name:
                    item_by_name[name] = item
    results: list[dict[str, Any]] = []
    for task in ordered_tasks:
        names = [task_display_name(task), task_filter_name(task), str(task.get("store") or ""), str(task.get("sourceStore") or "")]
        item = next((item_by_name.get(normalize_space(name)) for name in names if normalize_space(name) in item_by_name), None)
        if item is not None:
            results.append(item)
    if len(results) < sum(len(payload.get("items") or []) for payload in payloads):
        seen = {id(item) for item in results}
        for payload in payloads:
            for item in payload.get("items") or []:
                if isinstance(item, dict) and id(item) not in seen:
                    results.append(item)
                    seen.add(id(item))
    return payload_from_results(period, results)


def build_payload_parallel(period: str, tasks: list[dict[str, Any]], workers: int, *, quiet: bool = False) -> dict[str, Any]:
    payloads: list[dict[str, Any]] = []
    script = Path(__file__).resolve()
    processes: list[tuple[str, subprocess.Popen[str]]] = []
    for chunk in split_safe_parallel_groups(tasks, workers):
        store_filter = ",".join(name for task in chunk if (name := task_filter_name(task)))
        if not store_filter:
            continue
        command = [
            sys.executable or "python3",
            str(script),
            "--period",
            period,
            "--stores",
            store_filter,
            "--workers",
            "1",
            "--json",
            "--quiet",
            "--no-write-latest",
        ]
        processes.append(
            (
                store_filter,
                subprocess.Popen(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT),
            )
        )
    for store_filter, process in processes:
        try:
            stdout, _ = process.communicate(timeout=900)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, _ = process.communicate()
            payloads.append(
                {
                    "items": [
                        {
                            "keyword": store_filter,
                            "displayName": store_filter,
                            "ok": False,
                            "error": "子进程超时：" + (stdout or "")[-600:],
                        }
                    ]
                }
            )
            continue
        if process.returncode not in {0, 2}:
            payloads.append(
                {
                    "items": [
                        {
                            "keyword": store_filter,
                            "displayName": store_filter,
                            "ok": False,
                            "error": (stdout or f"子进程退出码 {process.returncode}")[-1000:],
                        }
                    ]
                }
            )
            continue
        try:
            payloads.append(json.loads(stdout))
        except json.JSONDecodeError:
            payloads.append(
                {
                    "items": [
                        {
                            "keyword": store_filter,
                            "displayName": store_filter,
                            "ok": False,
                            "error": "子进程没有返回可解析 JSON：" + (stdout or "")[-600:],
                        }
                    ]
                }
            )
    return merge_payloads(period, payloads, tasks)


def build_payload(period: str, stores: list[str], limit: int | None, *, quiet: bool = False, workers: int = 1) -> dict[str, Any]:
    helpers = require_helpers()
    tasks = filter_tasks(load_meituan_tasks(period), stores)
    if limit is not None:
        tasks = tasks[:limit]
    if workers > 1 and len(tasks) > 1:
        return build_payload_parallel(period, tasks, workers, quiet=quiet)

    direct_accounts = helpers["load_direct_meituan_accounts"]()
    base_url = helpers["recent_meituan_promo_url"]() or HEADQUARTERS_HOME_URL

    results: list[dict[str, Any]] = []
    with helpers["sync_playwright"]() as playwright:
        contexts: dict[str, Any] = {}
        launched_contexts: list[Any] = []
        try:
            for task in tasks:
                if not quiet:
                    print(f"读取美团推广消耗：{task.get('keyword') or task.get('store')}", flush=True)
                record = query_task(task, helpers, playwright, contexts, launched_contexts, base_url, direct_accounts)
                if should_retry_query(record):
                    if not quiet:
                        print(f"重试美团推广消耗：{task.get('keyword') or task.get('store')}", flush=True)
                    time.sleep(3)
                    retry_record = query_task(task, helpers, playwright, contexts, launched_contexts, base_url, direct_accounts)
                    retry_record["retry_after"] = {
                        "failure_type": record.get("failure_type") or "",
                        "error": compact_error_message(str(record.get("error") or "")),
                    }
                    record = retry_record
                results.append(record)
        finally:
            for context in launched_contexts:
                try:
                    context.close()
                except Exception:
                    pass

    return payload_from_results(period, results)


def payload_from_results(period: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    ok_items = [item for item in results if item.get("ok")]
    failed_items = [item for item in results if not item.get("ok")]
    total = sum(float(item.get("today_spend") or 0) for item in ok_items if item.get("today_spend") is not None)
    elapsed = sum(float(item.get("elapsed_seconds") or 0) for item in results)
    return {
        "generated_at": now_text(),
        "status": "ok" if ok_items and not failed_items else "partial" if ok_items else "failed",
        "period": period,
        "summary": {
            "store_count": len(results),
            "success_count": len(ok_items),
            "failed_count": len(failed_items),
            "today_spend_total": round(total, 2),
            "elapsed_seconds_total": round(elapsed, 2),
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


def inspect_level(item: dict[str, Any]) -> tuple[str, str]:
    if not item.get("ok"):
        return "未核实", compact_error_message(str(item.get("error") or "没有读到页面数据"))
    percent = item.get("budget_percent")
    source = str(item.get("source") or "")
    if source == "budget_exhausted" or (percent is not None and float(percent) >= 100):
        return "已耗尽", "预算已耗尽"
    if percent is not None and float(percent) >= 90:
        return "预警", f"已消耗预算 {float(percent):.0f}%"
    if item.get("today_spend") in (0, 0.0):
        return "预警", "今日消耗为 0，需确认是否本应投放"
    return "正常", ""


def compact_error_message(message: str) -> str:
    text = normalize_space(message)
    if "安全验证" in text or "verify.meituan.com" in text:
        return "美团触发安全验证，需要先在 Mac mini 完成验证后重试"
    if "没有找到“全部门店”选择器" in text or "没有找到\"全部门店\"选择器" in text:
        return "总部账号门店选择器未出现，未能切换门店"
    if "backdrop" in text or "intercepts pointer events" in text:
        return "页面弹出遮罩层挡住门店选择器，未能切换门店"
    if "缺少 Playwright" in text or "No module named 'playwright'" in text:
        return "Mac mini 浏览器自动化环境缺少 Playwright"
    if "没有解析到推广花费" in text:
        return "页面已打开，但没有解析到推广花费"
    first = text.split("Call log:", 1)[0].strip()
    first = re.sub(r"https?://\S+", "[链接已省略]", first)
    first = re.sub(r"当前URL[:：]\s*\[链接已省略\]", "当前页面链接已省略", first)
    return (first or text)[:180]


def format_item_line(index: int, item: dict[str, Any]) -> str:
    keyword = item_display_name(item)
    level, reason = inspect_level(item)
    if not item.get("ok"):
        return f"{index}. {keyword}：{level}。原因：{reason}"

    parts = [f"{index}. {keyword}：{level}，今日消耗 {money(item.get('today_spend'))} 元"]
    if item.get("budget") is not None:
        parts.append(f"当前预算 {money(item.get('budget'))} 元")
    if item.get("remaining_budget") is not None:
        parts.append(f"剩余 {money(item.get('remaining_budget'))} 元")
    if item.get("budget_percent") is not None:
        parts.append(f"使用率 {float(item.get('budget_percent')):.0f}%")
    if item.get("updated_at_hint"):
        parts.append(f"页面更新时间 {item.get('updated_at_hint')}")
    if reason:
        parts.append(reason)
    return "，".join(parts) + "。"


def compact_store_name(value: str, *, width: int = 6) -> str:
    text = normalize_space(value)
    return text if len(text) <= width else text[: max(1, width - 1)] + "…"


def table_cell(value: Any, width: int, *, align: str = "left") -> str:
    text = normalize_space(str(value if value is not None else ""))
    if len(text) > width:
        text = text[: max(1, width - 1)] + "…"
    pad = width - len(text)
    if align == "right":
        return " " * pad + text
    return text + " " * pad


def format_item_table(items: list[dict[str, Any]]) -> list[str]:
    lines = [
        "```",
        "门店   状态   消耗   预算   剩余   用量  更新时间/原因",
        "----   ----   ----   ----   ----   ----  ------------",
    ]
    for item in items:
        level, reason = inspect_level(item)
        store = compact_store_name(item_display_name(item), width=5)
        spend = money(item.get("today_spend")) if item.get("ok") else "-"
        budget = money(item.get("budget")) if item.get("ok") and item.get("budget") is not None else "-"
        remaining = money(item.get("remaining_budget")) if item.get("ok") and item.get("remaining_budget") is not None else "-"
        percent = f"{float(item.get('budget_percent')):.0f}%" if item.get("ok") and item.get("budget_percent") is not None else "-"
        note = item.get("updated_at_hint") or reason or "-"
        lines.append(
            " ".join(
                [
                    table_cell(store, 5),
                    table_cell(level, 4),
                    table_cell(spend, 6, align="right"),
                    table_cell(budget, 6, align="right"),
                    table_cell(remaining, 6, align="right"),
                    table_cell(percent, 5, align="right"),
                    normalize_space(str(note)),
                ]
            )
        )
    lines.append("```")
    return lines


def format_human(items: list[dict[str, Any]]) -> str:
    ok_items = [item for item in items if item.get("ok")]
    total = sum(float(item.get("today_spend") or 0) for item in ok_items if item.get("today_spend") is not None)
    budget_total = sum(float(item.get("budget") or 0) for item in ok_items if item.get("budget") is not None)
    remaining_total = sum(float(item.get("remaining_budget") or 0) for item in ok_items if item.get("remaining_budget") is not None)
    level_counts = {"正常": 0, "预警": 0, "已耗尽": 0, "未核实": 0}
    for item in items:
        level, _ = inspect_level(item)
        level_counts[level] = level_counts.get(level, 0) + 1
    lines = [
        "美团推广实时消耗巡检：",
        (
            f"总览：已读到 {len(ok_items)}/{len(items)} 家，今日消耗 {money(total)} 元，"
            f"当前预算 {money(budget_total)} 元，剩余 {money(remaining_total)} 元；"
            f"正常 {level_counts.get('正常', 0)}，预警 {level_counts.get('预警', 0)}，"
            f"已耗尽 {level_counts.get('已耗尽', 0)}，未核实 {level_counts.get('未核实', 0)}。"
        ),
    ]
    lines.extend(format_item_table(items))
    if level_counts.get("已耗尽") or level_counts.get("预警") or level_counts.get("未核实"):
        lines.append("建议：先人工复核已耗尽/预警/未核实门店；本巡检只读，不会修改预算、出价或投放开关。")
    else:
        lines.append("建议：当前只读巡检未发现预算耗尽、预警或未核实门店；不需要自动修复。")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="只读查询美团点金推广消耗。")
    parser.add_argument("--period", choices=["lunch", "dinner", "all"], default="lunch", help="读取哪组美团门店配置；默认午餐门店。")
    parser.add_argument("--stores", default="", help="只查指定门店/关键词，逗号分隔。")
    parser.add_argument("--limit", type=int, default=0, help="调试用：最多读取多少家；0 表示不限制。")
    parser.add_argument("--workers", type=int, default=int(os.environ.get("MEITUAN_SPEND_WORKERS", "4")), help="并发读取 worker 数；1 表示串行。")
    parser.add_argument("--no-write-latest", action="store_true", help="子进程使用：不写 latest.json。")
    parser.add_argument("--json", action="store_true", help="输出 JSON。")
    parser.add_argument("--quiet", action="store_true", help="只输出最终结果，不输出逐店进度。")
    args = parser.parse_args(argv)
    stores = [item.strip() for item in args.stores.split(",") if item.strip()]
    payload = build_payload(args.period, stores, args.limit or None, quiet=args.quiet, workers=max(1, args.workers))
    if not args.no_write_latest:
        write_latest(payload)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(payload["message"])
    return 0 if payload["status"] == "ok" else 2 if payload["status"] == "partial" else 1


if __name__ == "__main__":
    raise SystemExit(main())
