from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from one_click_meituan_balance import recent_meituan_promo_url


ROOT = Path(__file__).resolve().parent
WORKING_NODE = "/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
if Path(WORKING_NODE).exists():
    os.environ.setdefault("PLAYWRIGHT_NODEJS_PATH", WORKING_NODE)

from playwright.sync_api import sync_playwright

WORKSPACE = ROOT.parent
PREVIEW_PATH = WORKSPACE / "outputs" / "promo_budget_preview" / "latest.json"
LOG_DIR = WORKSPACE / "outputs" / "meituan_budget_automation"
DIRECT_MEITUAN_CONFIG_PATH = WORKSPACE / "config" / "direct_meituan_accounts.json"

WM_POI_IDS = {
    "第3档口": "30703865",
    "川湘府": "32346101",
    "金融街": "31264210",
    "光谷": "33283802",
    "双井": "32949755",
    "丽泽": "32914406",
    "第13档口": "32914406",
    "保利中心": "32022526",
    "安贞": "28944820",
    "五一广场": "32744963",
    "雅宝": "5650880",
    "朝阳门": "5650880",
    "B2档口": "5650880",
}


def load_direct_meituan_accounts() -> dict[str, dict]:
    if not DIRECT_MEITUAN_CONFIG_PATH.exists():
        return {}
    payload = json.loads(DIRECT_MEITUAN_CONFIG_PATH.read_text(encoding="utf-8"))
    return {
        str(account.get("id")): account
        for account in payload.get("accounts", [])
        if account.get("id") and account.get("enabled", True)
    }


def load_tasks(period: str) -> list[dict]:
    payload = json.loads(PREVIEW_PATH.read_text(encoding="utf-8"))
    key = "meituan_dinner" if period == "晚餐" else "meituan_lunch"
    return [item for item in payload.get(key, []) if item.get("status") == "auto"]


def resolve_period(period: str) -> str:
    if period in {"午餐", "晚餐"}:
        return period
    return "午餐" if time.localtime().tm_hour < 15 else "晚餐"


def wm_poi_id(task: dict) -> str:
    configured = str(task.get("wmPoiId") or task.get("wm_poi_id") or "").strip()
    if configured:
        return configured
    joined = " ".join(str(task.get(key, "")) for key in ["keyword", "store", "sourceStore"])
    for keyword, value in WM_POI_IDS.items():
        if keyword in joined:
            return value
    raise RuntimeError(f"没有门店 wmPoiId：{joined}")


def wm_poi_id_from_url(raw_url: str) -> str | None:
    candidates = [raw_url]
    fragment = urlsplit(raw_url).fragment
    if fragment:
        candidates.append(fragment)
    for candidate in candidates:
        query = dict(parse_qsl(urlsplit(candidate).query, keep_blank_values=True))
        value = query.get("wmPoiId")
        if value:
            return value
    return None


def url_for_store(base_url: str, wm_id: str) -> str:
    parts = urlsplit(base_url)
    if "waimaieapp.meituan.com" in parts.fragment:
        inner = urlsplit(parts.fragment)
        inner_query = dict(parse_qsl(inner.query, keep_blank_values=True))
        inner_query["wmPoiId"] = wm_id
        inner_url = urlunsplit((inner.scheme, inner.netloc, inner.path, urlencode(inner_query), inner.fragment or "/index"))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, inner_url))
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["wmPoiId"] = wm_id
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), "/index"))


def page_text(page) -> str:
    texts: list[str] = []
    for frame in page.frames:
        try:
            texts.append(frame.locator("body").inner_text(timeout=10000))
        except Exception:
            pass
    return "\n".join(text for text in texts if text)


def read_budget(page) -> float | None:
    text = page_text(page)
    patterns = [
        r"(?:推广预算|每日预算)\s*(?:预算已耗尽|已消耗\s*\d+%)?\s*(\d+(?:\.\d+)?)\s*元",
        r"(?:推广预算|每日预算).*?\n(\d+(?:\.\d+)?)\n元",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.S)
        if match:
            return float(match.group(1))
    return None


