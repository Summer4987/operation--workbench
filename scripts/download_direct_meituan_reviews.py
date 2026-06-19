from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "direct_meituan_accounts.json"
REVIEW_DIR = ROOT / "business-report-dashboard" / "data" / "reviews" / "raw"
OUTPUT_DIR = ROOT / "outputs" / "direct_meituan_reviews"
WORKING_NODE = "/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
if Path(WORKING_NODE).exists():
    os.environ.setdefault("PLAYWRIGHT_NODEJS_PATH", WORKING_NODE)

sys.path.insert(0, str(ROOT / "business-report-dashboard"))
from chrome_cdp_reports import date_with_dashes  # noqa: E402
from check_direct_meituan_account import MAC_CHROME, load_account, resolve_browser_executable  # noqa: E402
from download_direct_meituan_daily import cdp_available  # noqa: E402


def require_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError:
        print("缺少 playwright。请先安装 business-report-dashboard/requirements.txt。")
        raise SystemExit(2)
    return sync_playwright


def yesterday_compact() -> str:
    return (date.today() - timedelta(days=1)).strftime("%Y%m%d")


def launch_context(playwright, account: dict, visible: bool, browser_executable: str | None):
    debug_port = account.get("debug_port")
    if debug_port and cdp_available(int(debug_port)):
        browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{int(debug_port)}")
        context = browser.contexts[0] if browser.contexts else browser.new_context(accept_downloads=False)
        return context, False

    profile_dir = Path(account["profile_dir"]).expanduser()
    profile_dir.mkdir(parents=True, exist_ok=True)
    executable_path = resolve_browser_executable(browser_executable)
    options = {
        "user_data_dir": str(profile_dir),
        "headless": not visible,
        "accept_downloads": False,
        "viewport": {"width": 1440, "height": 1000},
    }
    if executable_path:
        options["executable_path"] = executable_path
    return playwright.chromium.launch_persistent_context(**options), True


def normalize_review_item(item: dict, target_date: str, account: dict) -> dict:
    stores = account.get("stores") or []
    fallback_store = stores[0] if len(stores) == 1 else ""
    return {
        "评价时间": item.get("createTime") or target_date,
        "门店名称": item.get("poiName") or fallback_store,
        "综合评分": item.get("orderCommentScore") or item.get("commentScoreType") or "",
        "评价内容": item.get("cleanComment") if item.get("cleanComment") is not None else item.get("comment") or "",
        "用户昵称": item.get("userName") or "",
        "门店id": item.get("wmPoiId") or "",
        "味道评分": item.get("tasteScore") or item.get("foodCommentScore") or "",
        "包装评分": item.get("packagingScore") or "",
        "配送评分": item.get("deliveryCommentScore") or "",
        "评价id": item.get("id") or "",
    }


def click_next_page(page) -> bool:
    try:
        return bool(
            page.evaluate(
            """() => {
              const visible = (el) => {
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
              };
              const candidates = Array.from(document.querySelectorAll('button, a, li, span, div'))
                .filter(visible)
                .filter((el) => {
                  const text = (el.innerText || el.textContent || '').trim();
                  const aria = el.getAttribute('aria-label') || '';
                  const cls = String(el.className || '');
                  return text === '下一页' || text === '>' || aria.includes('下一页') || /next/i.test(cls);
                })
                .map((el) => el.closest('button, a, li') || el)
                .filter(visible)
                .filter((el) => !el.disabled && !String(el.className || '').includes('disabled'))
                .sort((a, b) => {
                  const ar = a.getBoundingClientRect();
                  const br = b.getBoundingClientRect();
                  return br.left - ar.left;
                });
              const target = candidates[0];
              if (!target) return false;
              target.scrollIntoView({ block: 'center', inline: 'center' });
              const rect = target.getBoundingClientRect();
              const init = { bubbles: true, cancelable: true, view: window, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 };
              target.dispatchEvent(new MouseEvent('mousedown', init));
              target.dispatchEvent(new MouseEvent('mouseup', init));
              target.dispatchEvent(new MouseEvent('click', init));
              if (typeof target.click === 'function') target.click();
              return true;
            }"""
            )
        )
    except Exception:
        return False


def click_review_list_tab(page) -> bool:
    try:
        page.get_by_text("外卖评价列表", exact=True).click(timeout=3000)
        return True
    except Exception:
        pass
    for frame in page.frames:
        if "userComment_gw" not in frame.url:
            continue
        try:
            frame.get_by_text("外卖评价列表", exact=True).click(timeout=3000)
            return True
        except Exception:
            pass
        try:
            element = frame.frame_element()
            box = element.bounding_box()
            if box:
                page.mouse.click(box["x"] + 462, box["y"] + 244)
                return True
        except Exception:
            pass
    try:
        # The Meituan review page is Flutter/canvas-based in some sessions, so
        # the tab text is not always exposed to the DOM accessibility tree.
        page.mouse.click(462, 244)
        return True
    except Exception:
        return False


def write_reviews_csv(account: dict, target_compact: str, rows: list[dict]) -> Path:
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    target = REVIEW_DIR / (
        f"直营美团评价_{account['id']}_{target_compact}_{target_compact}_"
        f"{datetime.now().strftime('%Y-%m-%d+%H_%M_%S')}.csv"
    )
    with target.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "评价时间",
                "门店名称",
                "综合评分",
                "评价内容",
                "用户昵称",
                "门店id",
                "味道评分",
                "包装评分",
                "配送评分",
                "评价id",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
    return target


