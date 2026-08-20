from __future__ import annotations

import json
import math
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from parse_balance_ocr import build_result
from balance_coverage import apply_direct_coverage


ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent
REPORT_DIR = WORKSPACE / "business-report-dashboard"
OUTPUT_JSON = ROOT / "eleme-cdp-latest.json"
OUTPUT_DATA_JS = ROOT / "eleme-cdp-latest-data.js"
ELEME_BALANCE_URL = "https://melody.shop.ele.me/app/unit/vas__account#app.unit.vas.account"
ELEME_ACCOUNT_FRAME_KEY = "__path__=accountChain"
BALANCE_API_KEY = "IGwShopInfoService.listLeafShopInfoPage"
THRESHOLD = 200.0
WORKING_NODE = "/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
if Path(WORKING_NODE).exists():
    os.environ.setdefault("PLAYWRIGHT_NODEJS_PATH", WORKING_NODE)

if str(REPORT_DIR) not in sys.path:
    sys.path.insert(0, str(REPORT_DIR))

import chrome_cdp_reports as cdp  # noqa: E402


def yuan_from_cents(value) -> float:
    try:
        return round(float(value) / 100, 2)
    except (TypeError, ValueError):
        return 0.0


def parse_shop_rows(payload: dict) -> list[dict]:
    rows = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    items = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ad_balance = row.get("adBalance") if isinstance(row.get("adBalance"), dict) else {}
        detail = ad_balance.get("detail") if isinstance(ad_balance.get("detail"), dict) else {}
        balance_cents = detail.get("balance")
        if balance_cents is None:
            balance_cents = ad_balance.get("balance")
        store_name = str(row.get("shopName") or "").strip()
        if not store_name:
            continue
        shop_id = row.get("shopId") or detail.get("shopId") or ""
        balance = yuan_from_cents(balance_cents)
        items.append(
            {
                "platform": "饿了么",
                "store_name": store_name,
                "store_id": str(shop_id),
                "balance": balance,
                "status": "warning" if balance < THRESHOLD else "normal",
                "source": "Chrome CDP接口读取",
            }
        )
    return items


def parse_dom_balance_rows(rows: list[dict]) -> list[dict]:
    items = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        store_name = str(row.get("shopName") or "").strip()
        if not store_name:
            continue
        balance = row.get("balance")
        try:
            balance_float = round(float(str(balance).replace(",", "")), 2)
        except (TypeError, ValueError):
            continue
        items.append(
            {
                "platform": "饿了么",
                "store_name": store_name,
                "store_id": str(row.get("shopId") or ""),
                "balance": balance_float,
                "status": "warning" if balance_float < THRESHOLD else "normal",
                "source": "Chrome CDP页面表格读取",
            }
        )
    return items


def collect_dom_balance_rows(page) -> list[dict]:
    return page.evaluate(
        """
        () => {
          const visible = (el) => {
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return rect.width > 0 && rect.height > 0
              && style.visibility !== "hidden"
              && style.display !== "none";
          };
          const textOf = (el) => (el?.innerText || el?.textContent || "").trim();
          const rows = Array.from(document.querySelectorAll("tbody tr,.ant-table-row"))
            .filter(visible)
            .map((tr) => {
              const cells = Array.from(tr.querySelectorAll("td,.ant-table-cell")).map(textOf);
              if (cells.length < 4) return null;
              const joined = cells.join("\\n");
              const idMatch = joined.match(/\\b\\d{6,}\\b/);
              const balanceCell = cells.find((cell, index) =>
                index >= 2 && /^\\d+(?:,\\d{3})*(?:\\.\\d+)?$/.test(cell.replace(/\\s/g, ""))
              );
              const nameCell = cells.find((cell) => /POKE|熊小小|牛排饭/i.test(cell));
              return {
                shopId: idMatch ? idMatch[0] : (cells[0] || ""),
                shopName: nameCell || cells[1] || "",
                balance: balanceCell ? balanceCell.replace(/\\s/g, "") : "",
              };
            })
            .filter(Boolean);
          return rows;
        }
        """
    )