def wait_budget(page, *, timeout_seconds: int = 15) -> float | None:
    last_value = None
    for _ in range(timeout_seconds):
        value = read_budget(page)
        if value and value > 0:
            return value
        last_value = value
        time.sleep(1)
    return last_value


def setting_snapshot(page) -> dict:
    return page.evaluate(
        """() => {
            const text = document.body.innerText || '';
            const wrappers = [...document.querySelectorAll('.isomor-cpc-fresh-right-wrapper, [class*=right-wrapper]')]
                .map((el) => {
                    const rect = el.getBoundingClientRect();
                    return {
                        text: (el.innerText || '').trim(),
                        width: rect.width,
                        height: rect.height,
                        cursor: getComputedStyle(el).cursor,
                    };
                })
                .filter((item) => item.width > 0 && item.height > 0);
            const rangeMatch = text.match(/当前最终出价范围为\\s*([0-9.]+)~([0-9.]+)元/);
            return {
                text,
                wrappers,
                rangeMin: rangeMatch ? Number(rangeMatch[1]) : null,
                rangeMax: rangeMatch ? Number(rangeMatch[2]) : null,
            };
        }"""
    )


def wait_setting_ready(page, *, timeout_seconds: int = 35) -> dict:
    last_snapshot = {}
    for _ in range(timeout_seconds):
        last_snapshot = setting_snapshot(page)
        budget = read_budget(page)
        range_max = last_snapshot.get("rangeMax")
        has_clickable_budget = any(
            ("预算" in wrapper.get("text", "") or "元" in wrapper.get("text", ""))
            and wrapper.get("cursor") == "pointer"
            for wrapper in last_snapshot.get("wrappers", [])
        )
        if budget and budget > 0 and has_clickable_budget:
            return last_snapshot
        if range_max and range_max > 0 and has_clickable_budget:
            return last_snapshot
        time.sleep(1)
    return last_snapshot


def click_visible_text(page, label: str) -> bool:
    for frame in page.frames:
        locator = frame.get_by_text(label)
        for index in range(locator.count()):
            item = locator.nth(index)
            try:
                if item.is_visible():
                    item.click(timeout=5000)
                    return True
            except Exception:
                pass
    return False


def enter_dianjin(page) -> None:
    text = page_text(page)
    if "推广设置" in text and ("推广预算" in text or "每日预算" in text):
        return
    if not click_visible_text(page, "点金推广"):
        raise RuntimeError("没有可见的点金推广入口")
    for _ in range(15):
        time.sleep(1)
        text = page_text(page)
        if "推广设置" in text and ("推广预算" in text or "每日预算" in text):
            return
    raise RuntimeError("进入点金推广后没有预算区域")


def enter_dianjin_with_recovery(page, target_url: str) -> None:
    errors: list[str] = []
    for attempt in range(3):
        try:
            enter_dianjin(page)
            return
        except Exception as exc:
            errors.append(str(exc))
            if attempt == 0:
                page.reload(wait_until="domcontentloaded", timeout=30000)
            else:
                page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(5)
    raise RuntimeError("没有可见的点金推广入口；重试后仍失败：" + "；".join(errors[-2:]))


