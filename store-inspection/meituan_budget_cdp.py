from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path
from urllib.error import URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import urlopen

from one_click_meituan_balance import URL as MEITUAN_PROMO_FALLBACK_URL
from one_click_meituan_balance import recent_meituan_promo_url


ROOT = Path(__file__).resolve().parent
WORKING_NODE = "/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
if Path(WORKING_NODE).exists():
    os.environ.setdefault("PLAYWRIGHT_NODEJS_PATH", WORKING_NODE)

from playwright.sync_api import sync_playwright

WORKSPACE = ROOT.parent
PREVIEW_PATH = WORKSPACE / "outputs" / "promo_budget_preview" / "latest.json"
LOG_DIR = WORKSPACE / "outputs" / "meituan_budget_automation"
EVIDENCE_DIR = WORKSPACE / "outputs" / "meituan_budget_automation" / "evidence"
DIRECT_PROMO_URL_CACHE_PATH = LOG_DIR / "direct_promo_urls.json"
DIRECT_MEITUAN_CONFIG_PATH = WORKSPACE / "config" / "direct_meituan_accounts.json"
MAC_CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

INPUT_RETRY_ATTEMPTS = int(os.environ.get("MEITUAN_BUDGET_INPUT_RETRY_ATTEMPTS", "3"))
STORE_RETRY_ATTEMPTS = int(os.environ.get("MEITUAN_BUDGET_STORE_RETRY_ATTEMPTS", "2"))

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


def cdp_available(debug_port: int) -> bool:
    try:
        with urlopen(f"http://127.0.0.1:{debug_port}/json/version", timeout=2) as response:
            return response.status == 200
    except (URLError, OSError):
        return False
    except Exception:
        return False


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


def classify_failure(message: str) -> str:
    body = str(message or "")
    if any(token in body for token in ("未登录", "登录", "验证码", "安全验证", "UNAUTHORIZED")):
        return "auth_block"
    if any(token in body for token in ("未能打开点金推广内层页面", "没有可见的点金推广入口", "进入点金推广后没有预算区域")):
        return "direct_promo_url_missing" if "直营美团账号" in body else "dianjin_entry_missing"
    if any(token in body for token in ("输入框未变为目标预算", "预算弹窗没有可见可编辑", "确定按钮禁用")):
        return "input_sync_failed" if "输入框" in body else "confirm_disabled"
    if any(token in body for token in ("未打开预算设置弹窗", "预算区域不可编辑", "预算弹窗没有确定按钮")):
        return "page_structure_changed"
    if "没有门店 wmPoiId" in body or "未找到直营美团账号配置" in body:
        return "store_mapping"
    if "timeout" in body.lower() or "超时" in body:
        return "timeout"
    return "execution_failed"


def store_slug(task: dict) -> str:
    raw = str(task.get("keyword") or task.get("store") or task.get("sourceStore") or "store")
    slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "_", raw).strip("_")
    return slug or "store"


def save_failure_evidence(page, task: dict, stage: str) -> dict:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    prefix = EVIDENCE_DIR / f"{stamp}_{store_slug(task)}_{stage}"
    evidence = {
        "stage": stage,
        "text_path": "",
        "screenshot_path": "",
        "url": "",
    }
    try:
        evidence["url"] = page.url
    except Exception:
        pass
    try:
        text_path = prefix.with_suffix(".txt")
        text_path.write_text(page_text(page), encoding="utf-8")
        evidence["text_path"] = str(text_path.relative_to(WORKSPACE))
    except Exception:
        pass
    try:
        shot_path = prefix.with_suffix(".png")
        page.screenshot(path=str(shot_path), full_page=True, timeout=10000)
        evidence["screenshot_path"] = str(shot_path.relative_to(WORKSPACE))
    except Exception:
        pass
    return evidence


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
            time.sleep(8)
    raise RuntimeError("没有可见的点金推广入口；重试后仍失败：" + "；".join(errors[-2:]))