def find_account_frame(page, timeout_seconds: int = 30):
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        for frame in page.frames:
            if ELEME_ACCOUNT_FRAME_KEY in frame.url:
                return frame
        page.wait_for_timeout(500)
    raise RuntimeError("饿了么新推广资金页没有加载账户明细区域。")


def click_exact_text(frame, text: str) -> bool:
    locator = frame.get_by_text(text, exact=True)
    if locator.count() < 1:
        return False
    locator.first.evaluate(
        "(element) => (element.closest('label,button,a,li') || element).click()"
    )
    frame.page.wait_for_timeout(800)
    return True


def wait_for_frame_text(frame, text: str, timeout_seconds: int = 15) -> str:
    deadline = time.time() + timeout_seconds
    body = ""
    while time.time() < deadline:
        body = frame.locator("body").inner_text(timeout=10_000)
        if text in body:
            return body
        frame.page.wait_for_timeout(500)
    return body


def open_leaf_balance_detail(page):
    """Open the new unit-account leaf balance table without changing any funds."""
    frame = find_account_frame(page)

    # The platform can show a one-time account-upgrade explanation over the tabs.
    try:
        click_exact_text(frame, "知道了")
    except Exception:
        pass

    body = frame.locator("body").inner_text(timeout=10_000)
    if "分店账户明细及转账" in body:
        return frame

    if "分店账户" in body:
        click_exact_text(frame, "分店账户")
        body = wait_for_frame_text(frame, "账户明细及转账")

    if "账户明细及转账" not in body:
        raise RuntimeError("饿了么推广资金页没有显示“账户明细及转账”入口。")

    click_exact_text(frame, "账户明细及转账")
    deadline = time.time() + 20
    while time.time() < deadline:
        body = frame.locator("body").inner_text(timeout=10_000)
        if "分店账户明细及转账" in body:
            return frame
        page.wait_for_timeout(500)
    raise RuntimeError("饿了么推广资金页未进入分店账户明细。")


