from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "direct_meituan_accounts.json"
OUTPUT_DIR = ROOT / "business-report-dashboard" / "data" / "direct" / "raw"
WORKING_NODE = "/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
if Path(WORKING_NODE).exists():
    os.environ.setdefault("PLAYWRIGHT_NODEJS_PATH", WORKING_NODE)

sys.path.insert(0, str(ROOT / "business-report-dashboard"))
from chrome_cdp_reports import date_with_dashes, meituan_history, meituan_report_frame, safe_filename  # noqa: E402
from check_direct_meituan_account import MAC_CHROME, load_account, resolve_browser_executable  # noqa: E402


def require_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError:
        print("缺少 playwright。请先安装 business-report-dashboard/requirements.txt。")
        raise SystemExit(2)
    return sync_playwright


def yesterday_compact() -> str:
    return (date.today() - timedelta(days=1)).strftime("%Y%m%d")


def enabled_account_ids() -> list[str]:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return [
        str(account.get("id"))
        for account in payload.get("accounts") or []
        if account.get("id") and account.get("enabled", False)
    ]


def launch_context(playwright, account: dict, visible: bool, browser_executable: str | None):
    debug_port = account.get("debug_port")
    if debug_port and cdp_available(int(debug_port)):
        browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{int(debug_port)}")
        context = browser.contexts[0] if browser.contexts else browser.new_context(accept_downloads=True)
        return context, False

    profile_dir = Path(account["profile_dir"]).expanduser()
    profile_dir.mkdir(parents=True, exist_ok=True)
    executable_path = resolve_browser_executable(browser_executable)
    options = {
        "user_data_dir": str(profile_dir),
        "headless": not visible,
        "accept_downloads": True,
        "viewport": {"width": 1440, "height": 950},
    }
    if executable_path:
        options["executable_path"] = executable_path
    return playwright.chromium.launch_persistent_context(**options), True