def open_budget_modal(page) -> None:
    def opened() -> bool:
        return (
            page.get_by_text("预算设置").count() > 0
            and page.locator('input[type="number"]').count() > 0
            and page.get_by_role("button", name="确定").count() > 0
        )

    def try_dom_click(selector: str) -> bool:
        try:
            count = page.locator(selector).count()
        except Exception:
            return False
        for index in range(count):
            item = page.locator(selector).nth(index)
            try:
                if not item.is_visible():
                    continue
                item.click(timeout=3000)
                time.sleep(1)
                if opened():
                    return True
            except Exception:
                continue
        return False

    def budget_click_boxes() -> list[dict]:
        return page.evaluate(
            """() => {
                const visible = (el) => {
                    const rect = el.getBoundingClientRect();
                    const style = getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0
                        && style.display !== 'none'
                        && style.visibility !== 'hidden';
                };
                const boxes = [];
                const lines = [
                    ...document.querySelectorAll(
                        '.isomor-cpc-fresh-budget-line, .isomor-cpc-fresh-budget-lines, [class*=budget]'
                    )
                ];
                for (const line of lines) {
                    const text = (line.innerText || '').trim();
                    if (!/(推广预算|每日预算|预算已耗尽|已消耗)/.test(text)) {
                        continue;
                    }
                    const candidates = [
                        ...line.querySelectorAll(
                            '.isomor-cpc-fresh-right-wrapper, [class*=right-wrapper], [class*=cursor], [class*=arrow], [class*=action]'
                        )
                    ].filter(visible);
                    const target = candidates[0] || line;
                    if (!visible(target)) {
                        continue;
                    }
                    const rect = target.getBoundingClientRect();
                    boxes.push({x: rect.x, y: rect.y, w: rect.width, h: rect.height});
                }
                return boxes;
            }"""
        )

    for selector in [
        ".isomor-cpc-fresh-budget-number",
        ".isomor-cpc-fresh-used-wrapper",
        ".isomor-cpc-fresh-right-wrapper.isomor-cpc-cursor",
        ".isomor-cpc-fresh-budget-line .r2x-text",
    ]:
        if try_dom_click(selector):
            return

    for _ in range(4):
        for box in budget_click_boxes():
            page.mouse.click(box["x"] + box["w"] / 2, box["y"] + box["h"] / 2)
            time.sleep(1)
            if opened():
                return

    for label in ["推广预算", "每日预算"]:
        locator = page.get_by_text(label)
        for index in range(locator.count()):
            item = locator.nth(index)
            try:
                if not item.is_visible():
                    continue
                box = item.bounding_box()
                if not box:
                    continue
                for dx in [20, 120, 250, 340]:
                    page.mouse.click(box["x"] + dx, box["y"] + 8)
                    time.sleep(1)
                    if opened():
                        return
            except Exception:
                pass
    raise RuntimeError("未打开预算设置弹窗，可能当前门店预算区域不可编辑")