def collect_balance_payload(timeout_seconds: int = 60) -> tuple[dict | None, str]:
    config = cdp.load_config()
    playwright, browser = cdp.connect_browser(config)
    response_payloads: list[dict] = []
    response_url = ""
    dom_rows: list[dict] = []
    try:
        context = cdp.first_context(browser)
        page = cdp.reusable_page(context)

        def handle_response(response):
            nonlocal response_url
            if BALANCE_API_KEY not in response.url:
                return
            try:
                payload = response.json()
            except Exception:
                return
            if isinstance(payload, dict) and isinstance(payload.get("result"), list):
                response_payloads.append(payload)
                response_url = response.url

        def wait_for_response_count(count: int, seconds: int = 20) -> bool:
            deadline = time.time() + seconds
            while time.time() < deadline:
                if len(response_payloads) >= count:
                    return True
                page.wait_for_timeout(500)
            return len(response_payloads) >= count

        def click_page_number(surface, page_number: int) -> bool:
            return bool(
                surface.evaluate(
                    """
                    (pageNumber) => {
                      const label = String(pageNumber);
                      const visible = (el) => {
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        return rect.width > 0 && rect.height > 0
                          && style.visibility !== "hidden"
                          && style.display !== "none";
                      };
                      const candidates = Array.from(document.querySelectorAll("button,li,a,span,div"))
                        .filter((el) => visible(el) && (el.innerText || el.textContent || "").trim() === label)
                        .sort((a, b) => {
                          const ar = a.getBoundingClientRect();
                          const br = b.getBoundingClientRect();
                          return (ar.width * ar.height) - (br.width * br.height);
                        });
                      const item = candidates[0];
                      if (!item) return false;
                      item.scrollIntoView({ block: "center", inline: "center" });
                      const target = item.closest("button,li,a") || item;
                      target.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true, view: window }));
                      target.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true, view: window }));
                      target.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, view: window }));
                      return true;
                    }
                    """,
                    page_number,
                )
            )

        def merged_payload() -> dict | None:
            if not response_payloads:
                return None
            merged = dict(response_payloads[-1])
            rows_by_shop: dict[str, dict] = {}
            for payload in response_payloads:
                for row in payload.get("result") or []:
                    if not isinstance(row, dict):
                        continue
                    key = str(row.get("shopId") or row.get("shopName") or len(rows_by_shop))
                    rows_by_shop[key] = row
            merged["result"] = list(rows_by_shop.values())
            merged["totalCount"] = max(
                int(payload.get("totalCount") or 0)
                for payload in response_payloads
                if isinstance(payload, dict)
            )
            return merged

        page.on("response", handle_response)
        try:
            cdp.goto_backend_page(page, ELEME_BALANCE_URL, timeout=90_000)
            balance_frame = open_leaf_balance_detail(page)

            # The account table remembers its last pagination position. Always
            # return to page 1 so a patrol cannot silently start from page 2.
            before_first_page = len(response_payloads)
            if click_page_number(balance_frame, 1):
                wait_for_response_count(before_first_page + 1, seconds=5)

            deadline = time.time() + timeout_seconds
            while time.time() < deadline and not response_payloads:
                page.wait_for_timeout(1000)
                if not response_payloads:
                    try:
                        dom_rows = collect_dom_balance_rows(balance_frame)
                    except Exception:
                        dom_rows = []
                    if dom_rows:
                        rows_by_shop = {
                            str(row.get("shopId") or row.get("shopName") or index): row
                            for index, row in enumerate(dom_rows)
                        }
                        for page_number in range(2, 6):
                            if not click_page_number(balance_frame, page_number):
                                break
                            page.wait_for_timeout(1200)
                            try:
                                for row in collect_dom_balance_rows(balance_frame):
                                    key = str(row.get("shopId") or row.get("shopName") or len(rows_by_shop))
                                    rows_by_shop[key] = row
                            except Exception:
                                break
                        dom_rows = list(rows_by_shop.values())
                        break
            if response_payloads:
                total_count = int(response_payloads[0].get("totalCount") or len(response_payloads[0].get("result") or []))
                page_size = max(
                    1,
                    *(len(payload.get("result") or []) for payload in response_payloads),
                )
                total_pages = math.ceil(total_count / page_size)
                page.wait_for_timeout(2500)
                for page_number in range(2, total_pages + 1):
                    before = len(response_payloads)
                    if not click_page_number(balance_frame, page_number):
                        break
                    wait_for_response_count(before + 1)
                    page.wait_for_timeout(1000)
        finally:
            page.remove_listener("response", handle_response)
        payload = merged_payload()
        if payload:
            return payload, response_url
        if dom_rows:
            return {"result": dom_rows, "source": "dom_table"}, "dom_table"
        return None, response_url
    finally:
        cdp.disconnect_browser(playwright, browser)


def write_test_outputs(data: dict) -> None:
    OUTPUT_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUTPUT_DATA_JS.write_text(
        "window.ELEME_CDP_BALANCE_DATA = " + json.dumps(data, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8",
    )


def main() -> int:
    payload, response_url = collect_balance_payload()
    if (payload or {}).get("source") == "dom_table":
        items = parse_dom_balance_rows((payload or {}).get("result") or [])
    else:
        items = parse_shop_rows(payload or {})
    data = apply_direct_coverage(
        build_result(items, THRESHOLD, "CDP接口没有读取到饿了么门店余额。"),
        {"饿了么"},
    )
    data["source"] = "eleme_cdp_balance"
    data["response_url"] = response_url
    data["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    write_test_outputs(data)
    summary = data["summary"]
    print(
        f"饿了么 CDP 余额读取完成：{summary['store_count']} 家门店，"
        f"{summary['warning_count']} 家低于 {THRESHOLD:g} 元。"
    )
    print(f"测试输出：{OUTPUT_JSON}")
    return 0 if items else 1


if __name__ == "__main__":
    raise SystemExit(main())
