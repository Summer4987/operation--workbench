from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.error import URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "chrome_cdp_config.json"
ELEME_COMMENTS_URL = "https://melody.shop.ele.me/app/chain/93331264/comments#app.chainshop.comments"
MEITUAN_COMMENTS_URL = "https://e.waimai.meituan.com/#https://waimaieapp.meituan.com/frontweb/ffw/userComment_gw"
WORKING_NODE = "/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
if Path(WORKING_NODE).exists():
    os.environ.setdefault("PLAYWRIGHT_NODEJS_PATH", WORKING_NODE)


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def require_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError:
        print("缺少 playwright。请先运行 install_browser_automation.command。")
        raise SystemExit(2)
    return sync_playwright


def debug_url(config: dict) -> str:
    return f"http://127.0.0.1:{int(config['chrome']['debug_port'])}"


def cdp_available(config: dict) -> bool:
    try:
        with urlopen(f"{debug_url(config)}/json/version", timeout=2) as response:
            return response.status == 200
    except URLError:
        return False
    except Exception:
        return False


def cdp_page_targets(config: dict) -> list[dict]:
    try:
        with urlopen(f"{debug_url(config)}/json/list", timeout=2) as response:
            targets = json.loads(response.read().decode("utf-8"))
    except Exception:
        return []
    if not isinstance(targets, list):
        return []
    return [target for target in targets if target.get("type") == "page"]


def ensure_cdp_page_target(config: dict) -> None:
    if cdp_page_targets(config):
        return
    try:
        request = Request(f"{debug_url(config)}/json/new?about:blank", method="PUT")
        with urlopen(request, timeout=5):
            pass
    except Exception:
        pass


def start_chrome(*, wait_seconds: int = 90) -> bool:
    config = load_config()
    chrome = config["chrome"]
    if cdp_available(config):
        print(f"Chrome 调试端口已可用：{debug_url(config)}")
        return True

    executable = Path(chrome["executable"])
    if not executable.exists():
        raise FileNotFoundError(f"找不到 Chrome 可执行文件：{executable}")

    chrome_args = [
        f"--remote-debugging-port={int(chrome['debug_port'])}",
        f"--user-data-dir={chrome['user_data_dir']}",
        f"--profile-directory={chrome.get('profile_directory', 'Default')}",
        "--disable-breakpad",
        "--disable-crash-reporter",
        "--no-first-run",
        "--no-default-browser-check",
        "about:blank",
    ]
    args = [
        str(executable),
        *chrome_args,
    ]
    log_path = ROOT / "chrome-start.log"
    log_file = log_path.open("a", encoding="utf-8")
    log_file.write(f"\n--- start {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
    log_file.write(" ".join(args) + "\n")
    log_file.flush()
    subprocess.Popen(args, stdout=log_file, stderr=log_file)
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if cdp_available(config):
            print(f"Chrome 调试端口已启动：{debug_url(config)}")
            return True
        time.sleep(2)

    app_path = executable.parents[2] if len(executable.parents) >= 3 else executable
    open_args = ["open", "-na", str(app_path), "--args", *chrome_args]
    log_file.write(" ".join(open_args) + "\n")
    log_file.flush()
    subprocess.Popen(open_args, stdout=log_file, stderr=log_file)
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if cdp_available(config):
            print(f"Chrome 调试端口已启动：{debug_url(config)}")
            return True
        time.sleep(2)

    print("Chrome 已尝试启动，但调试端口还不可用。")
    print(f"当前使用的 Chrome 资料夹：{chrome['user_data_dir']}")
    print(f"启动日志：{log_path}")
    print("请确认 Chrome 是否已弹出；如果普通 Chrome 已经打开，请先完全退出 Chrome 后再试。")
    return False


def connect_browser(config: dict):
    if not cdp_available(config):
        print("正在启动常用 Chrome...")
        if not start_chrome():
            raise SystemExit(2)

    ensure_cdp_page_target(config)
    sync_playwright = require_playwright()
    playwright = sync_playwright().start()
    try:
        browser = playwright.chromium.connect_over_cdp(debug_url(config))
    except Exception:
        ensure_cdp_page_target(config)
        try:
            browser = playwright.chromium.connect_over_cdp(debug_url(config))
            return playwright, browser
        except Exception:
            pass
        playwright.stop()
        print("没有连上常用 Chrome。请先完全退出普通 Chrome，再重新双击桌面的一键采集。")
        raise SystemExit(2)
    return playwright, browser


def first_context(browser):
    if browser.contexts:
        return browser.contexts[0]
    return browser.new_context(accept_downloads=True)


def reusable_page(context):
    for page in context.pages:
        if not page.is_closed():
            return page
    return context.new_page()


def goto_backend_page(page, url: str, *, timeout: int = 90_000) -> None:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=timeout)
    except Exception as exc:
        if "net::ERR_ABORTED" not in str(exc):
            raise


def disconnect_browser(playwright, browser) -> None:
    # Keep the single debugging Chrome alive between steps; closing it here makes
    # the next report action launch another window.
    playwright.stop()


def status() -> None:
    config = load_config()
    print(f"调试地址：{debug_url(config)}")
    print(f"端口状态：{'可连接' if cdp_available(config) else '不可连接'}")
    print(f"Chrome 可执行文件：{config['chrome']['executable']}")
    print(f"用户数据目录：{config['chrome']['user_data_dir']}")


def open_pages() -> None:
    config = load_config()
    playwright, browser = connect_browser(config)
    try:
        context = first_context(browser)
        for platform in config["platforms"].values():
            page = reusable_page(context)
            page.goto(platform["entry_url"], wait_until="domcontentloaded", timeout=90_000)
            print(f"已打开 {platform['name']}：{page.url}")
        print("请确认页面正常登录。如果出现验证码或安全验证，请手动处理。")
    finally:
        disconnect_browser(playwright, browser)