def execute_task(context, base_url: str, task: dict, *, commit: bool) -> dict:
    target = float(task["targetBudget"])
    try:
        wm_id = wm_poi_id(task)
    except RuntimeError:
        if not task.get("directMeituanAccountId"):
            raise
        wm_id = wm_poi_id_from_url(base_url)
        if not wm_id:
            raise
    target_url = url_for_store(base_url, wm_id)
    page = None
    created_page = False
    for candidate in context.pages:
        urls = [candidate.url, *(frame.url for frame in candidate.frames)]
        if any(f"wmPoiId={wm_id}" in url for url in urls):
            text = page_text(candidate)
            if "推广设置" in text or "点金推广" in text:
                page = candidate
                break
    if page is None:
        page = context.new_page()
        created_page = True
    record = {
        "store": task.get("store"),
        "keyword": task.get("keyword"),
        "wmPoiId": wm_id,
        "directMeituanAccountId": task.get("directMeituanAccountId") or "",
        "targetBudget": target,
        "ok": False,
    }
    try:
        if created_page:
            page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(5)
        enter_dianjin_with_recovery(page, target_url)
        ready = wait_setting_ready(page)
        if read_budget(page) in {None, 0} and ready.get("rangeMax") in {None, 0}:
            page.reload(wait_until="domcontentloaded", timeout=30000)
            time.sleep(5)
            enter_dianjin_with_recovery(page, target_url)
            wait_setting_ready(page)
        record["beforeBudget"] = wait_budget(page)
        if not commit:
            record["ok"] = True
            record["message"] = "预览模式：已打开门店并读取当前预算，未保存修改"
            return record
        if record["beforeBudget"] is not None and abs(record["beforeBudget"] - target) <= 0.01:
            record["afterBudget"] = record["beforeBudget"]
            record["ok"] = True
            record["message"] = "页面预算已是目标值，无需重复保存"
            return record
        try:
            open_budget_modal(page)
        except RuntimeError:
            page.reload(wait_until="domcontentloaded", timeout=30000)
            time.sleep(5)
            enter_dianjin_with_recovery(page, target_url)
            wait_setting_ready(page)
            open_budget_modal(page)
        input_box = page.locator('input[type="number"]').first
        record["beforeInput"] = input_box.input_value(timeout=3000)
        value = str(int(target) if target.is_integer() else target)
        input_box.fill(value)
        time.sleep(0.3)
        record["afterInput"] = input_box.input_value(timeout=3000)
        if float(record["afterInput"]) != target:
            raise RuntimeError(f"输入框未变为目标预算：{record['afterInput']}")
        confirm_button = page.get_by_role("button", name="确定")
        if confirm_button.count() == 0:
            raise RuntimeError("预算弹窗没有确定按钮")
        if not confirm_button.first.is_enabled(timeout=3000):
            page.keyboard.press("Escape")
            time.sleep(2)
            final_budget = read_budget(page)
            record["afterBudget"] = final_budget
            if final_budget is not None and abs(final_budget - target) <= 0.01:
                record["ok"] = True
                record["message"] = "确定按钮禁用，页面预算已是目标值"
                return record
            raise RuntimeError(f"确定按钮禁用，且页面预算={final_budget}，目标={target}")
        confirm_button.first.click(timeout=5000)
        time.sleep(6)
        final_budget = read_budget(page)
        record["afterBudget"] = final_budget
        if final_budget is None or abs(final_budget - target) > 0.01:
            raise RuntimeError(f"保存后预算={final_budget}，目标={target}")
        record["ok"] = True
        record["message"] = "已保存并读回确认"
    finally:
        if created_page:
            try:
                page.close()
            except Exception:
                pass
    return record


def context_for_task(playwright, contexts: dict[str, object], task: dict, direct_accounts: dict[str, dict]):
    account_id = task.get("directMeituanAccountId") or ""
    if not account_id:
        endpoint = "http://127.0.0.1:9222"
        if endpoint not in contexts:
            browser = playwright.chromium.connect_over_cdp(endpoint)
            contexts[endpoint] = browser.contexts[0] if browser.contexts else browser.new_context()
        return contexts[endpoint]

    account = direct_accounts.get(account_id)
    if not account:
        raise RuntimeError(f"未找到直营美团账号配置：{account_id}")
    debug_port = account.get("debug_port")
    if not debug_port:
        raise RuntimeError(f"直营美团账号未配置 debug_port：{account_id}")
    endpoint = f"http://127.0.0.1:{int(debug_port)}"
    if endpoint not in contexts:
        browser = playwright.chromium.connect_over_cdp(endpoint)
        contexts[endpoint] = browser.contexts[0] if browser.contexts else browser.new_context()
    return contexts[endpoint]


def recent_promo_url_from_context(context) -> str | None:
    for page in reversed(context.pages):
        candidates = [page.url]
        candidates.extend(frame.url for frame in page.frames)
        for candidate in candidates:
            if (
                "waimaieapp.meituan.com/ad/v1/rpc" in candidate
                and "token=" in candidate
                and "acctId=" in candidate
            ):
                return candidate
    return None