def write_status(payload: dict) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_DIR / "latest.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def run(
    account_id: str,
    target_compact: str,
    visible: bool,
    wait_seconds: int,
    max_pages: int,
    browser_executable: str | None,
) -> Path:
    account = load_account(account_id)
    target_date = date_with_dashes(target_compact)
    page_url = (account.get("pages") or {}).get("reviews")
    if not page_url:
        raise RuntimeError(f"{account_id} 未配置 reviews 页面。")

    sync_playwright = require_playwright()
    with sync_playwright() as p:
        context, should_close_context = launch_context(p, account, visible, browser_executable)
        page = context.new_page()
        page.set_viewport_size({"width": 1440, "height": 1000})
        comment_pages: list[dict] = []
        api_urls: list[str] = []
        api_errors: list[str] = []

        def collect_comment_response(response) -> None:
            if "/gw/customer/comment/list" not in response.url:
                return
            api_urls.append(response.url)
            try:
                body = response.json()
            except Exception as exc:
                api_errors.append(str(exc))
                return
            data = body.get("data") if isinstance(body, dict) else None
            if isinstance(data, dict):
                comment_pages.append(data)

        page.on("response", collect_comment_response)
        rows: list[dict] = []
        seen_page_nums: set[int] = set()
        seen_review_ids: set[str] = set()
        processed_pages = 0
        try:
            page.goto(page_url, wait_until="domcontentloaded", timeout=90_000)
            page.wait_for_timeout(8000)
            click_review_list_tab(page)
            deadline = time.time() + wait_seconds
            while time.time() < deadline and processed_pages < max_pages:
                while comment_pages:
                    data = comment_pages.pop(0)
                    processed_pages += 1
                    page_num = int(data.get("pageNum") or processed_pages)
                    if page_num in seen_page_nums:
                        continue
                    seen_page_nums.add(page_num)
                    for item in data.get("list") or []:
                        if str(item.get("createTime") or "") != target_date:
                            continue
                        review_id = str(item.get("id") or "")
                        if review_id and review_id in seen_review_ids:
                            continue
                        if review_id:
                            seen_review_ids.add(review_id)
                        rows.append(normalize_review_item(item, target_date, account))

                if rows and processed_pages >= 2:
                    break
                if not click_next_page(page):
                    page.wait_for_timeout(1000)
                else:
                    page.wait_for_timeout(2500)
                if api_urls and not comment_pages and processed_pages >= 1 and not rows:
                    page.wait_for_timeout(1000)

            if not api_urls:
                body_text = ""
                try:
                    body_text = page.locator("body").inner_text(timeout=5000)
                except Exception:
                    pass
                blocking = [
                    text
                    for text in ["登录", "验证码", "安全验证", "手机验证码", "验证中心", "身份核实", "拖动滑块", "verify.meituan.com"]
                    if text in body_text or text in page.title() or text in page.url
                ]
                if blocking:
                    raise RuntimeError(f"直营美团评价页需要人工处理：{'、'.join(blocking)}")
                raise RuntimeError("直营美团评价页未捕获评论列表接口")

            target = write_reviews_csv(account, target_compact, rows)
            status = {
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "account_id": account_id,
                "account_name": account.get("name", account_id),
                "stores": account.get("stores") or [],
                "target_date": target_date,
                "status": "ok",
                "review_count": len(rows),
                "api_response_count": len(api_urls),
                "processed_page_count": processed_pages,
                "output": str(target),
                "api_errors": api_errors[-5:],
            }
            status_output = write_status(status)
            print(f"直营美团评价已采集：{target}，{target_date} 共 {len(rows)} 条；状态：{status_output}")
            return target
        except Exception as exc:
            write_status(
                {
                    "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "account_id": account_id,
                    "account_name": account.get("name", account_id),
                    "stores": account.get("stores") or [],
                    "target_date": target_date,
                    "status": "needs_manual"
                    if any(text in str(exc) for text in ["登录", "验证码", "安全验证", "验证中心", "身份核实", "拖动滑块", "verify.meituan.com"])
                    else "failed",
                    "review_count": 0,
                    "api_response_count": len(api_urls),
                    "processed_page_count": processed_pages,
                    "output": "",
                    "api_errors": api_errors[-5:],
                    "error": str(exc),
                }
            )
            raise
        finally:
            try:
                page.close()
            except Exception:
                pass
            if should_close_context:
                context.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="只读采集直营美团临时账号评价，写入直营/日报看板可识别的 CSV。")
    parser.add_argument("--account", default="direct_chaoyangmen", help="账号 ID。")
    parser.add_argument("--target-date", default=yesterday_compact(), help="评价日期，格式 YYYYMMDD；默认昨天。")
    parser.add_argument("--visible", action="store_true", help="显示浏览器窗口；默认 headless。")
    parser.add_argument("--wait-seconds", type=int, default=75, help="等待评价接口和翻页的秒数。")
    parser.add_argument("--max-pages", type=int, default=12, help="最多读取的评价分页数。")
    parser.add_argument("--browser-executable", default=str(MAC_CHROME) if MAC_CHROME.exists() else None, help="Chrome/Chromium 可执行文件。")
    args = parser.parse_args()
    run(args.account, args.target_date, args.visible, args.wait_seconds, args.max_pages, args.browser_executable)


if __name__ == "__main__":
    main()
