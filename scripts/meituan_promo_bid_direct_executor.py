from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STORE_INSPECTION = ROOT / "store-inspection"
if str(STORE_INSPECTION) not in sys.path:
    sys.path.insert(0, str(STORE_INSPECTION))


OUTPUT_DIR = ROOT / "outputs" / "promo_bid_direct_executor"
LATEST_PATH = OUTPUT_DIR / "latest.json"

AUTH_WORDS = ("登录", "验证码", "安全验证", "扫码登录", "验证中心", "身份核实", "拖动滑块")

_MEITUAN_HELPERS_LOADED = False


def require_meituan_helpers() -> None:
    global _MEITUAN_HELPERS_LOADED
    if _MEITUAN_HELPERS_LOADED:
        return
    try:
        from meituan_budget_cdp import (  # noqa: PLC0415
            base_url_for_task as imported_base_url_for_task,
            classify_failure as imported_classify_failure,
            context_for_task as imported_context_for_task,
            enter_dianjin_with_recovery as imported_enter_dianjin_with_recovery,
            click_visible_text as imported_click_visible_text,
            load_direct_meituan_accounts as imported_load_direct_meituan_accounts,
            page_text as imported_page_text,
            save_failure_evidence as imported_save_failure_evidence,
            sync_playwright as imported_sync_playwright,
            wait_setting_ready as imported_wait_setting_ready,
        )
    except ModuleNotFoundError as exc:
        if exc.name == "playwright":
            raise RuntimeError("当前运行环境缺少 Playwright 依赖，暂时不能打开美团后台执行改价。") from exc
        raise
    globals().update(
        {
            "base_url_for_task": imported_base_url_for_task,
            "classify_failure": imported_classify_failure,
            "context_for_task": imported_context_for_task,
            "enter_dianjin_with_recovery": imported_enter_dianjin_with_recovery,
            "click_visible_text": imported_click_visible_text,
            "load_direct_meituan_accounts": imported_load_direct_meituan_accounts,
            "page_text": imported_page_text,
            "save_failure_evidence": imported_save_failure_evidence,
            "sync_playwright": imported_sync_playwright,
            "wait_setting_ready": imported_wait_setting_ready,
        }
    )
    _MEITUAN_HELPERS_LOADED = True


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def write_latest(payload: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LATEST_PATH.chmod(0o600)


def compact(value: str) -> str:
    return "".join(str(value or "").lower().split())


def match_account(store: str, accounts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    needle = compact(store)
    candidates = []
    for account in accounts.values():
        values = [
            account.get("id", ""),
            account.get("name", ""),
            account.get("meituan_store_name", ""),
            account.get("keyword", ""),
            *(account.get("stores") or []),
        ]
        joined = compact(" ".join(str(value) for value in values))
        if needle and needle in joined:
            candidates.append(account)
            continue
        if any(compact(value) and compact(value) in needle for value in values):
            candidates.append(account)
    if not candidates:
        known = "、".join(
            str(account.get("stores", [""])[0] or account.get("keyword") or account.get("id"))
            for account in accounts.values()
        )
        raise RuntimeError(f"没有找到美团门店账号配置：{store}。已配置：{known}")
    return candidates[0]


def parse_money(text: str) -> float | None:
    match = re.search(r"-?\d+(?:\.\d+)?", str(text or "").replace(",", ""))
    return float(match.group(0)) if match else None


def read_bid_snapshot(page) -> dict[str, Any]:
    text = page_text(page)
    range_match = re.search(r"当前最终出价范围为\s*([0-9.]+)~([0-9.]+)元", text)
    bid_candidates = []
    for pattern in [
        r"(?:门店出价|当前出价|最终出价|推广出价)\s*([0-9.]+)\s*元",
        r"出价[^\n0-9]{0,12}([0-9.]+)\s*元",
    ]:
        for match in re.finditer(pattern, text):
            bid_candidates.append(float(match.group(1)))
    return {
        "range_min": float(range_match.group(1)) if range_match else None,
        "range_max": float(range_match.group(2)) if range_match else None,
        "current_bid": bid_candidates[0] if bid_candidates else None,
        "text_sample": " ".join(text.split())[:1000],
        "is_paused": "已暂停" in text,
        "budget_exhausted": "预算耗尽" in text or "预算已耗尽" in text,
    }


def enter_promo_settings(page) -> None:
    def ready() -> bool:
        text = page_text(page)
        return "推广出价" in text and ("每日预算" in text or "推广模式" in text)

    if ready() and "推广实况地图" not in page_text(page):
        return

    clicked = False
    for label in ["推广设置", "设置"]:
        try:
            clicked = click_visible_text(page, label)
        except Exception:
            clicked = False
        if clicked:
            break
    if clicked:
        for _ in range(12):
            time.sleep(1)
            if ready() and "推广实况地图" not in page_text(page):
                return

    current_url = page.url
    if "realtime" in current_url:
        target_url = current_url.replace("/realtime", "/setting").replace("realtime?", "setting?")
        if target_url != current_url:
            page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(5)
            if ready():
                return

    if ready():
        return
    raise RuntimeError("没有进入美团推广设置页，当前页面仍不是出价设置区域")


def active_setting_modal(page) -> dict[str, Any]:
    return page.evaluate(
        """() => {
                const visible = (el) => {
                    if (!el) return false;
                    const rect = el.getBoundingClientRect();
                    const style = getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0
                        && style.display !== 'none'
                        && style.visibility !== 'hidden';
                };
                const textOf = (el) => (el?.innerText || el?.textContent || '').replace(/\\s+/g, ' ').trim();
                const roots = [...document.querySelectorAll('[role="dialog"],[class*=modal],[class*=Modal],[class*=popover],[class*=drawer]')]
                    .filter(visible)
                    .filter((el) => {
                        const text = textOf(el);
                        const inputs = [...el.querySelectorAll('input')].filter((item) => visible(item) && !item.disabled && !item.readOnly);
                        const buttons = [...el.querySelectorAll('button,[role="button"],a')].filter(visible).map((item) => textOf(item).replace(/\\s/g, ''));
                        return inputs.length > 0 && buttons.some((item) => item === '确定') && /预算|出价/.test(text);
                    });
                const root = roots.at(-1);
                if (!root) return { kind: '', text: '', hasInput: false };
                const text = textOf(root);
                const kind = /出价/.test(text) && !/预算设置|设置预算/.test(text) ? 'bid' : /预算/.test(text) ? 'budget' : '';
                return { kind, text: text.slice(0, 1200), hasInput: true };
            }"""
    )


def modal_opened(page) -> bool:
    return active_setting_modal(page).get("kind") == "bid"


def budget_modal_opened(page) -> bool:
    return active_setting_modal(page).get("kind") == "budget"


def close_active_modal(page) -> None:
    try:
        page.keyboard.press("Escape")
        time.sleep(0.5)
    except Exception:
        pass


def dismiss_non_bid_modal(page) -> None:
    try:
        page.evaluate(
            """() => {
                const visible = (el) => {
                    if (!el) return false;
                    const rect = el.getBoundingClientRect();
                    const style = getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0
                        && style.display !== 'none'
                        && style.visibility !== 'hidden';
                };
                const textOf = (el) => (el?.innerText || el?.textContent || '').replace(/\\s+/g, ' ').trim();
                const body = document.body.innerText || '';
                if (!/计费规则|知道了/.test(body)) return false;
                const button = [...document.querySelectorAll('button,[role="button"],a')]
                    .filter(visible)
                    .find((el) => textOf(el) === '知道了' || textOf(el) === '关闭' || textOf(el) === '取消');
                if (!button) return false;
                button.click();
                return true;
            }"""
        )
        time.sleep(0.5)
    except Exception:
        pass


def click_bid_setting_row(page) -> bool:
    return bool(
        page.evaluate(
            """() => {
                const visible = (el) => {
                    if (!el) return false;
                    const rect = el.getBoundingClientRect();
                    const style = getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0
                        && style.display !== 'none'
                        && style.visibility !== 'hidden';
                };
                const textOf = (el) => (el?.innerText || el?.textContent || '').replace(/\\s+/g, ' ').trim();
                const all = [...document.querySelectorAll('div,span,button,[role="button"],a')].filter(visible);
                const label = all.find((el) => textOf(el) === '推广出价');
                if (!label) return false;
                label.scrollIntoView({ block: 'center', inline: 'center' });
                const labelRect = label.getBoundingClientRect();
                const targetY = labelRect.top + labelRect.height / 2;
                const xCandidates = [
                    window.innerWidth - 72,
                    window.innerWidth - 120,
                    labelRect.right + 320,
                    labelRect.right + 220,
                    labelRect.right + 120
                ].filter((x) => x > 0 && x < window.innerWidth - 4);
                for (const targetX of xCandidates) {
                    const target = document.elementFromPoint(targetX, targetY);
                    if (!target) continue;
                    const rowText = textOf(target.closest('div') || target);
                    if (/计费规则/.test(rowText)) continue;
                    const eventInit = {
                        bubbles: true,
                        cancelable: true,
                        view: window,
                        clientX: targetX,
                        clientY: targetY,
                        button: 0,
                        buttons: 1,
                    };
                    for (const name of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
                        const EventType = name.startsWith('pointer') ? PointerEvent : MouseEvent;
                        target.dispatchEvent(new EventType(name, eventInit));
                    }
                    if (typeof target.click === 'function') target.click();
                    return true;
                }
                return false;
            }"""
        )
    )


def open_bid_modal(page) -> None:
    if modal_opened(page):
        return
    if click_bid_setting_row(page):
        time.sleep(1.2)
        if modal_opened(page):
            return
        if budget_modal_opened(page):
            close_active_modal(page)
            raise RuntimeError("误打开了预算设置弹窗，已停止；不会把出价写进预算")
        dismiss_non_bid_modal(page)
    click_script = (
        """() => {
            const visible = (el) => {
                if (!el) return false;
                const rect = el.getBoundingClientRect();
                const style = getComputedStyle(el);
                return rect.width > 0 && rect.height > 0
                    && style.display !== 'none'
                    && style.visibility !== 'hidden';
            };
            const scoreNode = (el) => {
                let text = '';
                let node = el;
                for (let depth = 0; node && depth < 6; depth += 1, node = node.parentElement) {
                    text += '\\n' + (node.innerText || '');
                }
                let score = 0;
                if (/门店出价|当前出价|最终出价|推广出价|出价设置|设置出价/.test(text)) score += 100;
                if (/出价助手|出价模式/.test(text)) score -= 80;
                if (/当前最终出价范围/.test(text)) score += 30;
                if (getComputedStyle(el).cursor === 'pointer') score += 20;
                if (/right-wrapper|cursor|arrow|action|edit|setting/i.test(String(el.className || ''))) score += 15;
                return { score, text: text.trim().slice(0, 500) };
            };
            return [...document.querySelectorAll(
                '.isomor-cpc-fresh-right-wrapper, [class*=right-wrapper], [class*=cursor], [class*=arrow], [class*=action], [class*=edit], button, [role="button"], a'
            )]
                .filter(visible)
                .map((el, index) => {
                    const rect = el.getBoundingClientRect();
                    const scored = scoreNode(el);
                    return { index, x: rect.x + rect.width / 2, y: rect.y + rect.height / 2, ...scored };
                })
                .filter((item) => item.score > 0)
                .sort((a, b) => b.score - a.score)
                .slice(0, 12);
        }"""
    )
    candidates = page.evaluate(click_script)
    for item in candidates:
        clicked = page.evaluate(
            """(targetText) => {
                const visible = (el) => {
                    if (!el) return false;
                    const rect = el.getBoundingClientRect();
                    const style = getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0
                        && style.display !== 'none'
                        && style.visibility !== 'hidden';
                };
                const scoreNode = (el) => {
                    let text = '';
                    let node = el;
                    for (let depth = 0; node && depth < 6; depth += 1, node = node.parentElement) {
                        text += '\\n' + (node.innerText || '');
                    }
                    let score = 0;
                    if (/门店出价|当前出价|最终出价|推广出价|出价设置|设置出价/.test(text)) score += 100;
                    if (/出价助手|出价模式/.test(text)) score -= 80;
                    if (/当前最终出价范围/.test(text)) score += 30;
                    if (getComputedStyle(el).cursor === 'pointer') score += 20;
                    if (/right-wrapper|cursor|arrow|action|edit|setting/i.test(String(el.className || ''))) score += 15;
                    return { score, text: text.trim().slice(0, 500) };
                };
                const candidates = [...document.querySelectorAll(
                    '.isomor-cpc-fresh-right-wrapper, [class*=right-wrapper], [class*=cursor], [class*=arrow], [class*=action], [class*=edit], button, [role="button"], a'
                )]
                    .filter(visible)
                    .map((el) => ({ el, ...scoreNode(el) }))
                    .filter((item) => item.score > 0)
                    .sort((a, b) => b.score - a.score);
                const item = candidates.find((candidate) => candidate.text === targetText) || candidates[0];
                if (!item) return false;
                const el = item.el;
                el.scrollIntoView({ block: 'center', inline: 'center' });
                const rect = el.getBoundingClientRect();
                const eventInit = {
                    bubbles: true,
                    cancelable: true,
                    view: window,
                    clientX: rect.left + rect.width / 2,
                    clientY: rect.top + rect.height / 2,
                    button: 0,
                    buttons: 1,
                };
                for (const EventType of [PointerEvent, MouseEvent]) {
                    for (const name of EventType === PointerEvent ? ['pointerdown', 'pointerup'] : ['mousedown', 'mouseup', 'click']) {
                        el.dispatchEvent(new EventType(name, eventInit));
                    }
                }
                if (typeof el.click === 'function') el.click();
                return true;
            }""",
            item.get("text", ""),
        )
        if not clicked:
            page.mouse.click(item["x"], item["y"])
        time.sleep(1.2)
        if modal_opened(page):
            return
        if budget_modal_opened(page):
            close_active_modal(page)
            continue
        dismiss_non_bid_modal(page)
    for label in ["门店出价", "当前出价", "最终出价", "推广出价", "出价"]:
        locator = page.get_by_text(label)
        for index in range(locator.count()):
            try:
                target = locator.nth(index)
                if not target.is_visible():
                    continue
                target.scroll_into_view_if_needed(timeout=3000)
                box = target.bounding_box()
                if not box:
                    continue
                for dx in [20, 100, 200, 320, 440]:
                    page.mouse.click(box["x"] + dx, box["y"] + box["height"] / 2)
                    time.sleep(1.0)
                    if modal_opened(page):
                        return
                    if budget_modal_opened(page):
                        close_active_modal(page)
                        break
            except Exception:
                continue
    raise RuntimeError("没有打开出价设置弹窗，可能美团页面结构已变化或当前门店不允许改出价")


def bid_input_locator(page):
    modal = active_setting_modal(page)
    if modal.get("kind") != "bid":
        raise RuntimeError(f"当前打开的不是出价设置弹窗：{modal.get('kind') or 'unknown'}")
    scored = []
    for frame in page.frames:
        try:
            candidates = frame.evaluate(
                """() => [...document.querySelectorAll('input')]
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
                        const placeholder = el.getAttribute('placeholder') || '';
                        let score = 0;
                        if (/设置出价|出价设置|门店出价|推广出价/.test(text)) score += 100;
                        if (/出价/.test(placeholder)) score += 30;
                        if (el.type === 'number') score += 20;
                        if (visible) score += 10;
                        return { index, visible, score };
                    })
                    .filter((item) => item.visible)
                    .sort((a, b) => b.score - a.score)"""
            )
        except Exception:
            continue
        for item in candidates:
            scored.append((int(item.get("score") or 0), frame, int(item["index"])))
    if not scored:
        raise RuntimeError("出价弹窗里没有找到可编辑数字输入框")
    scored.sort(key=lambda item: item[0], reverse=True)
    _, frame, index = scored[0]
    return frame.locator("input").nth(index)


def set_input_value(input_box, value: float) -> tuple[str, str]:
    text = str(int(value) if value.is_integer() else value)
    before = input_box.input_value(timeout=3000)
    input_box.click(timeout=3000)
    input_box.fill("")
    input_box.type(text, delay=35)
    input_box.evaluate(
        """(el, value) => {
            const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
            if (setter) setter.call(el, value);
            else el.value = value;
            for (const eventName of ['input', 'change', 'keyup', 'blur']) {
                el.dispatchEvent(new Event(eventName, { bubbles: true }));
            }
        }""",
        text,
    )
    time.sleep(0.8)
    return before, input_box.input_value(timeout=3000)


def confirm_bid(page) -> None:
    buttons = page.get_by_role("button", name="确定")
    if buttons.count() == 0:
        raise RuntimeError("出价弹窗没有确定按钮")
    button = buttons.first
    if not button.is_enabled(timeout=3000):
        raise RuntimeError("出价弹窗确定按钮不可用，页面可能未接受目标出价")
    button.click(timeout=5000)
    time.sleep(5)
    if modal_opened(page):
        raise RuntimeError("点击确定后出价弹窗仍未关闭，可能页面校验未通过")


def run_meituan_direct_bid(store: str, target_bid: float, *, commit: bool) -> dict[str, Any]:
    result: dict[str, Any] = {
        "platform": "meituan",
        "store": store,
        "target_bid": target_bid,
        "account_id": "",
        "account_name": "",
        "mode": "commit" if commit else "preflight",
        "ok": False,
        "saved": False,
    }
    try:
        require_meituan_helpers()
        accounts = load_direct_meituan_accounts()
        account = match_account(store, accounts)
    except Exception as exc:
        result["error"] = str(exc)
        result["failure_type"] = "dependency_missing" if "Playwright" in str(exc) else "store_mapping"
        result["message"] = f"美团 {store} 出价调整失败：{exc}"
        return result
    account_id = str(account.get("id") or "")
    result["account_id"] = account_id
    result["account_name"] = account.get("name") or account_id
    task = {
        "store": store,
        "keyword": account.get("keyword") or store,
        "directMeituanAccountId": account_id,
        "targetBid": target_bid,
    }
    with sync_playwright() as playwright:
        contexts: dict[str, object] = {}
        launched_contexts: list[object] = []
        page = None
        created_page = False
        try:
            context = context_for_task(playwright, contexts, launched_contexts, task, accounts)
            base_url = base_url_for_task("", task, accounts, context)
            page = context.new_page()
            created_page = True
            page.goto(base_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(5)
            enter_dianjin_with_recovery(page, base_url)
            enter_promo_settings(page)
            wait_setting_ready(page)
            text = page_text(page)
            blocking = [word for word in AUTH_WORDS if word in text or word in page.url]
            if blocking:
                raise RuntimeError("美团页面需要人工处理：" + "、".join(blocking))
            result["before"] = read_bid_snapshot(page)
            if (
                result["before"].get("range_min") == 0
                and result["before"].get("range_max") == 0
                and (
                    result["before"].get("current_bid") == 0
                    or result["before"].get("is_paused")
                    or result["before"].get("budget_exhausted")
                )
            ):
                raise RuntimeError("美团点金推广当前出价为 0 且平台出价范围为 0~0，暂时没有开放可编辑出价弹窗。先恢复推广、预算或平台允许的出价范围后才能改出价。")
            open_bid_modal(page)
            input_box = bid_input_locator(page)
            before_input, after_input = set_input_value(input_box, target_bid)
            result["before_input"] = before_input
            result["after_input"] = after_input
            parsed_after = parse_money(after_input)
            if parsed_after is None or abs(parsed_after - target_bid) > 0.01:
                raise RuntimeError(f"输入框未变为目标出价：{after_input}")
            if not commit:
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
                result["ok"] = True
                result["message"] = "美团出价预检通过：已打开出价弹窗并填入目标价，未保存"
                return result
            confirm_bid(page)
            result["after"] = read_bid_snapshot(page)
            after_bid = result.get("after", {}).get("current_bid")
            result["saved"] = True
            if after_bid is not None and abs(float(after_bid) - target_bid) > 0.01:
                raise RuntimeError(f"保存后页面读回出价={after_bid}，目标={target_bid}")
            result["ok"] = True
            result["message"] = f"美团 {store} 出价已尝试保存为 {target_bid} 元。"
            return result
        except Exception as exc:
            result["error"] = str(exc)
            result["failure_type"] = classify_failure(str(exc))
            if page is not None:
                result["evidence"] = save_failure_evidence(page, task, result["failure_type"])
            result["message"] = f"美团 {store} 出价调整失败：{exc}"
            return result
        finally:
            if page is not None and created_page:
                try:
                    page.close()
                except Exception:
                    pass
            for context in launched_contexts:
                try:
                    context.close()
                except Exception:
                    pass


def build_payload(platform: str, store: str, target_bid: float, *, commit: bool) -> dict[str, Any]:
    generated_at = now_text()
    if platform != "meituan":
        return {
            "generated_at": generated_at,
            "status": "unsupported_platform",
            "platform": platform,
            "store": store,
            "target_bid": target_bid,
            "execution": {"attempted": False, "executed": False, "reason": "unsupported_platform"},
            "message": "目前直接出价执行器先接美团；饿了么 direct 指令还需要把现有点金预览执行器改造成单条指令入口。",
        }
    result = run_meituan_direct_bid(store, target_bid, commit=commit)
    status = "success" if result.get("ok") and result.get("saved") else "preflight_ok" if result.get("ok") else "failed"
    return {
        "generated_at": generated_at,
        "status": status,
        "platform": platform,
        "store": store,
        "target_bid": target_bid,
        "execution": {
            "attempted": True,
            "executed": bool(result.get("ok") and result.get("saved")),
            "reason": "" if result.get("ok") else result.get("failure_type") or "execution_failed",
        },
        "result": result,
        "message": result.get("message") or "美团出价执行器已运行。",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Hermes 直接推广出价执行器。")
    parser.add_argument("--platform", required=True, choices=["meituan", "eleme"])
    parser.add_argument("--store", required=True)
    parser.add_argument("--target-bid", required=True, type=float)
    parser.add_argument("--commit", action="store_true", help="真实保存到平台；不加时只做预检。")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_payload(args.platform, args.store, args.target_bid, commit=args.commit)
    write_latest(payload)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(payload["message"])
    return 0 if payload["status"] in {"success", "preflight_ok"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