def probe_pages() -> None:
    config = load_config()
    playwright, browser = connect_browser(config)
    try:
        context = first_context(browser)
        for key, platform in config["platforms"].items():
            page = reusable_page(context)
            goto_backend_page(page, platform["download_url"])
            page.wait_for_timeout(2500)
            title = page.title()
            body = page.locator("body").inner_text(timeout=10_000)[:2000]
            matched = [text for text in platform["ready_texts"] if text in body or text in title]
            print(f"\n{platform['name']}")
            print(f"URL: {page.url}")
            print(f"标题: {title}")
            print(f"页面识别: {' / '.join(matched) if matched else '未识别到配置关键词'}")
            if "login" in page.url.lower() or "登录" in body:
                print("登录状态: 未登录或已跳转登录页")
            else:
                print("登录状态: 未发现登录页跳转")
            if "验证码" in body or "安全" in body or "验证" in body:
                print("提示: 页面可能出现验证，请手动接管。")
    finally:
        disconnect_browser(playwright, browser)


def downloads_dir() -> Path:
    path = Path.home() / "Downloads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def newest_file_before(pattern: str) -> float:
    files = [path for path in downloads_dir().glob(pattern) if path.is_file()]
    if not files:
        return 0
    return max(path.stat().st_mtime for path in files)


def newest_file(pattern: str) -> Path | None:
    files = [path for path in downloads_dir().glob(pattern) if path.is_file()]
    if not files:
        return None
    return max(files, key=lambda path: path.stat().st_mtime)


def wait_for_newest_file(pattern: str, after: float, timeout_seconds: int = 30) -> Path | None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        path = newest_file(pattern)
        if path and path.stat().st_mtime > after:
            return path
        time.sleep(1)
    return None


def save_download_to_reviews(download, fallback_name: str | None = None) -> Path:
    review_dir = ROOT / "data" / "reviews" / "raw"
    review_dir.mkdir(parents=True, exist_ok=True)
    suggested = download.suggested_filename or fallback_name or f"评价下载_{int(time.time())}.xlsx"
    target = review_dir / suggested
    if target.exists():
        stem = target.stem
        suffix = target.suffix
        target = review_dir / f"{stem}_{int(time.time())}{suffix}"
    download.save_as(str(target))
    return target


def download_url_to_reviews(url: str, filename: str) -> Path:
    review_dir = ROOT / "data" / "reviews" / "raw"
    review_dir.mkdir(parents=True, exist_ok=True)
    target = review_dir / filename
    if target.exists():
        target = review_dir / f"{target.stem}_{int(time.time())}{target.suffix}"
    temporary = target.with_name(f"{target.name}.part")
    with urlopen(url, timeout=120) as response:
        data = response.read()
    if not data:
        raise RuntimeError("下载结果为空文件")
    if data.lstrip().startswith(b"<!DOCTYPE html") or data.lstrip().startswith(b"<html"):
        raise RuntimeError("下载结果是 HTML，不是评价文件")
    temporary.write_bytes(data)
    temporary.replace(target)
    return target


def eleme_request_id() -> str:
    return f"{uuid.uuid4().hex.upper()}|{int(time.time() * 1000)}"


def copy_existing_review_file(platform: str, target_compact: str, target_dashed: str) -> Path | None:
    review_dir = ROOT / "data" / "reviews" / "raw"
    local_candidates: list[Path] = []
    for directory in [review_dir, downloads_dir()]:
        if not directory.exists():
            continue
        for pattern in ("*评价*.xlsx", "*评价*.xls", "*评价*.csv", "*评论*.xlsx", "*评论*.xls", "*评论*.csv"):
            for path in directory.glob(pattern):
                if not path.is_file():
                    continue
                name = path.name
                if platform == "eleme" and ("美团" in name or name.startswith("评价_全部门店_")):
                    continue
                if platform == "meituan" and "美团" not in name and "外卖评价统计" not in name and not name.startswith("评价_全部门店_"):
                    continue
                local_candidates.append(path)
    def name_matches_target(path: Path) -> bool:
        name = path.name
        if target_compact in name or target_dashed in name:
            return True
        range_match = re.search(r"(\d{4}-\d{2}-\d{2})~(\d{4}-\d{2}-\d{2})", name)
        if range_match:
            return range_match.group(1) <= target_dashed <= range_match.group(2)
        return False

    for path in sorted(local_candidates, key=lambda item: item.stat().st_mtime, reverse=True):
        if not name_matches_target(path):
            continue
        if path.stat().st_size <= 128:
            continue
        review_dir.mkdir(parents=True, exist_ok=True)
        target = review_dir / path.name
        if path.resolve() != target.resolve() and not target.exists():
            shutil.copy2(path, target)
        return target
    return None


def click_any_text(page, texts: list[str], timeout: int = 30_000) -> str:
    last_error: Exception | None = None
    for text in texts:
        try:
            click_text(page, text, timeout=timeout)
            return text
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"没有找到这些入口：{'、'.join(texts)}；最后错误：{last_error}")


def click_any_text_in_page_or_frames(page, texts: list[str], timeout: int = 30_000) -> str:
    last_error: Exception | None = None
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        for target in [page, *page.frames]:
            for text in texts:
                try:
                    click_text(target, text, timeout=2_000)
                    return text
                except Exception as exc:
                    last_error = exc
        page.wait_for_timeout(500)
    raise RuntimeError(f"没有找到这些入口：{'、'.join(texts)}；最后错误：{last_error}")


def frame_or_page_with_any_text(page, texts: list[str], timeout_seconds: int = 30):
    deadline = time.time() + timeout_seconds
    last_seen = ""
    while time.time() < deadline:
        for target in [page, *page.frames]:
            try:
                body = target.locator("body").inner_text(timeout=2_000)
            except Exception:
                continue
            if body:
                last_seen = body[:500]
            if any(text in body for text in texts):
                return target
        page.wait_for_timeout(1000)
    raise RuntimeError(f"没有找到包含任一文本的页面：{texts}；最后看到：{last_seen}")


def click_text(page, text: str, timeout: int = 30_000) -> None:
    clicked = page.evaluate(
        """
        (targetText) => {
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const elements = Array.from(document.querySelectorAll('a,button,span,li,div')).filter(visible);
          const exact = elements
            .filter((el) => (el.innerText || el.textContent || '').trim() === targetText)
            .sort((a, b) => {
              const ar = a.getBoundingClientRect();
              const br = b.getBoundingClientRect();
              return (ar.width * ar.height) - (br.width * br.height);
            })[0];
          const partial = elements
            .filter((el) => (el.innerText || el.textContent || '').includes(targetText))
            .sort((a, b) => {
              const ar = a.getBoundingClientRect();
              const br = b.getBoundingClientRect();
              return (ar.width * ar.height) - (br.width * br.height);
            })[0];
          const target = exact || partial;
          const el = target && (target.closest('a,button,li') || target);
          if (!el) return false;
          el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window }));
          el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window }));
          el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
          return true;
        }
        """,
        text,
    )
    if clicked:
        return
    locator = page.get_by_text(text, exact=True)
    if locator.count() == 0:
        locator = page.get_by_text(text, exact=False)
    locator.first.click(timeout=timeout, force=True)