def open_budget_modal(page) -> None:
    def opened() -> bool:
        for frame in page.frames:
            try:
                if (
                    frame.get_by_text("预算设置").count() > 0
                    and frame.locator('input[type="number"]').count() > 0
                    and confirm_button_locator(page) is not None
                ):
                    return True
            except Exception:
                continue
        return False

    def try_dom_click(selector: str) -> bool:
        for frame in page.frames:
            try:
                count = frame.locator(selector).count()
            except Exception:
                continue
            for index in range(count):
                item = frame.locator(selector).nth(index)
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
        boxes: list[dict] = []
        for frame in page.frames:
            try:
                frame_boxes = frame.evaluate(
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
            except Exception:
                continue
            boxes.extend(frame_boxes or [])
        return boxes

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
        for frame in page.frames:
            locator = frame.get_by_text(label)
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


def budget_input_locator(page):
    scored_candidates = []
    for frame in page.frames:
        try:
            candidates = frame.evaluate(
                """() => [...document.querySelectorAll('input[type="number"]')]
                    .map((el, index) => {
                        const rect = el.getBoundingClientRect();
                        const style = getComputedStyle(el);
                        const visible = rect.width > 0 && rect.height > 0
                            && style.display !== 'none'
                            && style.visibility !== 'hidden'
                            && !el.disabled
                            && !el.readOnly;
                        let text = '';
                        let node = el;
                        for (let depth = 0; node && depth < 8; depth += 1, node = node.parentElement) {
                            text += '\\n' + (node.innerText || '');
                        }
                        const dialog = el.closest('[role=dialog], [class*=dialog], [class*=modal], [class*=popover]');
                        const dialogText = dialog ? (dialog.innerText || '') : '';
                        const placeholder = el.getAttribute('placeholder') || '';
                        let score = 0;
                        if (dialogText.includes('预算设置')) score += 100;
                        if (dialogText.includes('预算')) score += 40;
                        if (text.includes('预算设置')) score += 60;
                        if (text.includes('推广预算') || text.includes('每日预算')) score += 30;
                        if (placeholder.includes('预算') || placeholder.includes('金额')) score += 20;
                        if (visible) score += 10;
                        return {index, visible, score, text, dialogText, placeholder};
                    })
                    .filter((item) => item.visible)
                    .sort((a, b) => b.score - a.score)"""
            )
        except Exception:
            continue
        for item in candidates:
            scored_candidates.append((int(item.get("score", 0)), frame, int(item["index"])))
    if not scored_candidates:
        raise RuntimeError("预算弹窗没有可见可编辑的数字输入框")
    scored_candidates.sort(key=lambda item: item[0], reverse=True)
    _, frame, index = scored_candidates[0]
    return frame.locator('input[type="number"]').nth(index)


def set_budget_input(input_box, value: str) -> tuple[str, str]:
    before = input_box.input_value(timeout=3000)
    input_box.click(timeout=3000)
    input_box.fill("")
    input_box.type(value, delay=35)
    input_box.evaluate(
        """(el, value) => {
            const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
            if (setter) {
                setter.call(el, value);
            } else {
                el.value = value;
            }
            el.dispatchEvent(new Event('input', {bubbles: true}));
            el.dispatchEvent(new Event('change', {bubbles: true}));
            el.dispatchEvent(new KeyboardEvent('keyup', {bubbles: true, key: 'Enter'}));
            el.blur();
        }""",
        value,
    )
    time.sleep(0.8)
    after = input_box.input_value(timeout=3000)
    return before, after


def close_budget_modal(page) -> None:
    try:
        page.keyboard.press("Escape")
        time.sleep(1)
    except Exception:
        pass


def trigger_form_dirty(page, input_box, value: str) -> None:
    try:
        input_box.evaluate(
            """(el, value) => {
                const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
                if (setter) setter.call(el, value);
                else el.value = value;
                for (const eventName of ['input', 'change', 'keyup', 'blur']) {
                    el.dispatchEvent(new Event(eventName, {bubbles: true}));
                }
            }""",
            value,
        )
    except Exception:
        pass
    try:
        radios = page.locator('input[type="radio"]')
        if radios.count() >= 2:
            first_checked = None
            for index in range(radios.count()):
                radio = radios.nth(index)
                if radio.is_checked(timeout=1000):
                    first_checked = index
                    break
            toggle_index = 1 if first_checked == 0 else 0
            radios.nth(toggle_index).click(force=True, timeout=2000)
            time.sleep(0.4)
            if first_checked is not None:
                radios.nth(first_checked).click(force=True, timeout=2000)
    except Exception:
        pass


def fill_budget_with_recovery(page, target: float) -> tuple[str, str, int]:
    value = str(int(target) if target.is_integer() else target)
    before = ""
    after = ""
    for attempt in range(1, INPUT_RETRY_ATTEMPTS + 1):
        input_box = budget_input_locator(page)
        try:
            before, after = set_budget_input(input_box, value)
        except Exception:
            before, after = "", ""
        if after and abs(float(after) - target) <= 0.01:
            return before, after, attempt
        trigger_form_dirty(page, input_box, value)
        time.sleep(0.8)
        try:
            after = input_box.input_value(timeout=3000)
            if after and abs(float(after) - target) <= 0.01:
                return before, after, attempt
        except Exception:
            pass
        if attempt < INPUT_RETRY_ATTEMPTS:
            close_budget_modal(page)
            time.sleep(1)
            open_budget_modal(page)
    raise RuntimeError(f"输入框未变为目标预算：{after or before}")


def confirm_button_locator(page):
    locator_specs = [
        lambda frame: frame.get_by_role("button", name=re.compile(r"^\s*确定\s*$")),
        lambda frame: frame.get_by_text("确定", exact=True),
    ]
    for frame in page.frames:
        for locator_for in locator_specs:
            try:
                locator = locator_for(frame)
                count = locator.count()
            except Exception:
                continue
            for index in range(count):
                item = locator.nth(index)
                try:
                    if item.is_visible():
                        return item
                except Exception:
                    continue
    return None


def confirm_button_enabled(locator) -> bool:
    try:
        return locator.is_enabled(timeout=3000)
    except Exception:
        return True


def confirm_budget_with_recovery(page, target: float) -> tuple[float | None, str]:
    confirm_button = confirm_button_locator(page)
    if confirm_button is None:
        raise RuntimeError("预算弹窗没有确定按钮")
    if not confirm_button_enabled(confirm_button):
        input_box = budget_input_locator(page)
        value = str(int(target) if target.is_integer() else target)
        trigger_form_dirty(page, input_box, value)
        time.sleep(1)
        confirm_button = confirm_button_locator(page) or confirm_button
    if not confirm_button_enabled(confirm_button):
        final_budget = read_budget(page)
        if final_budget is not None and abs(final_budget - target) <= 0.01:
            close_budget_modal(page)
            return final_budget, "确定按钮禁用，页面预算已是目标值"
        raise RuntimeError(f"确定按钮禁用，且页面预算={final_budget}，目标={target}")
    confirm_button.click(timeout=5000)
    time.sleep(6)
    final_budget = read_budget(page)
    return final_budget, "已保存并读回确认"


def execute_task(context, base_url: str, task: dict, *, commit: bool, preflight: bool = False) -> dict:
    target = float(task["targetBudget"])
    try:
        wm_id = wm_poi_id(task)
    except RuntimeError:
        if not task.get("directMeituanAccountId"):
            raise
        wm_id = wm_poi_id_from_url(base_url)
        if not wm_id:
            wm_id = ""
    target_url = url_for_store(base_url, wm_id) if wm_id else base_url
    page = None
    created_page = False
    if wm_id:
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
        if preflight:
            try:
                open_budget_modal(page)
                input_box = budget_input_locator(page)
                record["beforeInput"] = input_box.input_value(timeout=3000)
                if confirm_button_locator(page) is None:
                    raise RuntimeError("预算弹窗没有确定按钮")
                close_budget_modal(page)
            except Exception as exc:
                raise RuntimeError(f"预算前预检失败：{exc}") from exc
            record["ok"] = True
            record["message"] = "预算前预检通过：点金页、预算弹窗和输入框可用，未保存修改"
            return record
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
        record["beforeInput"], record["afterInput"], record["inputAttempts"] = fill_budget_with_recovery(page, target)
        final_budget, message = confirm_budget_with_recovery(page, target)
        record["afterBudget"] = final_budget
        if final_budget is None or abs(final_budget - target) > 0.01:
            raise RuntimeError(f"保存后预算={final_budget}，目标={target}")
        record["ok"] = True
        record["message"] = message
    except Exception as exc:
        record["error"] = str(exc)
        record["failure_type"] = classify_failure(str(exc))
        if page is not None:
            record["evidence"] = save_failure_evidence(page, task, record["failure_type"])
    finally:
        if created_page:
            try:
                page.close()
            except Exception:
                pass
    return record


def execute_task_with_store_retries(context, base_url: str, task: dict, *, commit: bool, preflight: bool) -> dict:
    attempts = 1 if preflight or not commit else max(1, STORE_RETRY_ATTEMPTS)
    last_record: dict | None = None
    for attempt in range(1, attempts + 1):
        record = execute_task(context, base_url, task, commit=commit, preflight=preflight)
        record["attempt"] = attempt
        last_record = record
        if record.get("ok"):
            return record
        if record.get("failure_type") in {"auth_block", "store_mapping", "page_structure_changed"}:
            return record
        print(f"门店级重试：{task.get('keyword')} 第 {attempt}/{attempts} 次失败：{record.get('error')}", flush=True)
        time.sleep(5)
    return last_record or {"ok": False, "error": "未执行", "failure_type": "execution_failed"}


def context_for_task(
    playwright,
    contexts: dict[str, object],
    launched_contexts: list[object],
    task: dict,
    direct_accounts: dict[str, dict],
):
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
    if endpoint not in contexts and cdp_available(int(debug_port)):
        browser = playwright.chromium.connect_over_cdp(endpoint)
        contexts[endpoint] = browser.contexts[0] if browser.contexts else browser.new_context()
    if endpoint not in contexts:
        profile_dir = Path(account["profile_dir"]).expanduser()
        profile_dir.mkdir(parents=True, exist_ok=True)
        options = {
            "user_data_dir": str(profile_dir),
            "headless": os.environ.get("MEITUAN_DIRECT_BUDGET_HEADLESS", "0") == "1",
            "accept_downloads": False,
            "viewport": {"width": 1440, "height": 950},
        }
        if MAC_CHROME.exists():
            options["executable_path"] = str(MAC_CHROME)
        context = playwright.chromium.launch_persistent_context(**options)
        contexts[endpoint] = context
        launched_contexts.append(context)
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


def recent_promo_url_from_page(page) -> str | None:
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


def configured_meituan_promo_url() -> str | None:
    value = os.environ.get("MEITUAN_PROMO_BASE_URL", "").strip()
    return value or None


def resolve_default_base_url() -> str:
    return configured_meituan_promo_url() or recent_meituan_promo_url() or MEITUAN_PROMO_FALLBACK_URL


def load_direct_promo_url_cache() -> dict[str, str]:
    try:
        payload = json.loads(DIRECT_PROMO_URL_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    urls = payload.get("urls") if isinstance(payload, dict) else {}
    return urls if isinstance(urls, dict) else {}


def save_direct_promo_url_cache(account_id: str, promo_url: str) -> None:
    if not account_id or not promo_url:
        return
    urls = load_direct_promo_url_cache()
    urls[account_id] = promo_url
    DIRECT_PROMO_URL_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    DIRECT_PROMO_URL_CACHE_PATH.write_text(
        json.dumps(
            {
                "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
                "urls": urls,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def open_direct_promo_url(context, account: dict) -> str:
    account_id = str(account.get("id") or "")
    page = context.new_page()
    try:
        page_url = ((account.get("pages") or {}).get("promo_balance")) or ""
        if page_url:
            page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
            for _ in range(30):
                time.sleep(1)
                promo_url = recent_promo_url_from_page(page) or recent_promo_url_from_context(context)
                if promo_url:
                    save_direct_promo_url_cache(account_id, promo_url)
                    return promo_url
        home_url = ((account.get("pages") or {}).get("home")) or "https://e.waimai.meituan.com/"
        for _ in range(2):
            page.goto(home_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(6)
            click_visible_text(page, "门店推广")
            for _ in range(18):
                time.sleep(1)
                promo_url = recent_promo_url_from_context(context)
                if promo_url:
                    save_direct_promo_url_cache(account_id, promo_url)
                    return promo_url
            page.reload(wait_until="domcontentloaded", timeout=30000)
    finally:
        try:
            page.close()
        except Exception:
            pass
    raise RuntimeError(f"直营美团账号未能打开点金推广内层页面：{account.get('id')}")


def base_url_for_task(default_base_url: str, task: dict, direct_accounts: dict[str, dict], context=None) -> str:
    account_id = task.get("directMeituanAccountId") or ""
    if not account_id:
        if context is not None:
            return recent_promo_url_from_context(context) or default_base_url
        return default_base_url
    account = direct_accounts.get(account_id)
    if context is not None:
        cached_url = recent_promo_url_from_context(context) or load_direct_promo_url_cache().get(account_id)
        if cached_url:
            return cached_url
        try:
            return open_direct_promo_url(context, account or {})
        except Exception:
            page_url = ((account or {}).get("pages") or {}).get("promo_balance")
            if page_url:
                return page_url
            raise
    page_url = ((account or {}).get("pages") or {}).get("promo_balance")
    if not page_url:
        raise RuntimeError(f"直营美团账号未配置 promo_balance 页面：{account_id}")
    return page_url


def write_run_log(output: Path, period: str, requested_period: str, mode: str, results: list[dict], *, partial: bool, preflight: bool = False) -> None:
    output.write_text(
        json.dumps(
            {
                "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
                "period": period,
                "requestedPeriod": requested_period,
                "mode": mode,
                "preflight": preflight,
                "partial": partial,
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--period", default="auto", choices=["auto", "午餐", "晚餐"])
    parser.add_argument("--mode", default="commit", choices=["preview", "commit"])
    parser.add_argument("--limit", default="all", help="执行数量；默认 all。预览时可用 1 快速验证。")
    parser.add_argument("--stores", default="", help="只执行指定门店关键词，逗号分隔，例如：第3档口,川湘府")
    parser.add_argument("--preflight", action="store_true", help="正式提交前只读预检：打开点金页、预算弹窗和输入框，但不保存。")
    args = parser.parse_args()
    period = resolve_period(args.period)
    commit = args.mode == "commit" and not args.preflight

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
    base_url = resolve_default_base_url()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    output = LOG_DIR / f"meituan_cdp_{period}_{time.strftime('%Y%m%d_%H%M%S')}.json"
    partial_output = output.with_suffix(".partial.json")
    results = []
    with sync_playwright() as playwright:
        contexts: dict[str, object] = {}
        launched_contexts: list[object] = []
        try:
            for task in tasks:
                try:
                    account_id = task.get("directMeituanAccountId") or ""
                    account_label = f" [{account_id}]" if account_id else ""
                    print(f"{task.get('keyword')} -> {task.get('targetBudget')} ({args.mode}){account_label}", flush=True)
                    context = context_for_task(playwright, contexts, launched_contexts, task, direct_accounts)
                    task_base_url = base_url_for_task(base_url, task, direct_accounts, context)
                    result = execute_task_with_store_retries(context, task_base_url, task, commit=commit, preflight=args.preflight)
                    results.append(result)
                    if not result.get("ok"):
                        print(
                            f"失败：{task.get('keyword')}：{result.get('failure_type') or 'execution_failed'}：{result.get('error')}",
                            flush=True,
                        )
                except Exception as exc:
                    results.append({
                        "store": task.get("store"),
                        "keyword": task.get("keyword"),
                        "directMeituanAccountId": task.get("directMeituanAccountId") or "",
                        "targetBudget": task.get("targetBudget"),
                        "ok": False,
                        "error": str(exc),
                        "failure_type": classify_failure(str(exc)),
                    })
                    print(f"失败：{task.get('keyword')}：{exc}", flush=True)
                finally:
                    write_run_log(partial_output, period, args.period, args.mode, results, partial=True, preflight=args.preflight)
        finally:
            for context in launched_contexts:
                try:
                    context.close()
                except Exception:
                    pass

    write_run_log(output, period, args.period, args.mode, results, partial=False, preflight=args.preflight)
    ok_count = sum(1 for item in results if item.get("ok"))
    fail_count = len(results) - ok_count
    print(f"美团预算执行日志：{output}")
    print(f"任务数：{len(results)}，成功：{ok_count}，失败：{fail_count}")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
