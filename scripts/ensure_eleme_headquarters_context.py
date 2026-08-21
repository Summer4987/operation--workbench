#!/usr/bin/env python3
"""Force Eleme's daily Chrome session back to the headquarters/all-store context."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "dianjin_automation"
LATEST_OUTPUT = OUTPUT_DIR / "eleme_headquarters_context_latest.json"
GROUP_ID = "93331264"
PIVOT_SHOP_ID = "524321320"
GROUP_CONTEXT_URL = (
    f"https://melody.shop.ele.me/app/chain/{GROUP_ID}/vas__bid#app.chainshop.vas.bid"
)
PROMOTION_URL = (
    "https://r.ele.me/doujin-isv-manage/index.html?__path__=eleCpcChain/oldBranch"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--debug-url",
        default=os.environ.get("ELEME_CDP_DEBUG_URL", "http://127.0.0.1:9222"),
    )
    parser.add_argument("--preview", required=True, help="预算执行预览 JSON")
    parser.add_argument("--wait-ms", type=int, default=5_000)
    parser.add_argument("--output", default=str(LATEST_OUTPUT))
    return parser.parse_args()


def expected_shop_ids(preview_path: Path) -> list[str]:
    payload = json.loads(preview_path.read_text(encoding="utf-8"))
    ids = {
        str(item.get("shopId") or "").strip()
        for item in payload.get("rows") or []
        if str(item.get("shopId") or "").strip()
    }
    if not ids:
        raise RuntimeError(f"预算预览没有 shopId：{preview_path}")
    return sorted(ids)


def visible_locator(locator):
    for index in range(locator.count()):
        candidate = locator.nth(index)
        if candidate.is_visible():
            return candidate
    return None


def open_switcher(page):
    switchers = page.locator('div[class*="shopSwitcher"]')
    switchers.first.wait_for(state="visible", timeout=45_000)
    switcher = visible_locator(switchers)
    if switcher is None:
        raise RuntimeError("饿了么总部页面没有显示门店切换器")
    switcher.click()
    page.wait_for_timeout(700)
    return switcher


def choose_context(page, value: str, expected_url_pattern: str) -> None:
    open_switcher(page)
    option = visible_locator(page.locator(f'li[data-value="{value}"]'))
    if option is None:
        raise RuntimeError(f"门店切换器没有找到上下文：{value}")
    option.click()
    page.wait_for_url(expected_url_pattern, timeout=30_000)
    page.wait_for_timeout(1_500)


def extract_shop_ids(page) -> set[str]:
    ids: set[str] = set()
    for text in page.locator("tbody tr").all_inner_texts():
        ids.update(re.findall(r"ID[：:]\s*(\d+)", text))
    return ids


def clear_store_search(page) -> None:
    candidates = page.locator('input[placeholder*="门店"], input[placeholder*="搜索"]')
    search = visible_locator(candidates)
    if search is None:
        return
    search.fill("")
    search.press("Enter")
    page.wait_for_timeout(1_500)


def collect_all_shop_ids(page) -> set[str]:
    clear_store_search(page)
    first_page_ids = extract_shop_ids(page)
    page_two = visible_locator(page.locator(".ant-pagination-item-2"))
    if page_two is None:
        return first_page_ids
    page_two.click()
    page.wait_for_timeout(2_000)
    second_page_ids = extract_shop_ids(page)
    page_one = visible_locator(page.locator(".ant-pagination-item-1"))
    if page_one is not None:
        page_one.click()
        page.wait_for_timeout(800)
    return first_page_ids | second_page_ids


def write_result(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    args = parse_args()
    output_path = Path(args.output)
    expected = expected_shop_ids(Path(args.preview))
    result: dict[str, Any] = {
        "ok": False,
        "checkedAt": datetime.now().astimezone().isoformat(),
        "debugUrl": args.debug_url,
        "expectedCount": len(expected),
        "expectedShopIds": expected,
    }
    helper = None
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(args.debug_url)
            if not browser.contexts:
                raise RuntimeError("日常 Chrome 没有可用浏览器上下文")
            context = browser.contexts[0]
            helper = context.new_page()
            helper.goto(GROUP_CONTEXT_URL, wait_until="domcontentloaded", timeout=90_000)
            helper.wait_for_timeout(args.wait_ms)

            # A no-op click on “全部” does not refresh Eleme's organization token.
            # Force a real transition through one store, then return to headquarters.
            choose_context(
                helper,
                f"{GROUP_ID}__RC_CASCADER_SPLIT__{PIVOT_SHOP_ID}",
                f"**/app/shop/{PIVOT_SHOP_ID}/**",
            )
            choose_context(
                helper,
                f"{GROUP_ID}__RC_CASCADER_SPLIT__{GROUP_ID}",
                f"**/app/chain/{GROUP_ID}/**",
            )

            promotion = next(
                (page for page in context.pages if "doujin-isv-manage/index.html" in page.url),
                None,
            )
            if promotion is None:
                promotion = context.new_page()
            promotion.goto(PROMOTION_URL, wait_until="domcontentloaded", timeout=90_000)
            promotion.wait_for_timeout(args.wait_ms)
            body = promotion.locator("body").inner_text()
            if "系统被限流" in body:
                raise RuntimeError("完成单店→全部校准后，旧批量页仍返回系统被限流")
            if "未登录" in body or "/login" in promotion.url:
                raise RuntimeError("完成总部上下文校准后，旧批量页显示未登录")

            actual = sorted(collect_all_shop_ids(promotion))
            missing = sorted(set(expected) - set(actual))
            if missing:
                raise RuntimeError(
                    f"旧批量页门店不完整：期望 {len(expected)} 家，实际匹配 "
                    f"{len(set(expected) & set(actual))} 家，缺少 {','.join(missing)}"
                )

            result.update(
                ok=True,
                actualCount=len(actual),
                actualShopIds=actual,
                missingShopIds=[],
                message=f"总部上下文校准成功，旧批量页已核对 {len(expected)} 家门店",
            )
            browser.close()
    except Exception as exc:
        result.update(error=str(exc))
    finally:
        if helper is not None:
            try:
                helper.close()
            except Exception:
                pass
        write_result(output_path, result)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 71


if __name__ == "__main__":
    sys.exit(main())