def frame_with_text(page, text: str, timeout_seconds: int = 30):
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        for frame in page.frames:
            try:
                body = frame.locator("body").inner_text(timeout=2_000)
            except Exception:
                continue
            if text in body:
                return frame
        page.wait_for_timeout(1000)
    raise RuntimeError(f"没有找到包含“{text}”的内嵌页面")

def frame_with_any_text(page, texts: list[str], timeout_seconds: int = 45):
    deadline = time.time() + timeout_seconds
    last_seen = ""
    while time.time() < deadline:
        for frame in page.frames:
            try:
                body = frame.locator("body").inner_text(timeout=2_000)
            except Exception:
                continue
            if body:
                last_seen = body[:500]
            if any(text in body for text in texts):
                return frame
        page.wait_for_timeout(1000)
    raise RuntimeError(f"没有找到包含任一文本的内嵌页面：{texts}；最后看到：{last_seen}")


def eleme_download_form_frame(page, timeout_seconds: int = 60):
    deadline = time.time() + timeout_seconds
    last_seen = ""
    required = ["门店下载", "下载数据", "日期", "至"]
    while time.time() < deadline:
        for frame in page.frames:
            try:
                body = frame.locator("body").inner_text(timeout=2_000)
            except Exception:
                continue
            if body:
                last_seen = body[:800]
            if all(text in body for text in required) and ("顾客实付" in body or "营业额及明细" in body):
                return frame
        page.wait_for_timeout(1000)
    raise RuntimeError(f"没有找到饿了么日报下载表单；最后看到：{last_seen}")


def click_visible_text(target, text: str) -> bool:
    return target.evaluate(
        """
        (targetText) => {
          const visible = (element) => {
            const style = window.getComputedStyle(element);
            const rect = element.getBoundingClientRect();
            return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
          };
          const elements = Array.from(document.querySelectorAll('button, a, span, div'))
            .filter((element) => visible(element) && (element.innerText || element.textContent || '').trim() === targetText)
            .sort((a, b) => {
              const ar = a.getBoundingClientRect();
              const br = b.getBoundingClientRect();
              return (ar.width * ar.height) - (br.width * br.height);
            });
          const target = elements[0];
          if (!target) return false;
          target.scrollIntoView({ block: 'center', inline: 'center' });
          const clickable = target.closest('button, a') || target;
          clickable.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window }));
          clickable.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window }));
          clickable.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
          return true;
        }
        """,
        text,
    )


def meituan_report_frame(page, timeout_seconds: int = 30):
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        for frame in page.frames:
            if "bizdata_pc/report/download" in frame.url:
                return frame
        page.wait_for_timeout(1000)
    raise RuntimeError("没有找到美团报表内嵌页面")


def click_frame_text_by_box(page, frame, text: str) -> None:
    locator = frame.locator(f'a:has-text("{text}")')
    if locator.count() == 0:
        locator = frame.locator(f'span:has-text("{text}")')
    if locator.count() == 0:
        raise RuntimeError(f"没有找到可点击文本：{text}")
    box = locator.first.bounding_box()
    if not box:
        raise RuntimeError(f"文本不可见：{text}")
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)


def safe_filename(name: str, suffix: str = ".csv") -> str:
    cleaned = "".join("+" if char.isspace() else char for char in name.strip())
    cleaned = cleaned.replace("/", "_").replace(":", "_")
    if not cleaned.lower().endswith(suffix):
        cleaned += suffix
    return cleaned


def yesterday_compact() -> str:
    return (date.today() - timedelta(days=1)).strftime("%Y%m%d")


def date_with_dashes(compact_date: str) -> str:
    return f"{compact_date[:4]}-{compact_date[4:6]}-{compact_date[6:8]}"


def meituan_history(frame) -> dict:
    return frame.evaluate(
        """async () => {
          const params = new URLSearchParams(location.search);
          const query = new URLSearchParams({
            pageSize: '20',
            pageNum: '1',
            ignoreSetRouterProxy: 'true',
            acctId: params.get('acctId') || '',
            wmPoiId: params.get('wmPoiId') || '-1',
            token: params.get('token') || '',
            appType: params.get('appType') || '3',
            deviceUUID: params.get('device_uuid') || params.get('deviceUUID') || ''
          });
          const response = await fetch('/gw/bizdata/report/download/history?' + query.toString(), {
            credentials: 'include'
          });
          return await response.json();
        }"""
    )


def download_url_to_file(context, url: str, filename: str) -> Path:
    target = downloads_dir() / filename
    temporary = target.with_name(f"{target.name}.part")
    page = context.new_page()
    try:
        with page.expect_download(timeout=60_000) as download_info:
            try:
                page.goto(url, wait_until="commit", timeout=60_000)
            except Exception as exc:
                if "Download is starting" not in str(exc):
                    raise
        download = download_info.value
        download.save_as(str(temporary))
        data_start = temporary.read_bytes()[:64]
        if temporary.stat().st_size == 0:
            raise RuntimeError("下载结果为空文件")
        if data_start.lstrip().startswith(b"<!DOCTYPE html") or data_start.lstrip().startswith(b"<html"):
            raise RuntimeError("下载结果是 HTML，不是 CSV")
        temporary.replace(target)
    finally:
        if temporary.exists():
            temporary.unlink()
        page.close()
    return target


