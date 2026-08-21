#!/usr/bin/env python3
"""Set Eleme budgets through each store's promotion page.

This is the safe fallback for the legacy chain batch page.  It switches into one
store at a time, changes only that store, verifies the saved value, and continues
after an isolated store failure.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Frame, Page


ROOT = Path(__file__).resolve().parents[1]
PREVIEW_PATH = ROOT / "outputs" / "promo_budget_preview" / "latest.json"
OUTPUT_DIR = ROOT / "outputs" / "dianjin_automation"
UNIT_PROMOTION_URL = "https://melody.shop.ele.me/app/unit/vas__bid#app.unit.vas.bid"
CDP_URL = "http://127.0.0.1:9222"
COMPANY_NAME = "成都熊小小餐饮管理有限公司"


def parse_budget_text(text: str) -> int | None:
    match = re.search(r"每日预算.*?¥\s*([0-9,]+)", text, re.S)
    return int(match.group(1).replace(",", "")) if match else None


def select_rows(
    payload: dict[str, Any],
    time_point: str,
    store: str = "",
    stores: str = "",
    shop_id: str = "",
    limit: str = "all",
) -> list[dict[str, Any]]:
    source_key = "eleme_lunch" if time_point == "10:30" else "eleme_dinner"
    rows = [dict(row) for row in payload.get(source_key, []) if str(row.get("time")) == time_point]
    allowed_stores = {item.strip() for item in stores.split(",") if item.strip()}
    if store:
        rows = [row for row in rows if store in str(row.get("store") or "")]
    if allowed_stores:
        rows = [row for row in rows if str(row.get("store") or "") in allowed_stores]
    if shop_id:
        rows = [row for row in rows if str(row.get("shopId") or "") == str(shop_id)]
    if limit != "all":
        rows = rows[: max(0, int(limit))]
    return rows


async def connect_context() -> tuple[Any, BrowserContext]:
    from playwright.async_api import async_playwright

    playwright = await async_playwright().start()
    browser = await playwright.chromium.connect_over_cdp(CDP_URL)
    if not browser.contexts:
        await playwright.stop()
        raise RuntimeError("生产 Chrome 没有可用浏览器上下文")
    return playwright, browser.contexts[0]


async def page_text(page: Page) -> str:
    try:
        return await page.locator("body").inner_text(timeout=3_000)
    except Exception:
        return ""


async def find_store_dashboard(
    context: BrowserContext,
    shop_id: str,
    store: str,
    timeout_seconds: int = 25,
) -> tuple[Page, Frame]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        for page in reversed(context.pages):
            if f"/shop/{shop_id}/" not in page.url:
                continue
            text = await page_text(page)
            if store not in text or "无效店铺" in text:
                continue
            frames = [frame for frame in page.frames if "eleCpc/dashBoard" in frame.url]
            if frames:
                return page, frames[-1]
        await asyncio.sleep(1)
    raise RuntimeError(f"{store} 未进入单店斗金推广页")


async def prepare_store(shop_id: str, store: str) -> None:
    playwright, context = await connect_context()
    page = await context.new_page()
    await page.goto(UNIT_PROMOTION_URL, wait_until="domcontentloaded", timeout=60_000)
    await page.wait_for_timeout(5_000)
    company = page.get_by_text(COMPANY_NAME, exact=True)
    if not await company.count():
        raise RuntimeError("集团账号门店切换器未显示，可能登录已失效")
    await company.first.click()
    search = page.get_by_placeholder("搜索店铺名称/ID")
    await search.fill(store)
    await page.wait_for_timeout(1_200)
    item = page.locator(f'li[data-value="{shop_id}"]')
    if not await item.count():
        raise RuntimeError(f"门店切换器没有找到 {store}（{shop_id}）")
    await item.click()
    await page.wait_for_timeout(5_000)
    if f"/shop/{shop_id}/" not in page.url or store not in await page_text(page):
        raise RuntimeError(f"切换后未确认当前门店为 {store}（{shop_id}）")
    await page.get_by_text("店铺推广", exact=True).first.click()
    await page.wait_for_timeout(5_000)
    product_frame = None
    for _ in range(15):
        product_frame = next((frame for frame in page.frames if "elePcHome" in frame.url), None)
        if product_frame:
            break
        await asyncio.sleep(1)
    if product_frame is None:
        raise RuntimeError(f"{store} 店铺推广首页未加载")
    card = product_frame.locator(".bs-entry-card").filter(has_text="斗金推广")
    if not await card.count():
        raise RuntimeError(f"{store} 没有找到斗金推广入口")
    print(json.dumps({"phase": "prepared", "store": store, "shopId": shop_id}, ensure_ascii=False), flush=True)
    # The card replaces an embedded application target.  Dispatching the click
    # directly lets the parent orchestrator reconnect after that replacement.
    await card.first.evaluate("element => element.click()")
    await playwright.stop()


async def set_current_budget(shop_id: str, store: str, target: int, commit: bool) -> None:
    playwright, context = await connect_context()
    _, frame = await find_store_dashboard(context, shop_id, store)
    modal = frame.locator(".cook-modal.manualbudget-modal-container")
    if await modal.count() and await modal.first.is_visible():
        await modal.first.get_by_role("button", name="取消", exact=True).click()
        await frame.wait_for_timeout(500)
    body = await frame.locator("body").inner_text()
    current = parse_budget_text(body)
    if current is None:
        raise RuntimeError(f"{store} 当前页没有读到每日预算")
    if current == target or not commit:
        print(json.dumps({"phase": "set", "store": store, "shopId": shop_id, "current": current, "target": target, "saved": False}, ensure_ascii=False), flush=True)
        await playwright.stop()
        return
    section = frame.locator("section.base_set_item_container").filter(has_text="每日预算")
    if not await section.count():
        raise RuntimeError(f"{store} 没有找到每日预算设置入口")
    await section.first.click()
    modal = frame.locator(".cook-modal.manualbudget-modal-container")
    await modal.wait_for(state="visible", timeout=8_000)
    value_input = modal.locator("input.cook-input").first
    await value_input.fill(str(target))
    if await value_input.input_value() != str(target):
        raise RuntimeError(f"{store} 预算输入框未写入 {target}")
    await value_input.press("Tab")
    await frame.wait_for_timeout(800)
    confirm = modal.get_by_role("button", name="确定", exact=True)
    print(json.dumps({"phase": "set", "store": store, "shopId": shop_id, "current": current, "target": target, "saved": True}, ensure_ascii=False), flush=True)
    await confirm.click(no_wait_after=True)
    await frame.wait_for_timeout(1_000)
    await playwright.stop()


async def verify_current_budget(shop_id: str, store: str, target: int) -> dict[str, Any]:
    playwright, context = await connect_context()
    page, frame = await find_store_dashboard(context, shop_id, store)
    current = None
    for _ in range(20):
        current = parse_budget_text(await frame.locator("body").inner_text())
        if current == target:
            break
        await asyncio.sleep(1)
    result = {
        "ok": current == target,
        "store": store,
        "shopId": int(shop_id),
        "targetBudget": target,
        "verifiedBudget": current,
        "error": "" if current == target else f"保存后回读为 {current}，目标为 {target}",
    }
    await page.close()
    await playwright.stop()
    return result


def run_phase(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(Path(__file__).resolve()), *args], text=True, capture_output=True)


def run_all(args: argparse.Namespace) -> int:
    payload = json.loads(PREVIEW_PATH.read_text(encoding="utf-8"))
    rows = select_rows(payload, args.time, args.store, args.stores, args.shop_id, args.limit)
    if not rows:
        print("没有匹配的饿了么预算任务", file=sys.stderr)
        return 2
    if args.mode != "commit":
        result = {"ok": True, "mode": args.mode, "total": len(rows), "results": rows}
    else:
        results: list[dict[str, Any]] = []
        for row in rows:
            store = str(row["store"])
            shop_id = str(row["shopId"])
            target = int(row["targetBudget"])
            print(f"== {store}（{shop_id}）目标预算 {target} 元 ==", flush=True)
            prepare = run_phase("_prepare", "--shop-id", shop_id, "--store", store)
            if prepare.stdout:
                print(prepare.stdout.strip(), flush=True)
            if prepare.returncode != 0:
                error = (prepare.stderr or prepare.stdout or "单店页面准备失败").strip()
                results.append({"ok": False, "store": store, "shopId": int(shop_id), "targetBudget": target, "error": error})
                print(f"{store} 准备失败，已跳过并继续下一店：{error}", flush=True)
                continue
            time.sleep(8)
            setter = run_phase("_set", "--shop-id", shop_id, "--store", store, "--budget", str(target), "--commit")
            if setter.stdout:
                print(setter.stdout.strip(), flush=True)
            if setter.returncode != 0:
                error = (setter.stderr or setter.stdout or "预算提交失败").strip()
                results.append({"ok": False, "store": store, "shopId": int(shop_id), "targetBudget": target, "error": error})
                print(f"{store} 提交失败，已跳过并继续下一店：{error}", flush=True)
                continue
            time.sleep(5)
            verify = run_phase("_verify", "--shop-id", shop_id, "--store", store, "--budget", str(target))
            try:
                item = json.loads(verify.stdout.strip().splitlines()[-1])
            except Exception:
                error = (verify.stderr or verify.stdout or "预算回读失败").strip()
                item = {"ok": False, "store": store, "shopId": int(shop_id), "targetBudget": target, "error": error}
            results.append(item)
            print(f"{store}：{'成功' if item['ok'] else '失败'}，回读 {item.get('verifiedBudget')} 元", flush=True)
        result = {"ok": bool(results) and all(item.get("ok") for item in results), "mode": args.mode, "total": len(rows), "results": results}
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    output_path = OUTPUT_DIR / f"eleme_single_store_budget_{args.mode}_{stamp}.json"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"结果：{output_path}")
    print(f"任务数：{result['total']}，成功：{sum(1 for item in result['results'] if item.get('ok', args.mode != 'commit'))}，失败：{sum(1 for item in result['results'] if not item.get('ok', args.mode != 'commit'))}")
    return 0 if result["ok"] else 71


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", default="run", choices=("run", "_prepare", "_set", "_verify"))
    parser.add_argument("--time", choices=("10:30", "16:30"))
    parser.add_argument("--mode", choices=("preview", "rehearse", "commit"), default="preview")
    parser.add_argument("--limit", default="all")
    parser.add_argument("--store", default="")
    parser.add_argument("--stores", default="")
    parser.add_argument("--shop-id", default="")
    parser.add_argument("--budget", type=int)
    parser.add_argument("--commit", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "run":
        if not args.time:
            raise SystemExit("run 需要 --time")
        return run_all(args)
    if not args.shop_id or not args.store:
        raise SystemExit("内部阶段需要 --shop-id 和 --store")
    if args.command == "_prepare":
        asyncio.run(prepare_store(args.shop_id, args.store))
        return 0
    if args.budget is None:
        raise SystemExit("预算阶段需要 --budget")
    if args.command == "_set":
        asyncio.run(set_current_budget(args.shop_id, args.store, args.budget, args.commit))
        return 0
    result = asyncio.run(verify_current_budget(args.shop_id, args.store, args.budget))
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
