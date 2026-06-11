from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent
CONFIG_PATH = ROOT / "config.json"
LATEST_JSON = ROOT / "latest.json"
LATEST_DATA_JS = ROOT / "latest-data.js"
OUTPUT_DIR = WORKSPACE / "outputs" / "store_inspection"
STORE_CHROME_CONFIG = ROOT / "chrome_config.json"
BUSINESS_CHROME_CONFIG = WORKSPACE / "business-report-dashboard" / "chrome_cdp_config.json"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def debug_url(chrome_config: dict) -> str:
    return f"http://127.0.0.1:{int(chrome_config['chrome']['debug_port'])}"


def cdp_available(chrome_config: dict) -> bool:
    try:
        with urlopen(f"{debug_url(chrome_config)}/json/version", timeout=2) as response:
            return response.status == 200
    except URLError:
        return False
    except Exception:
        return False


def ensure_cdp_page_target(chrome_config: dict) -> None:
    try:
        request = Request(f"{debug_url(chrome_config)}/json/new?about:blank", method="PUT")
        with urlopen(request, timeout=5):
            pass
    except Exception:
        pass


def start_chrome(chrome_config: dict) -> None:
    if cdp_available(chrome_config):
        return
    if chrome_config.get("chrome", {}).get("daily_chrome"):
        raise RuntimeError(
            "日常 Chrome 可以打开余额页，但新版 Chrome 不对默认日常资料夹开放脚本读取端口。"
            "自动巡检需要改用 Chrome 插件读取方案。"
        )
    starter = WORKSPACE / "business-report-dashboard" / "start_common_chrome.command"
    if starter.exists():
        subprocess.Popen(["/bin/zsh", str(starter)])
    deadline = time.time() + 25
    while time.time() < deadline:
        if cdp_available(chrome_config):
            return
        time.sleep(0.5)
    raise RuntimeError("没有连上用于自动巡检的 Chrome。请先确认用于自动化的 Chrome 已打开，并且已登录饿了么余额页。")


def connect_browser(chrome_config: dict):
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError as exc:
        raise RuntimeError("缺少 Playwright，无法执行线上巡检。") from exc

    start_chrome(chrome_config)
    ensure_cdp_page_target(chrome_config)
    playwright = sync_playwright().start()
    try:
        browser = playwright.chromium.connect_over_cdp(debug_url(chrome_config))
    except Exception:
        playwright.stop()
        raise
    return playwright, browser


def first_context(browser):
    if browser.contexts:
        return browser.contexts[0]
    return browser.new_context(accept_downloads=True)


def money_to_float(value: str) -> float | None:
    cleaned = value.replace(",", "").replace("¥", "").replace("元", "").strip()
    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    if not match:
        return None
    return float(match.group(0))


def normalize_space(value: object) -> str:
    return re.sub(r"\s+", " ", "" if value is None else str(value)).strip()


def row_to_item(row: list[str]) -> dict | None:
    joined = " ".join(row)
    if "POKEBEAR" not in joined and "熊小小" not in joined:
        return None
    if len(row) < 5:
        return None

    store_index = next((index for index, value in enumerate(row) if "POKEBEAR" in value or "熊小小" in value), -1)
    if store_index < 0:
        return None

    store_name = normalize_space(row[store_index])
    store_id = ""
    for value in row[store_index + 1 :]:
        if re.fullmatch(r"\d{6,}", normalize_space(value)):
            store_id = normalize_space(value)
            break

    balance = None
    for value in reversed(row):
        amount = money_to_float(value)
        if amount is not None:
            balance = amount
            break
    if balance is None:
        return None

    date_text = row[0] if row else ""
    return {
        "platform": "饿了么",
        "store_name": store_name,
        "store_id": store_id,
        "balance": balance,
        "source_date": date_text,
        "source": "自动巡检",
    }


def find_balance_frame(page, timeout_seconds: int = 45):
    deadline = time.time() + timeout_seconds
    keywords = ["立即充值", "分店账户余额", "分店消费记录", "账户详情", "余额(元)", "余额（元）"]
    while time.time() < deadline:
        for frame in page.frames:
            try:
                body = frame.locator("body").inner_text(timeout=2_000)
            except Exception:
                continue
            if any(keyword in body for keyword in keywords):
                return frame
        page.wait_for_timeout(1000)
    raise RuntimeError("没有在饿了么页面找到余额表。请先用日常 Chrome 确认账号能打开余额页；自动巡检还需要单独配置可读取的 Chrome 环境。")