def open_direct_promo_url(context, account: dict) -> str:
    page = context.new_page()
    try:
        home_url = ((account.get("pages") or {}).get("home")) or "https://e.waimai.meituan.com/"
        page.goto(home_url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(5)
        click_visible_text(page, "门店推广")
        time.sleep(12)
        promo_url = recent_promo_url_from_context(context)
        if promo_url:
            return promo_url

        page_url = ((account.get("pages") or {}).get("promo_balance")) or ""
        if page_url:
            page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(10)
            promo_url = recent_promo_url_from_context(context)
            if promo_url:
                return promo_url
    finally:
        try:
            page.close()
        except Exception:
            pass
    raise RuntimeError(f"直营美团账号未能打开点金推广内层页面：{account.get('id')}")


def base_url_for_task(default_base_url: str, task: dict, direct_accounts: dict[str, dict], context=None) -> str:
    account_id = task.get("directMeituanAccountId") or ""
    if not account_id:
        return default_base_url
    account = direct_accounts.get(account_id)
    if context is not None:
        return recent_promo_url_from_context(context) or open_direct_promo_url(context, account or {})
    page_url = ((account or {}).get("pages") or {}).get("promo_balance")
    if not page_url:
        raise RuntimeError(f"直营美团账号未配置 promo_balance 页面：{account_id}")
    return page_url


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--period", default="auto", choices=["auto", "午餐", "晚餐"])
    parser.add_argument("--mode", default="commit", choices=["preview", "commit"])
    parser.add_argument("--limit", default="all", help="执行数量；默认 all。预览时可用 1 快速验证。")
    parser.add_argument("--stores", default="", help="只执行指定门店关键词，逗号分隔，例如：第3档口,川湘府")
    args = parser.parse_args()
    period = resolve_period(args.period)
    commit = args.mode == "commit"

    direct_accounts = load_direct_meituan_accounts()

    tasks = load_tasks(period)
    if args.stores.strip():
        keywords = [item.strip() for item in args.stores.split(",") if item.strip()]
        tasks = [
            task for task in tasks
            if any(keyword in " ".join(str(task.get(key, "")) for key in ["keyword", "store", "sourceStore"]) for keyword in keywords)
        ]
        if not tasks:
            raise RuntimeError(f"没有匹配到指定门店：{args.stores}")
    if args.limit != "all":
        try:
            limit = int(args.limit)
        except ValueError as exc:
            raise RuntimeError("--limit 必须是 all 或正整数") from exc
        if limit < 1:
            raise RuntimeError("--limit 必须是 all 或正整数")
        tasks = tasks[:limit]
    base_url = recent_meituan_promo_url()
    if not base_url and any(not task.get("directMeituanAccountId") for task in tasks):
        raise RuntimeError("没有找到本地 Chrome 最近的美团推广 URL，请先在本地 Chrome 打开一次美团点金推广页。")
    base_url = base_url or ""

    results = []
    with sync_playwright() as playwright:
        contexts: dict[str, object] = {}
        for task in tasks:
            try:
                print(f"{task.get('keyword')} -> {task.get('targetBudget')} ({args.mode})", flush=True)
                context = context_for_task(playwright, contexts, task, direct_accounts)
                task_base_url = base_url_for_task(base_url, task, direct_accounts, context)
                results.append(execute_task(context, task_base_url, task, commit=commit))
            except Exception as exc:
                results.append({
                    "store": task.get("store"),
                    "keyword": task.get("keyword"),
                    "directMeituanAccountId": task.get("directMeituanAccountId") or "",
                    "targetBudget": task.get("targetBudget"),
                    "ok": False,
                    "error": str(exc),
                })
                print(f"失败：{task.get('keyword')}：{exc}", flush=True)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    output = LOG_DIR / f"meituan_cdp_{period}_{time.strftime('%Y%m%d_%H%M%S')}.json"
    output.write_text(
        json.dumps(
            {
                "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
                "period": period,
                "requestedPeriod": args.period,
                "mode": args.mode,
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    ok_count = sum(1 for item in results if item.get("ok"))
    fail_count = len(results) - ok_count
    print(f"美团预算执行日志：{output}")
    print(f"任务数：{len(results)}，成功：{ok_count}，失败：{fail_count}")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