def run_cdp_helper(command: str, *args: str) -> dict:
    config = load_config()
    helper = ROOT / "cdp_download_helpers.mjs"
    result = subprocess.run(
        ["node", str(helper), command, debug_url(config), *args],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(result.stdout)


def download_direct(url: str, filename: str, expected_suffix: str) -> Path:
    target = downloads_dir() / safe_filename(filename, expected_suffix)
    temporary = target.with_name(f"{target.name}.part")
    with urlopen(url, timeout=120) as response:
        data = response.read()
    if not data:
        raise RuntimeError("下载结果为空文件")
    if data.lstrip().startswith(b"<!DOCTYPE html") or data.lstrip().startswith(b"<html"):
        raise RuntimeError("下载结果是 HTML，不是报表文件")
    if expected_suffix == ".xlsx" and not data.startswith(b"PK"):
        raise RuntimeError("下载结果不是 Excel 文件")
    temporary.write_bytes(data)
    temporary.replace(target)
    return target


def download_eleme_latest(target_date: str | None = None) -> Path:
    config = load_config()
    platform = config["platforms"]["eleme"]
    histories: list[dict] = []
    playwright, browser = connect_browser(config)
    try:
        context = first_context(browser)
        page = context.new_page()

        def collect_history(response) -> None:
            if "/api/download/queryHistoryTaskList" not in response.url:
                return
            try:
                histories.append(response.json())
            except Exception:
                pass

        page.on("response", collect_history)
        goto_backend_page(page, platform["download_url"])
        page.wait_for_timeout(12_000)
        auth_error = next((item for item in histories if item.get("code") == 401002), None)
        if auth_error:
            raise RuntimeError(f"饿了么数据中心登录已失效：{auth_error.get('fullMsg') or auth_error.get('msg') or auth_error}")
        history = next((item for item in histories if item.get("code") == 0), histories[-1] if histories else {})
        rows = history.get("data") if isinstance(history, dict) else []
        if not isinstance(rows, list):
            rows = []
        ready_rows = [
            row for row in rows
            if row.get("downloadStatus") == 1 and row.get("downloadUrl") and row.get("fileName")
        ]
        if target_date:
            ready_rows = [row for row in ready_rows if target_date in row.get("fileName", "")]
        if not ready_rows:
            raise RuntimeError(f"饿了么下载列表没有可下载文件：{history}")
        latest = ready_rows[0]
        target = download_direct(latest["downloadUrl"], latest["fileName"], ".xlsx")
        print(f"饿了么最新报表已下载：{target}")
        return target
    finally:
        disconnect_browser(playwright, browser)


def generate_eleme_report(target_date: str) -> None:
    config = load_config()
    platform = config["platforms"]["eleme"]
    playwright, browser = connect_browser(config)
    try:
        context = first_context(browser)
        page = reusable_page(context)
        auth_errors: list[dict] = []

        def collect_auth_error(response) -> None:
            if "/api/downloadConfig/getConfigList" not in response.url and "/api/download/" not in response.url:
                return
            try:
                body = response.json()
            except BaseException:
                return
            if isinstance(body, dict) and body.get("code") == 401002:
                auth_errors.append(body)

        page.on("response", collect_auth_error)
        goto_backend_page(page, platform["download_url"])
        page.wait_for_timeout(5000)
        if auth_errors:
            auth_error = auth_errors[-1]
            raise RuntimeError(f"饿了么数据中心登录已失效：{auth_error.get('fullMsg') or auth_error.get('msg') or auth_error}")
        frame = eleme_download_form_frame(page, timeout_seconds=60)
        field_result = frame.evaluate(
            """(keywords) => {
              const visible = (element) => {
                const style = window.getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
              };
              const elements = Array.from(document.querySelectorAll('label, span, div, p'))
                .filter((element) => visible(element) && keywords.some((keyword) => (element.textContent || '').includes(keyword)));
              for (const element of elements) {
                const label = element.closest('label');
                const container = element.closest('[class]') || element.parentElement;
                const checkbox = (label && label.querySelector('input[type="checkbox"]')) ||
                  (container && container.querySelector('input[type="checkbox"]'));
                if (checkbox) {
                  if (!checkbox.checked) checkbox.click();
                  return { found: true, clicked: !checkbox.checked, method: 'checkbox' };
                }
                element.click();
                return { found: true, clicked: true, method: 'text' };
              }
              return { found: false, clicked: false };
            }""",
            ["顾客实付总额", "顾客实付", "顾客实付金额", "顾客实际支付", "顾客支付"],
        )
        if not field_result.get("found"):
            print("饿了么未在当前页面找到“顾客实付”字段，已继续提交现有字段。")
        captured_request: dict[str, object] = {}
        capture_errors: list[str] = []

        for attempt in range(1, 4):
            if attempt > 1:
                goto_backend_page(page, platform["download_url"])
                page.wait_for_timeout(5000)
                frame = eleme_download_form_frame(page, timeout_seconds=60)

            def capture_download_request(route, request):
                captured_request["url"] = request.url
                captured_request["post_data"] = request.post_data or "{}"
                captured_request["headers"] = request.headers
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"code": 0, "data": True, "message": "captured"}, ensure_ascii=False),
                )

            page.context.route("**/api/download/request**", capture_download_request)
            try:
                clicked = click_visible_text(frame, "下载数据")
                if not clicked:
                    download_button = frame.get_by_text("下载数据", exact=True)
                    if download_button.count() == 0:
                        download_button = frame.get_by_text("数据下载", exact=True)
                    if download_button.count() == 0:
                        download_button = frame.get_by_text("报表下载", exact=True)
                    download_button.last.click(timeout=10_000)
                deadline = time.time() + 30
                while time.time() < deadline and not captured_request:
                    page.wait_for_timeout(300)
                if captured_request:
                    break
                try:
                    frame_text = frame.locator("body").inner_text(timeout=3000)[:800]
                except Exception as exc:
                    frame_text = f"读取页面文本失败：{exc}"
                capture_errors.append(f"第 {attempt} 次未捕获到提交请求；页面片段：{frame_text}")
            finally:
                page.context.unroute("**/api/download/request**", capture_download_request)

        if not captured_request:
            try:
                body_text = page.locator("body").inner_text(timeout=3000)
            except Exception:
                body_text = ""
            if (
                "数据下载" in body_text
                and "报表下载" in body_text
                and "下载管理" in body_text
                and "门店" not in body_text
                and "顾客实付" not in body_text
            ):
                raise RuntimeError(
                    "饿了么下载中心只加载了空入口页，未加载门店报表表单；"
                    "通常是数据中心登录失效，或 download_url 缺少正确任务参数"
                )
            raise RuntimeError("没有捕获到饿了么报表提交请求；" + "；".join(capture_errors))

        payload = json.loads(captured_request["post_data"])
        map_str = payload.get("mapStr")
        if not isinstance(map_str, str):
            raise RuntimeError(f"饿了么报表请求缺少 mapStr：{payload}")
        map_payload = json.loads(map_str)
        dashed = date_with_dashes(target_date)
        for key in ("begin_dt", "end_dt", "startDate", "endDate"):
            map_payload[key] = target_date
        original = map_payload.get("originalParams")
        if isinstance(original, dict):
            filter_payload = original.get("filter")
            if isinstance(filter_payload, dict):
                filter_payload["date"] = [f"{dashed}T00:00:00.000Z", f"{dashed}T00:00:00.000Z"]
        payload["mapStr"] = json.dumps(map_payload, ensure_ascii=False, separators=(",", ":"))
        payload["fileName"] = f"门店下载_{target_date}至{target_date}_全部门店"
        forwarded_headers = {
            key: value
            for key, value in (captured_request.get("headers") or {}).items()
            if key.lower() in {"content-type", "token", "f-version"}
        }
        forwarded_headers.setdefault("content-type", "application/json")

        submit_attempts = int(os.environ.get("ELEME_REPORT_SUBMIT_RETRIES", "4"))
        submit_delay = int(os.environ.get("ELEME_REPORT_SUBMIT_RETRY_DELAY_SECONDS", "75"))
        body: dict = {}
        for submit_attempt in range(1, submit_attempts + 1):
            body = frame.evaluate(
                """async ({ url, payload, headers }) => {
                  const response = await fetch(url, {
                    method: 'POST',
                    credentials: 'include',
                    headers,
                    body: JSON.stringify(payload),
                  });
                  return await response.json();
                }""",
                {"url": captured_request["url"], "payload": payload, "headers": forwarded_headers},
            )
            if body.get("code") == 0:
                break
            message = str(body.get("fullMsg") or body.get("msg") or body.get("message") or body)
            if body.get("code") == 500203 and submit_attempt < submit_attempts:
                print(f"饿了么报表提交被限流，{submit_delay}s 后重试（{submit_attempt}/{submit_attempts}）：{message}")
                time.sleep(submit_delay)
                continue
            break
        if body.get("code") != 0:
            raise RuntimeError(f"饿了么生成报表失败：{body}")
        print(f"饿了么报表任务已提交：{target_date}")
    finally:
        disconnect_browser(playwright, browser)