def click_if_visible(frame, text: str, timeout_ms: int = 3_000) -> bool:
    try:
        locator = frame.get_by_text(text, exact=True)
        if locator.count() > 0:
            locator.first.click(timeout=timeout_ms)
            frame.page.wait_for_timeout(800)
            return True
    except Exception:
        return False
    return False


def click_text_by_dom(frame, text: str) -> bool:
    return bool(
        frame.evaluate(
            """(targetText) => {
              const visible = (element) => {
                const style = window.getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
              };
              const candidates = Array.from(document.querySelectorAll('button,a,span,div,li'))
                .filter((element) => visible(element) && (element.innerText || element.textContent || '').trim().includes(targetText))
                .sort((a, b) => {
                  const ar = a.getBoundingClientRect();
                  const br = b.getBoundingClientRect();
                  return (ar.width * ar.height) - (br.width * br.height);
                });
              const target = candidates[0];
              if (!target) return false;
              const clickable = target.closest('button,a,li') || target;
              clickable.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window }));
              clickable.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window }));
              clickable.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
              return true;
            }""",
            text,
        )
    )


def wait_until_frame_has(page, texts: list[str], timeout_seconds: int = 20):
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        for frame in page.frames:
            try:
                body = frame.locator("body").inner_text(timeout=1_500)
            except Exception:
                continue
            if all(text in body for text in texts):
                return frame
        page.wait_for_timeout(700)
    raise RuntimeError(f"页面没有进入预期步骤：{' / '.join(texts)}")


def enter_eleme_branch_account(page):
    frame = find_balance_frame(page)
    clicked = click_if_visible(frame, "立即充值", timeout_ms=6_000)
    if not clicked:
        clicked = click_text_by_dom(frame, "立即充值")
        page.wait_for_timeout(1000)
    if not clicked:
        body = frame.locator("body").inner_text(timeout=3_000)
        if "分店账户" not in body:
            raise RuntimeError("没有找到“立即充值”按钮。请确认饿了么页面已进入品牌商推广服务平台首页。")

    frame = wait_until_frame_has(page, ["分店账户"], timeout_seconds=20)
    clicked = click_if_visible(frame, "分店账户", timeout_ms=6_000)
    if not clicked:
        clicked = click_text_by_dom(frame, "分店账户")
        page.wait_for_timeout(1000)
    if not clicked:
        raise RuntimeError("没有找到“分店账户”入口。请确认点击立即充值后页面正常打开。")

    return wait_until_frame_has(page, ["余额"], timeout_seconds=25)


def extract_visible_rows(frame) -> list[list[str]]:
    return frame.evaluate(
        """() => {
          const visible = (element) => {
            const style = window.getComputedStyle(element);
            const rect = element.getBoundingClientRect();
            return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
          };
          const tableRows = Array.from(document.querySelectorAll('tr'))
            .map((tr) => Array.from(tr.querySelectorAll('th,td')).map((cell) => (cell.innerText || cell.textContent || '').trim()).filter(Boolean))
            .filter((row) => row.length);
          if (tableRows.length) return tableRows;

          const roleRows = Array.from(document.querySelectorAll('[role="row"]'))
            .filter(visible)
            .map((row) => Array.from(row.querySelectorAll('[role="cell"],[role="gridcell"],div,span'))
              .filter(visible)
              .map((cell) => (cell.innerText || cell.textContent || '').trim())
              .filter(Boolean))
            .filter((row) => row.length);
          return roleRows;
        }"""
    )


def scroll_table(frame) -> bool:
    return bool(
        frame.evaluate(
            """() => {
              const candidates = Array.from(document.querySelectorAll('.ant-table-body, .el-table__body-wrapper, [class*="table"][class*="body"], main, body'));
              const scrollable = candidates.find((element) => element.scrollHeight > element.clientHeight + 20);
              if (!scrollable) return false;
              const before = scrollable.scrollTop;
              scrollable.scrollTop = Math.min(scrollable.scrollTop + Math.max(320, scrollable.clientHeight * 0.75), scrollable.scrollHeight);
              return scrollable.scrollTop !== before;
            }"""
        )
    )