def cdp_available(debug_port: int) -> bool:
    try:
        with urlopen(f"http://127.0.0.1:{debug_port}/json/version", timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


def goto_report_page(page, account: dict):
    url = (account.get("pages") or {}).get("daily_report") or "https://waimaieapp.meituan.com/bizdata_pc/report/download"
    page.goto(url, wait_until="domcontentloaded", timeout=90_000)
    page.wait_for_timeout(9000)
    frame = meituan_report_frame(page)
    if not report_params_ready(page, frame):
        raise RuntimeError(
            "直营美团日报页缺少 acctId/wmPoiId/token 参数；"
            "请先在同一 Chrome profile 登录 e.waimai.meituan.com 外层商家后台，"
            "再从后台进入经营分析/报表下载页。"
        )
    return frame


def report_params_ready(page, frame) -> bool:
    return bool(
        frame.evaluate(
            """() => {
              const hasParams = (rawUrl) => {
                try {
                  const url = new URL(rawUrl, location.href);
                  return Boolean(url.searchParams.get('acctId') && url.searchParams.get('wmPoiId') && url.searchParams.get('token'));
                } catch (_) {
                  return false;
                }
              };
              if (hasParams(location.href)) return true;
              return performance.getEntriesByType('resource')
                .map((entry) => entry.name)
                .some((url) => url.includes('/gw/bizdata/report/download/tab') && hasParams(url));
            }"""
        )
        or page.evaluate(
            """() => performance.getEntriesByType('resource')
              .map((entry) => entry.name)
              .some((url) => {
                if (!url.includes('/gw/bizdata/report/download/tab')) return false;
                const parsed = new URL(url, location.href);
                return Boolean(parsed.searchParams.get('acctId') && parsed.searchParams.get('wmPoiId') && parsed.searchParams.get('token'));
              })"""
        )
    )


def generate_report(page, account: dict, target_date: str) -> None:
    fields = "2,3,32449,32454,32455,12021,12032,13021,13024,13025,13525,13530,13523,13528"
    goto_report_page(page, account)
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
        raise RuntimeError(f"直营美团生成报表失败：{result}")
    if not result.get("customerPaidField"):
        print("直营美团未在字段接口找到“顾客实付”字段，已继续提交现有字段。")
    print(f"直营美团报表任务已提交：{target_date}")


def download_url_to_direct_raw(context, url: str, filename: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    target = OUTPUT_DIR / safe_filename(filename, ".csv")
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
        if temporary.stat().st_size == 0:
            raise RuntimeError("下载结果为空文件")
        data_start = temporary.read_bytes()[:64]
        if data_start.lstrip().startswith(b"<!DOCTYPE html") or data_start.lstrip().startswith(b"<html"):
            raise RuntimeError("下载结果是 HTML，不是 CSV")
        temporary.replace(target)
    finally:
        if temporary.exists():
            temporary.unlink()
        page.close()
    return target


def download_latest(page, context, account: dict, target_date: str | None) -> Path:
    frame = goto_report_page(page, account)
    history = meituan_history(frame)
    rows = history.get("data", {}).get("list", [])
    ready_rows = [row for row in rows if row.get("status") == 2 and row.get("url")]
    if target_date:
        dashed = date_with_dashes(target_date)
        ready_rows = [
            row for row in ready_rows
            if target_date in (row.get("name") or "") or dashed in (row.get("name") or "")
        ]
    if not ready_rows:
        raise RuntimeError(f"直营美团下载列表没有可下载文件：{history}")
    latest = ready_rows[0]
    filename = safe_filename(latest.get("name") or Path(urlparse(latest["url"]).path).name, ".csv")
    target = download_url_to_direct_raw(context, latest["url"], filename)
    print(f"直营美团最新报表已下载：{target}")
    return target


def run(account_id: str, target_date: str, submit: bool, visible: bool, wait_seconds: int, browser_executable: str | None) -> Path:
    account = load_account(account_id)
    sync_playwright = require_playwright()
    with sync_playwright() as p:
        context, should_close_context = launch_context(p, account, visible, browser_executable)
        page = context.pages[0] if context.pages else context.new_page()
        try:
            if submit:
                generate_report(page, account, target_date)
            deadline = time.time() + wait_seconds
            last_error: Exception | None = None
            while time.time() < deadline:
                try:
                    return download_latest(page, context, account, target_date)
                except Exception as exc:
                    if "缺少 acctId/wmPoiId/token 参数" in str(exc):
                        raise
                    last_error = exc
                    time.sleep(10)
            raise TimeoutError(f"等待直营美团报表超时：{last_error}")
        finally:
            if should_close_context:
                context.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="下载直营美团临时账号经营日报 CSV。")
    parser.add_argument("--account", default="direct_chaoyangmen", help="账号 ID。")
    parser.add_argument("--all", action="store_true", help="下载所有已启用直营美团账号。")
    parser.add_argument("--target-date", default=yesterday_compact(), help="报表日期，格式 YYYYMMDD；默认昨天。")
    parser.add_argument("--submit", action="store_true", help="先提交指定日期的报表任务，再等待下载。默认只下载已有文件。")
    parser.add_argument("--visible", action="store_true", help="显示浏览器窗口；默认 headless。")
    parser.add_argument("--wait-seconds", type=int, default=180, help="等待报表出现在下载列表的秒数。")
    parser.add_argument("--browser-executable", default=str(MAC_CHROME) if MAC_CHROME.exists() else None, help="Chrome/Chromium 可执行文件。")
    args = parser.parse_args()

    account_ids = enabled_account_ids() if args.all else [args.account]
    failures: list[str] = []
    for account_id in account_ids:
        try:
            path = run(account_id, args.target_date, args.submit, args.visible, args.wait_seconds, args.browser_executable)
            print(path)
        except Exception as exc:
            failures.append(f"{account_id}: {exc}")
            print(f"直营美团日报下载失败：{account_id}: {exc}", file=sys.stderr)
    if failures:
        raise SystemExit("；".join(failures))


if __name__ == "__main__":
    main()