def wait_for_eleme_report(target_date: str, timeout_seconds: int = 180) -> Path:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            return download_eleme_latest(target_date)
        except Exception as exc:
            last_error = exc
            time.sleep(10)
    raise TimeoutError(f"等待饿了么报表超时：{last_error}")


def download_meituan_latest(target_date: str | None = None) -> Path:
    config = load_config()
    platform = config["platforms"]["meituan"]
    playwright, browser = connect_browser(config)
    try:
        context = first_context(browser)
        page = reusable_page(context)
        goto_backend_page(page, platform["download_url"])
        page.wait_for_timeout(2500)

        report_frame = meituan_report_frame(page)
        history = meituan_history(report_frame)
        rows = history.get("data", {}).get("list", [])
        ready_rows = [row for row in rows if row.get("status") == 2 and row.get("url")]
        if target_date:
            dashed = date_with_dashes(target_date)
            ready_rows = [
                row for row in ready_rows
                if target_date in (row.get("name") or "") or dashed in (row.get("name") or "")
            ]
        if not ready_rows:
            raise RuntimeError(f"美团下载列表没有可下载文件：{history}")
        latest = ready_rows[0]
        filename = safe_filename(latest.get("name") or Path(urlparse(latest["url"]).path).name)
        target = download_url_to_file(context, latest["url"], filename)
        print(f"美团最新报表已下载：{target}")
        return target
    finally:
        disconnect_browser(playwright, browser)


def generate_meituan_report(target_date: str) -> None:
    config = load_config()
    fields = "2,3,32449,32454,32455,12021,12032,13021,13024,13025,13525,13530,13523,13528"
    playwright, browser = connect_browser(config)
    try:
        context = first_context(browser)
        page = reusable_page(context)
        goto_backend_page(page, "https://waimaieapp.meituan.com/bizdata_pc/report/download")
        page.wait_for_timeout(9000)
        result = page.evaluate(
            """async ({ targetDate, fields }) => {
              const findField = (value, keywords) => {
                const stack = [value];
                const seen = new Set();
                const candidates = [];
                while (stack.length) {
                  const item = stack.pop();
                  if (!item || typeof item !== 'object' || seen.has(item)) continue;
                  seen.add(item);
                  const label = [
                    item.name, item.title, item.label, item.fieldName, item.showName,
                    item.cnName, item.displayName, item.text, item.desc,
                    ...Object.values(item).filter((part) => typeof part === 'string' || typeof part === 'number')
                  ].filter(Boolean).join(' ');
                  if (keywords.some((keyword) => label.includes(keyword))) {
                    const id = item.id ?? item.fieldId ?? item.field ?? item.fieldCode ?? item.fieldKey ??
                      item.columnId ?? item.metricId ?? item.reportFieldId ?? item.key ?? item.dataIndex ??
                      item.value ?? item.code;
                    if (id !== undefined && id !== null && String(id).trim()) {
                      const score =
                        (label.includes('顾客实付') ? 100 : 0) +
                        (label.includes('顾客支付') ? 90 : 0) +
                        (label.includes('实付金额') ? 80 : 0) +
                        (label.includes('用户实付') ? 70 : 0) +
                        (label.includes('订单实付') ? 60 : 0) +
                        (label.includes('实付') ? 30 : 0) -
                        (label.includes('单均') ? 50 : 0);
                      candidates.push({ id: String(id).trim(), label, score });
                    }
                  }
                  if (Array.isArray(item)) {
                    for (const child of item) stack.push(child);
                  } else {
                    for (const child of Object.values(item)) {
                      if (child && typeof child === 'object') stack.push(child);
                    }
                  }
                }
                candidates.sort((a, b) => b.score - a.score || a.label.length - b.label.length);
                return candidates[0]?.id || null;
              };
              const tabUrl = performance.getEntriesByType('resource')
                .map((entry) => entry.name)
                .find((url) => url.includes('/gw/bizdata/report/download/tab'));
              if (!tabUrl) throw new Error('没有拿到美团报表参数');
              const url = new URL(tabUrl);
              const tabResponse = await fetch(tabUrl, { credentials: 'include' });
              const tabData = await tabResponse.json();
              const customerPaidField = findField(tabData, [
                '顾客实付总额', '顾客实付', '顾客实付金额', '顾客实际支付', '顾客支付',
                '用户实付', '用户支付', '订单实付', '实付金额', '实付'
              ]);
              const fieldSet = new Set(fields.split(',').map((field) => field.trim()).filter(Boolean));
              if (customerPaidField) fieldSet.add(customerPaidField);
              const finalFields = Array.from(fieldSet).join(',');
              url.pathname = '/gw/bizdata/report/download';
              url.searchParams.delete('poiType');
              const body = {
                beginDate: targetDate,
                endDate: targetDate,
                dateType: '1',
                fields: finalFields,
                requestCode: null,
                durationType: 0,
                aggreType: 0,
                acctId: url.searchParams.get('acctId'),
                wmPoiId: url.searchParams.get('wmPoiId'),
                poiType: 1,
                ignoreSetRouterProxy: 'true',
                wmPoiIds: ''
              };
              const response = await fetch(url.toString(), {
                method: 'POST',
                credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
              });
              const result = await response.json();
              result.customerPaidField = customerPaidField;
              result.finalFields = finalFields;
              return result;
            }""",
            {"targetDate": target_date, "fields": fields},
        )
        if not result.get("success"):
            raise RuntimeError(f"美团生成报表失败：{result}")
        if not result.get("customerPaidField"):
            print("美团未在字段接口找到“顾客实付”字段，已继续提交现有字段。")
        print(f"美团报表任务已提交：{target_date}")
    finally:
        disconnect_browser(playwright, browser)