def extract_eleme_balances(page, balance_url: str, threshold: float) -> list[dict]:
    page.goto(balance_url, wait_until="domcontentloaded", timeout=90_000)
    page.wait_for_timeout(6000)
    frame = enter_eleme_branch_account(page)
    click_if_visible(frame, "分店消费记录")

    items_by_store: dict[str, dict] = {}
    stable_rounds = 0
    last_count = 0
    for _ in range(18):
        rows = extract_visible_rows(frame)
        for row in rows:
            item = row_to_item(row)
            if not item:
                continue
            key = item["store_id"] or item["store_name"]
            if key not in items_by_store:
                items_by_store[key] = item
        if len(items_by_store) == last_count:
            stable_rounds += 1
        else:
            stable_rounds = 0
            last_count = len(items_by_store)
        if stable_rounds >= 2:
            break
        if not scroll_table(frame):
            break
        page.wait_for_timeout(700)

    items = list(items_by_store.values())
    for item in items:
        item["status"] = "warning" if float(item["balance"]) < threshold else "normal"
    items.sort(key=lambda item: (item["status"] != "warning", float(item["balance"]), item["store_name"]))
    return items


def build_result(items: list[dict], threshold: float, status: str = "ok", message: str = "") -> dict:
    warning_count = sum(1 for item in items if item.get("status") == "warning")
    lowest = min((float(item["balance"]) for item in items), default=0.0)
    platforms = sorted({item["platform"] for item in items})
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": status,
        "message": message,
        "threshold": threshold,
        "summary": {
            "platform_count": len(platforms) if platforms else 1,
            "store_count": len(items),
            "warning_count": warning_count,
            "lowest_balance": round(lowest, 2),
        },
        "items": items,
    }


def write_latest_data_js(data: dict) -> None:
    content = "window.INSPECTION_DATA = "
    content += json.dumps(data, ensure_ascii=False, indent=2)
    content += ";\n"
    LATEST_DATA_JS.write_text(content, encoding="utf-8")


def run_once() -> dict:
    config = load_json(CONFIG_PATH)
    chrome_config = load_json(STORE_CHROME_CONFIG if STORE_CHROME_CONFIG.exists() else BUSINESS_CHROME_CONFIG)
    threshold = float(config["rules"]["promotion_balance_warning"])
    balance_url = config["platforms"]["eleme"]["balance_url"]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    playwright, browser = connect_browser(chrome_config)
    try:
        context = first_context(browser)
        page = context.new_page()
        items = extract_eleme_balances(page, balance_url, threshold)
        if not items:
            raise RuntimeError("饿了么余额页没有识别到任何门店余额。")
        data = build_result(items, threshold)
    except Exception as exc:
        data = build_result([], threshold, status="failed", message=str(exc))
        raise
    finally:
        try:
            browser.close()
        finally:
            playwright.stop()

    write_json(LATEST_JSON, data)
    write_latest_data_js(data)
    snapshot = OUTPUT_DIR / f"promo_balance_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    write_json(snapshot, data)
    return data


def open_eleme_balance_page() -> None:
    config = load_json(CONFIG_PATH)
    chrome_config = load_json(STORE_CHROME_CONFIG if STORE_CHROME_CONFIG.exists() else BUSINESS_CHROME_CONFIG)
    balance_url = config["platforms"]["eleme"]["balance_url"]
    playwright, browser = connect_browser(chrome_config)
    try:
        context = first_context(browser)
        page = context.new_page()
        page.goto(balance_url, wait_until="domcontentloaded", timeout=90_000)
        print(f"已打开饿了么余额页：{page.url}")
        print("请在弹出的自动化 Chrome 中确认已登录，并能看到“账户详情/分店消费记录”。")
    finally:
        browser.close()
        playwright.stop()


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "open-login":
        try:
            open_eleme_balance_page()
            return 0
        except Exception as exc:
            print(f"打开登录页失败：{exc}", file=sys.stderr)
            return 1

    try:
        data = run_once()
    except Exception as exc:
        config = load_json(CONFIG_PATH)
        threshold = float(config["rules"]["promotion_balance_warning"])
        data = build_result([], threshold, status="failed", message=str(exc))
        write_json(LATEST_JSON, data)
        write_latest_data_js(data)
        print(f"巡检失败：{exc}", file=sys.stderr)
        return 1

    summary = data["summary"]
    print(
        f"巡检完成：{summary['store_count']} 家门店，"
        f"{summary['warning_count']} 家低于 {data['threshold']:.0f} 元。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