def wait_for_meituan_report(target_date: str, timeout_seconds: int = 180) -> Path:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            return download_meituan_latest(target_date)
        except Exception as exc:
            last_error = exc
            time.sleep(10)
    raise TimeoutError(f"等待美团报表超时：{last_error}")


def download_eleme_reviews() -> Path:
    config = load_config()
    target_compact = yesterday_compact()
    target_dashed = date_with_dashes(target_compact)
    review_dir = ROOT / "data" / "reviews" / "raw"
    playwright, browser = connect_browser(config)
    try:
        context = first_context(browser)
        page = reusable_page(context)
        page.goto(ELEME_COMMENTS_URL, wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_timeout(8000)
        comment_frame = frame_or_page_with_any_text(page, ["导出评价"], timeout_seconds=45)
        task_ids: list[str] = []
        export_metas: list[dict] = []

        def collect_export_request(request) -> None:
            if "ExportRatingTaskService.exportRatingData" not in request.url:
                return
            try:
                body = json.loads(request.post_data or "{}")
            except Exception:
                return
            metas = body.get("metas") if isinstance(body, dict) else None
            if isinstance(metas, dict):
                export_metas.append(metas)

        def collect_export_task(response) -> None:
            if "ExportRatingTaskService.exportRatingData" not in response.url:
                return
            try:
                body = response.json()
            except Exception:
                return
            task_id = body.get("result") if isinstance(body, dict) else None
            if task_id:
                task_ids.append(str(task_id))

        page.on("request", collect_export_request)
        page.on("response", collect_export_task)
        clicked = comment_frame.evaluate(
            """() => {
              const visible = (el) => {
                const rect = el.getBoundingClientRect();
                const style = getComputedStyle(el);
                return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
              };
              const textOf = (el) => (el.innerText || el.textContent || '').trim().replace(/\\s+/g, '');
              const score = (el) => {
                const text = textOf(el);
                const cls = String(el.className || '');
                let value = 0;
                if (text === '导出评价') value += 100;
                if (text.includes('导出评价')) value += 90;
                if (text.includes('评价') || text.includes('评论')) value += 35;
                if (text.includes('导出') || text.includes('下载')) value += 35;
                if (text.includes('数据')) value += 10;
                if (/download|export/i.test(cls)) value += 20;
                if (el.tagName === 'BUTTON' || el.getAttribute('role') === 'button') value += 15;
                if (/取消|关闭|重置|删除/.test(text)) value -= 100;
                return value;
              };
              const candidates = Array.from(document.querySelectorAll('button,[role="button"],a,span.download-btn,[class*="download"],[class*="export"],span,div'))
                .filter(visible)
                .map((el) => {
                  const target = el.closest('button,[role="button"],a') || el;
                  return { el: target, value: score(el) + (target === el ? 0 : score(target)) };
                })
                .filter((item) => item.value >= 60)
                .sort((a, b) => b.value - a.value);
              const button = candidates[0]?.el;
              if (!button) {
                return {
                  ok: false,
                  controls: Array.from(document.querySelectorAll('button,[role="button"],a,span,div'))
                    .filter(visible)
                    .map((el) => ({ tag: el.tagName, text: textOf(el).slice(0, 80), className: String(el.className || '').slice(0, 120), score: score(el) }))
                    .filter((item) => item.text.includes('导出') || item.text.includes('下载') || item.text.includes('评价') || item.text.includes('评论') || /download|export/i.test(item.className))
                    .slice(0, 80)
                };
              }
              button.scrollIntoView({ block: 'center', inline: 'center' });
              const rect = button.getBoundingClientRect();
              const init = { bubbles: true, cancelable: true, view: window, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 };
              button.dispatchEvent(new PointerEvent('pointerdown', init));
              button.dispatchEvent(new MouseEvent('mousedown', init));
              button.dispatchEvent(new PointerEvent('pointerup', init));
              button.dispatchEvent(new MouseEvent('mouseup', init));
              button.dispatchEvent(new MouseEvent('click', init));
              if (typeof button.click === 'function') button.click();
              return { ok: true, text: textOf(button).slice(0, 80), className: String(button.className || '').slice(0, 120) };
            }"""
        )
        if not clicked or not clicked.get("ok"):
            raise RuntimeError(f"没有找到饿了么评价页的导出评价按钮，页面候选控件：{clicked}")
        deadline = time.time() + 30
        while not task_ids and time.time() < deadline:
            page.wait_for_timeout(500)
        if not task_ids:
            raise RuntimeError("饿了么评价导出任务未返回任务编号")
        task_id = task_ids[-1]
        metas = dict(export_metas[-1]) if export_metas else {}
        metas.setdefault("appVersion", "1.0.0")
        metas.setdefault("menuType", "CHAIN")
        metas.setdefault("appName", "melody")
        metas.setdefault("shopId", 93331264)
        result: dict | None = None
        poll_deadline = time.time() + 180
        while time.time() < poll_deadline:
            result = page.evaluate(
                """async ({taskId, requestId, metas}) => {
                  const body = {
                    service: 'ExportRatingTaskService',
                    method: 'getExportRatingTask',
                    params: { taskId },
                    id: requestId,
                    metas,
                    ncp: '2.0.0'
                  };
                  const response = await fetch('https://app-api.shop.ele.me/ugc/invoke/?method=ExportRatingTaskService.getExportRatingTask', {
                    method: 'POST',
                    credentials: 'include',
                    headers: {
                      'content-type': 'application/json;charset=UTF-8',
                      'x-eleme-requestid': requestId,
                      'x-shard': 'shopid=93331264'
                    },
                    body: JSON.stringify(body)
                  });
                  return await response.json();
                }""",
                {"taskId": task_id, "requestId": eleme_request_id(), "metas": metas},
            )
            task = result.get("result") if isinstance(result, dict) else None
            if isinstance(task, dict) and task.get("status") == "COMPLETE" and task.get("link"):
                filename = f"{task.get('taskName') or '用户评价数据_' + target_dashed}.xlsx"
                target = download_url_to_reviews(str(task["link"]), filename)
                break
            if isinstance(task, dict) and task.get("status") == "FAILED":
                raise RuntimeError(f"饿了么评价导出任务失败：{task}")
            page.wait_for_timeout(5000)
        else:
            raise TimeoutError(f"等待饿了么评价导出完成超时：{result}")
        print(f"饿了么评价已下载：{target}")
        return target
    except Exception as exc:
        raise RuntimeError(f"饿了么评价未下载到新文件，已停止生成：{exc}") from exc
    finally:
        disconnect_browser(playwright, browser)


def download_meituan_reviews() -> Path:
    config = load_config()
    target_compact = yesterday_compact()
    target_date = date_with_dashes(target_compact)
    page = None
    playwright, browser = connect_browser(config)
    try:
        context = first_context(browser)
        page = context.new_page()
        page.set_viewport_size({"width": 1440, "height": 1000})
        comment_urls: list[str] = []
        comment_pages: list[dict] = []

        def collect_comment_url(response) -> None:
            if "/gw/customer/comment/list" in response.url:
                comment_urls.append(response.url)
                try:
                    body = response.json()
                except Exception:
                    return
                data = body.get("data") if isinstance(body, dict) else None
                if isinstance(data, dict):
                    comment_pages.append(data)

        page.on("response", collect_comment_url)
        page.goto(MEITUAN_COMMENTS_URL, wait_until="domcontentloaded", timeout=90_000)
        deadline = time.time() + 30
        while not comment_urls and time.time() < deadline:
            page.wait_for_timeout(1000)
        if not comment_urls:
            raise RuntimeError("美团评价页未捕获评论列表接口")
        rows: list[dict] = []
        seen_offsets: set[int] = set()
        without_target_pages = 0
        for _ in range(80):
            while comment_pages:
                data = comment_pages.pop(0)
                offset = int(data.get("pageNum") or 0)
                if offset in seen_offsets:
                    continue
                seen_offsets.add(offset)
                items = data.get("list") or []
                target_items = [item for item in items if str(item.get("createTime") or "") == target_date]
                rows.extend(target_items)
                if target_items:
                    without_target_pages = 0
                else:
                    without_target_pages += 1
                dates = [str(item.get("createTime") or "") for item in items]
                if rows and without_target_pages >= 2 and dates and max(dates) < target_date:
                    comment_pages.clear()
                    break
            if rows and without_target_pages >= 2:
                break
            before_count = len(seen_offsets)
            page.mouse.click(1118, 950)
            page.wait_for_timeout(2500)
            if len(seen_offsets) == before_count and not comment_pages:
                without_target_pages += 1
                if rows and without_target_pages >= 2:
                    break

        if not rows:
            raise RuntimeError(f"美团评价接口没有返回 {target_date} 的评价")

        review_dir = ROOT / "data" / "reviews" / "raw"
        review_dir.mkdir(parents=True, exist_ok=True)
        target = review_dir / f"评价_全部门店_{target_compact}_{target_compact}_xxxnpf1211_{datetime.now().strftime('%Y-%m-%d+%H_%M_%S')}.csv"
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
            for item in rows:
                writer.writerow(
                    {
                        "评价时间": item.get("createTime") or target_date,
                        "门店名称": item.get("poiName") or "",
                        "综合评分": item.get("orderCommentScore") or item.get("commentScoreType") or "",
                        "评价内容": item.get("cleanComment") if item.get("cleanComment") is not None else item.get("comment") or "",
                        "用户昵称": item.get("userName") or "",
                        "门店id": item.get("wmPoiId") or "",
                        "味道评分": item.get("tasteScore") or item.get("foodCommentScore") or "",
                        "包装评分": item.get("packagingScore") or "",
                        "配送评分": item.get("deliveryCommentScore") or "",
                        "评价id": item.get("id") or "",
                    }
                )
        print(f"美团评价已下载：{target}")
        return target
    except Exception as exc:
        raise RuntimeError(f"美团评价未下载到新文件，已停止生成：{exc}") from exc
    finally:
        try:
            if page:
                page.close()
        except Exception:
            pass
        disconnect_browser(playwright, browser)

    last_error: Exception | None = None
    for _ in range(12):
        try:
            downloaded = download_meituan_latest(target_compact)
            review_dir = ROOT / "data" / "reviews" / "raw"
            review_dir.mkdir(parents=True, exist_ok=True)
            target = review_dir / downloaded.name
            if downloaded.resolve() != target.resolve():
                shutil.copy2(downloaded, target)
            print(f"美团评价已下载：{target}")
            return target
        except Exception as exc:
            last_error = exc
            time.sleep(10)
    raise RuntimeError(f"美团评价任务已提交，但下载列表没有拿到文件：{last_error}")


def download_reviews_and_process() -> None:
    failures: list[str] = []
    downloaded_count = 0
    for name, downloader in [("饿了么评价", download_eleme_reviews), ("美团评价", download_meituan_reviews)]:
        try:
            downloader()
            downloaded_count += 1
        except Exception as exc:
            failures.append(f"{name}：{exc}")
            print(f"{name}下载失败：{exc}", file=sys.stderr)
    if failures:
        if downloaded_count == 0:
            raise RuntimeError("评价下载未全部完成，且没有拿到任何新评价文件：" + "；".join(failures))
        print("评价下载存在失败项，继续用已下载文件和本地最新文件生成看板：" + "；".join(failures), file=sys.stderr)
    else:
        print("双平台评价下载完成。")
    process_reports()


def local_report_candidate(target_date: str, platform: str) -> Path | None:
    if platform == "eleme":
        patterns = [f"门店下载_{target_date}至{target_date}_*.xlsx", f"*{target_date}*饿了么*.xlsx"]
    else:
        patterns = [f"门店_全部门店_{target_date}_{target_date}_*.csv", f"*{target_date}*美团*.csv"]
    for directory in [ROOT / "data" / "raw", downloads_dir()]:
        if not directory.exists():
            continue
        candidates: list[Path] = []
        for pattern in patterns:
            candidates.extend(path for path in directory.glob(pattern) if path.is_file())
        if candidates:
            return max(candidates, key=lambda path: path.stat().st_mtime)
    return None


def latest_local_report_candidate(platform: str) -> Path | None:
    if platform == "eleme":
        patterns = ["门店下载_*.xlsx", "*饿了么*.xlsx", "eleme.xlsx"]
    else:
        patterns = ["门店_全部门店_*.csv", "*美团*.csv", "meituan.csv"]
    candidates: list[Path] = []
    for directory in [ROOT / "data" / "raw", downloads_dir()]:
        if not directory.exists():
            continue
        for pattern in patterns:
            candidates.extend(path for path in directory.glob(pattern) if path.is_file())
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None


def process_reports(eleme: Path | None = None, meituan: Path | None = None) -> None:
    bundled_python = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
    python = bundled_python if bundled_python.exists() else Path(sys.executable)
    args = [str(python), "process_reports.py"]
    if eleme:
        args.extend(["--eleme", str(eleme)])
    if meituan:
        args.extend(["--meituan", str(meituan)])
    if eleme is None or meituan is None:
        args.append("--allow-missing-platform")
    subprocess.run(args, cwd=ROOT, check=True)


def download_meituan_and_process() -> None:
    download_meituan_latest()
    process_reports()


def download_eleme_and_process() -> None:
    download_eleme_latest()
    process_reports()


def download_all_and_process() -> None:
    download_eleme_latest()
    download_meituan_latest()
    process_reports()


def run_daily(target_date: str | None = None) -> None:
    report_date = target_date or yesterday_compact()
    print(f"开始生成日报：{report_date}")
    submit_failures: list[str] = []
    submitted: dict[str, bool] = {"eleme": False, "meituan": False}
    for key, name, generator in [
        ("eleme", "饿了么", generate_eleme_report),
        ("meituan", "美团", generate_meituan_report),
    ]:
        try:
            generator(report_date)
            submitted[key] = True
        except Exception as exc:
            submit_failures.append(f"{name}报表任务提交失败：{exc}")
            print(f"{name}报表任务提交失败：{exc}", file=sys.stderr)

    eleme_path: Path | None = None
    meituan_path: Path | None = None
    download_failures: list[str] = []
    if submitted["eleme"]:
        try:
            eleme_path = wait_for_eleme_report(report_date)
        except Exception as exc:
            download_failures.append(f"饿了么报表下载失败：{exc}")
            print(f"饿了么报表下载失败：{exc}", file=sys.stderr)
    if submitted["meituan"]:
        try:
            meituan_path = wait_for_meituan_report(report_date)
        except Exception as exc:
            download_failures.append(f"美团报表下载失败：{exc}")
            print(f"美团报表下载失败：{exc}", file=sys.stderr)

    if eleme_path is None:
        eleme_path = local_report_candidate(report_date, "eleme")
        if eleme_path:
            print(f"饿了么日报改用本地候选文件：{eleme_path}", file=sys.stderr)
    if meituan_path is None:
        meituan_path = local_report_candidate(report_date, "meituan")
        if meituan_path:
            print(f"美团日报改用本地候选文件：{meituan_path}", file=sys.stderr)

    if not eleme_path and not meituan_path:
        details = "；".join(submit_failures + download_failures)
        raise RuntimeError("日报采集没有可用平台文件，未生成看板：" + details)
    if submit_failures or download_failures:
        print("日报采集存在失败项，继续用可用文件生成看板：" + "；".join(submit_failures + download_failures), file=sys.stderr)
    process_reports(eleme_path, meituan_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="连接常用 Chrome 的报表自动化验证工具")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="查看 Chrome 调试端口状态")
    subparsers.add_parser("start-chrome", help="启动带调试端口的常用 Chrome")
    subparsers.add_parser("open-pages", help="打开两个后台入口，确认登录状态")
    subparsers.add_parser("probe-pages", help="打开配置的下载页并识别页面")
    subparsers.add_parser("download-eleme", help="进入饿了么下载列表并下载最新报表")
    subparsers.add_parser("download-eleme-and-process", help="下载饿了么最新报表并重新生成看板")
    subparsers.add_parser("download-meituan", help="进入美团下载列表并下载最新报表")
    subparsers.add_parser("download-meituan-and-process", help="下载美团最新报表并重新生成看板")
    subparsers.add_parser("download-all-and-process", help="下载两个平台最新报表并重新生成看板")
    subparsers.add_parser("download-reviews-and-process", help="下载双平台评价并重新生成看板")
    daily_parser = subparsers.add_parser("daily", help="一键生成昨日日报：提交任务、下载两个平台报表并生成看板")
    daily_parser.add_argument("--date", help="指定日报日期，格式 YYYYMMDD；不填则使用昨天")
    args = parser.parse_args()

    if args.command == "status":
        status()
    elif args.command == "start-chrome":
        start_chrome()
    elif args.command == "open-pages":
        open_pages()
    elif args.command == "probe-pages":
        probe_pages()
    elif args.command == "download-eleme":
        download_eleme_latest()
    elif args.command == "download-eleme-and-process":
        download_eleme_and_process()
    elif args.command == "download-meituan":
        download_meituan_latest()
    elif args.command == "download-meituan-and-process":
        download_meituan_and_process()
    elif args.command == "download-all-and-process":
        download_all_and_process()
    elif args.command == "download-reviews-and-process":
        download_reviews_and_process()
    elif args.command == "daily":
        run_daily(args.date)


if __name__ == "__main__":
    main()
