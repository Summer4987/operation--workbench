from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from one_click_meituan_balance import (
    activate_chrome,
    center_point,
    choose_store,
    click_point,
    click_text,
    current_lines,
    ensure_promo_home,
    find_text,
    open_chrome,
    paste_keyword,
    press_key,
    preflight_permissions,
    recent_meituan_promo_url,
    run,
    run_with_input,
    screen_info,
    verify_active_store,
    wait_for_promo_page_without_reload,
)


ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent
PREVIEW_PATH = WORKSPACE / "outputs" / "promo_budget_preview" / "latest.json"
LOG_DIR = WORKSPACE / "outputs" / "meituan_budget_automation"
SCREEN_TOOL = ROOT / "screen_tool.swift"

MEITUAN_WM_POI_IDS = {
    "第3档口": "30703865",
    "吉祥": "30703865",
    "川湘府": "32346101",
    "第5号": "32346101",
    "金融街": "31264210",
    "光谷": "33283802",
    "双井": "32949755",
    "第13档口": "32914406",
    "熙悦": "32914406",
    "丽泽": "32914406",
    "丽泽门店": "32914406",
    "保利中心": "32022526",
    "保利": "32022526",
    "安贞": "28944820",
    "五一广场": "32744963",
    "五一": "32744963",
}


def load_tasks(period: str, limit: int | None = None, store_filter: str = "") -> list[dict]:
    payload = json.loads(PREVIEW_PATH.read_text(encoding="utf-8"))
    key = "meituan_dinner" if period == "晚餐" else "meituan_lunch"
    tasks = [item for item in payload.get(key, []) if item.get("status") == "auto"]
    if store_filter:
        tasks = [
            item for item in tasks
            if store_filter in str(item.get("store", ""))
            or store_filter in str(item.get("keyword", ""))
            or store_filter in str(item.get("sourceStore", ""))
        ]
    return tasks[:limit] if limit else tasks


def resolve_period(period: str) -> str:
    if period in {"午餐", "晚餐"}:
        return period
    return "午餐" if datetime.now().hour < 15 else "晚餐"


def click_first_text(texts: list[str], *, wait: float = 1.0) -> str:
    for text in texts:
        if click_text(text, wait=wait):
            return text
    raise RuntimeError(f"没有找到按钮：{' / '.join(texts)}")


def keyword_candidates(task: dict) -> list[str]:
    raw_values = [
        task.get("keyword", ""),
        task.get("sourceStore", ""),
        task.get("store", ""),
    ]
    joined = " ".join(str(value) for value in raw_values)
    candidates = []
    for value in raw_values:
        text = str(value).strip()
        if text:
            candidates.append(text)
    aliases = {
        "第3档口": ["吉祥", "吉祥美食", "3档口", "第三"],
        "第13档口": ["丽泽", "丽泽门店", "熙悦", "熙悦美食", "13档口"],
        "川湘府": ["第5号", "第5", "5号档口"],
        "保利中心": ["保利"],
        "五一广场": ["五一"],
        "金融街": ["金融"],
        "光谷": ["光谷"],
        "双井": ["双井"],
        "安贞": ["安贞"],
    }
    for key, values in aliases.items():
        if key in joined:
            candidates.extend(values)
    seen = set()
    result = []
    for item in candidates:
        item = item.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def choose_store_with_fallback(task: dict) -> str:
    errors = []
    for keyword in keyword_candidates(task):
        try:
            choose_store(keyword)
            return keyword
        except Exception as exc:
            errors.append(f"{keyword}: {exc}")
    raise RuntimeError("没有找到美团门店搜索结果：" + "；".join(errors))


def wm_poi_id_for_task(task: dict) -> tuple[str, str] | tuple[None, None]:
    joined = " ".join(str(task.get(key, "")) for key in ["keyword", "sourceStore", "store"])
    for keyword, wm_poi_id in MEITUAN_WM_POI_IDS.items():
        if keyword in joined:
            return wm_poi_id, keyword
    return None, None


def url_with_wm_poi_id(url: str, wm_poi_id: str) -> str:
    parts = urlsplit(url)
    if "waimaieapp.meituan.com" in parts.fragment:
        inner = urlsplit(parts.fragment)
        inner_query = dict(parse_qsl(inner.query, keep_blank_values=True))
        inner_query["wmPoiId"] = wm_poi_id
        inner_url = urlunsplit((inner.scheme, inner.netloc, inner.path, urlencode(inner_query), inner.fragment))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, inner_url))
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["wmPoiId"] = wm_poi_id
    fragment = parts.fragment or "/index"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), fragment))


def switch_store_by_url(task: dict) -> str | None:
    wm_poi_id, keyword = wm_poi_id_for_task(task)
    if not wm_poi_id:
        return None
    base_url = recent_meituan_promo_url()
    if not base_url:
        return None
    target_url = url_with_wm_poi_id(base_url, wm_poi_id)
    script = (
        'tell application "Google Chrome"\n'
        "activate\n"
        "if (count of windows) = 0 then make new window\n"
        f'set URL of active tab of front window to "{target_url}"\n'
        "end tell"
    )
    run(["osascript", "-e", script], check=False)
    time.sleep(8)
    try:
        wait_for_promo_page_without_reload()
        verify_active_store(wm_poi_id, str(task.get("store") or task.get("sourceStore") or keyword))
        return keyword
    except Exception as exc:
        print(f"美团 URL 切店未生效，改用搜索切店：{exc}", flush=True)
        return None


def ensure_not_auto_budget_page() -> None:
    _, lines = current_lines(f"meituan_auto_budget_guard_{int(time.time())}.png")
    page_text = "\n".join(str(line.get("text", "")) for line in lines)
    if "自动提预算设置" in page_text or "自动提预算模式介绍" in page_text:
        raise RuntimeError("检测到已进入自动提预算设置页，立即停止；美团预算只能走“点金推广 > 推广预算”。")


def dismiss_blocking_popups() -> None:
    image_path, lines = current_lines(f"meituan_blocking_popup_{int(time.time())}.png")
    page_text = "\n".join(str(line.get("text", "")) for line in lines)
    info = screen_info()
    if "一键推广功能上线" in page_text:
        click_point(float(info["width"]) * 0.498, float(info["height"]) * 0.740)
        time.sleep(0.8)
        return
    close_line = find_text(lines, "×", min_x=0.55, min_y=0.35, max_y=0.75)
    if close_line and any(word in page_text for word in ["去看看", "功能上线", "弹窗"]):
        click_point(*center_point(close_line, image_path, info))
        time.sleep(0.8)


def ensure_auto_budget_is_off() -> None:
    _, lines = current_lines(f"meituan_auto_budget_off_check_{int(time.time())}.png")
    page_text = "\n".join(str(line.get("text", "")) for line in lines)
    if "自动提预算设置" in page_text or "自动提预算模式介绍" in page_text:
        raise RuntimeError("检测到已进入自动提预算设置页，立即停止。")
    compact = page_text.replace(" ", "")
    risky_words = ["自动提预算已开启", "自动提预算开启", "自动提预算开", "已开启自动提预算"]
    if any(word in compact for word in risky_words):
        raise RuntimeError("推广预算页显示自动提预算已开启，禁止保存预算。")


def page_text_from_lines(lines: list[dict]) -> str:
    return "\n".join(str(line.get("text", "")) for line in lines)


def budget_modal_has_zero_range_error() -> bool:
    _, lines = current_lines(f"meituan_budget_zero_range_{int(time.time())}.png")
    compact = page_text_from_lines(lines).replace(" ", "")
    return "0-0元" in compact or ("输入金额过高" in compact and "请输入0" in compact)


def close_budget_modal() -> None:
    press_key("escape")
    time.sleep(0.8)
    image_path, lines = current_lines(f"meituan_budget_modal_close_{int(time.time())}.png")
    if "预算设置" not in page_text_from_lines(lines):
        return
    close_line = find_text(lines, "×", min_x=0.55, min_y=0.50)
    if close_line:
        click_point(*center_point(close_line, image_path, screen_info()))
        time.sleep(0.8)


def enable_paused_promo_if_needed() -> bool:
    image_path, lines = current_lines(f"meituan_paused_promo_check_{int(time.time())}.png")
    paused_line = None
    for line in lines:
        text = str(line.get("text", "")).replace(" ", "")
        if "已暂停" in text and ("点金推广" in text or float(line.get("y", 0)) > 0.65):
            paused_line = line
            break
    if not paused_line:
        return False
    info = screen_info()
    x = min(float(info["width"]) * 0.34, (float(paused_line["x"]) + float(paused_line["width"]) + 0.035) * float(info["width"]))
    y = (1 - float(paused_line["y"]) - float(paused_line.get("height", 0)) / 2) * float(info["height"])
    click_point(x, y)
    time.sleep(2.0)
    for text in ["确定", "确认", "开启"]:
        if click_text(text, wait=1.5, min_x=0.45):
            break
    time.sleep(3.0)
    _, after_lines = current_lines(f"meituan_paused_promo_after_enable_{int(time.time())}.png")
    after_text = page_text_from_lines(after_lines).replace(" ", "")
    if "已暂停" in after_text:
        raise RuntimeError("美团提示预算范围为0-0，且点金推广仍处于暂停状态，自动开启失败。")
    return True


def recover_zero_range_budget() -> bool:
    if not budget_modal_has_zero_range_error():
        return False
    close_budget_modal()
    return enable_paused_promo_if_needed()


def money_text_to_float(text: str) -> float | None:
    cleaned = text.replace(",", "").replace("￥", "").replace("¥", "").strip()
    match = re.search(r"\d+(?:\.\d+)?", cleaned)
    return float(match.group(0)) if match else None


def current_spend(lines: list[dict]) -> float | None:
    clean = [
        {**line, "text": str(line.get("text", "")).strip(), "x": float(line.get("x", 0)), "y": float(line.get("y", 0))}
        for line in lines
        if str(line.get("text", "")).strip()
    ]
    labels = [
        line for line in clean
        if "推广花费" in line["text"] and 0.35 <= line["y"] <= 0.55
    ]
    labels.sort(key=lambda line: abs(line["x"] - 0.07))
    for label in labels:
        candidates = []
        for line in clean:
            if "元" not in line["text"]:
                continue
            amount = money_text_to_float(line["text"])
            if amount is None:
                continue
            if abs(line["x"] - label["x"]) <= 0.04 and 0.015 <= label["y"] - line["y"] <= 0.08:
                candidates.append((abs(label["y"] - line["y"]), amount))
        candidates.sort(key=lambda item: item[0])
        if candidates:
            return candidates[0][1]
    return None


def feasible_budget(target_budget: float) -> tuple[float, float | None]:
    _, lines = current_lines(f"meituan_current_spend_{int(time.time())}.png")
    spent = current_spend(lines)
    if spent is None or target_budget > spent:
        return target_budget, spent
    return float(math.ceil((spent + 0.01) / 10) * 10), spent


def click_budget_amount() -> None:
    image_path, lines = current_lines(f"meituan_budget_amount_{int(time.time())}.png")
    target = (
        find_text(lines, "预算已耗尽")
        or find_text(lines, "已消耗")
        or find_text(lines, "每日预算")
        or find_text(lines, "推广预算")
        or find_text(lines, "预算")
    )
    if not target:
        raise RuntimeError("没有识别到推广预算金额区域。")
    info = screen_info()
    if "预算已耗尽" in str(target.get("text", "")):
        x = (float(target["x"]) + float(target["width"]) * 0.78) * float(info["width"])
    else:
        x = float(info["width"]) * 0.94
    y = (1 - float(target["y"]) - float(target["height"]) / 2) * float(info["height"])
    click_point(x, y)
    time.sleep(1.0)


def open_budget_settings() -> str:
    ensure_not_auto_budget_page()
    try:
        click_budget_amount()
        ensure_not_auto_budget_page()
        return "预算金额区域"
    except Exception:
        pass
    for text in ["推广预算", "每日预算", "预算已耗尽", "已消耗"]:
        if click_text(text, wait=1.3):
            ensure_not_auto_budget_page()
            return text
    raise RuntimeError("没有找到按钮：推广预算 / 每日预算")


def run_screen_tool(*args: str) -> None:
    result = subprocess.run(["swift", str(SCREEN_TOOL), *args], cwd=WORKSPACE, text=True, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "").strip())


def type_budget_value(target_budget: float) -> None:
    run_screen_tool("key", "cmda")
    time.sleep(0.1)
    run_screen_tool("key", "backspace")
    time.sleep(0.1)
    run_with_input(["pbcopy"], str(int(target_budget)))
    run(["osascript", "-e", 'tell application "System Events" to keystroke "v" using command down'], capture=False)
    time.sleep(0.5)


def ensure_budget_value_visible(target_budget: float) -> None:
    _, lines = current_lines(f"meituan_budget_value_check_{int(time.time())}.png")
    label = find_text(lines, "每日预算") or find_text(lines, "推广预算")
    target_text = str(int(target_budget))
    matched = []
    for line in lines:
        text = str(line.get("text", "")).replace(" ", "")
        if "请输入" in text or "-" in text:
            continue
        if target_text not in text:
            continue
        if label:
            lx = float(label.get("x", 0))
            ly = float(label.get("y", 0))
            x = float(line.get("x", 0))
            y = float(line.get("y", 0))
            if 0.34 <= x <= 0.52 and x > lx and abs(y - ly) <= 0.08 and text in {target_text, f"¥{target_text}"}:
                matched.append(line)
        else:
            matched.append(line)
    if not matched:
        raise RuntimeError(f"没有确认预算输入框已显示 {int(target_budget)}，禁止保存。")


def page_budget_already_target(target_budget: float) -> bool:
    _, lines = current_lines(f"meituan_budget_target_check_{int(time.time())}.png")
    target_text = f"{int(target_budget)}元"
    joined = "\n".join(str(line.get("text", "")).replace(" ", "") for line in lines)
    has_budget_label = any(word in joined for word in ["推广预算", "页算", "预算已耗尽"])
    return has_budget_label and target_text in joined


def paste_budget_near_label(target_budget: float) -> None:
    info = screen_info()
    last_error = "没有识别到预算输入区域。"
    for attempt in range(3):
        image_path, lines = current_lines(f"meituan_budget_form_{attempt}_{int(time.time())}.png")
        label = (
            find_text(lines, "每日预算")
            or find_text(lines, "预算上限")
            or find_text(lines, "推广预算")
            or find_text(lines, "预算")
        )
        if not label:
            time.sleep(0.6)
            continue
        amount_lines = []
        clear_lines = []
        label_y = float(label.get("y", 0))
        for line in lines:
            text = str(line.get("text", "")).replace(" ", "")
            x = float(line.get("x", 0))
            y = float(line.get("y", 0))
            if ("¥" in text or text.isdigit()) and 0.42 <= x <= 0.58 and abs(y - label_y) <= 0.08:
                amount_lines.append({**line, "x": x, "y": y})
            if text in {"×", "x", "X"} and 0.60 <= x <= 0.70 and abs(y - label_y) <= 0.08:
                clear_lines.append({**line, "x": x, "y": y})
        amount_lines.sort(key=lambda item: abs(float(item["y"]) - label_y))
        clear_lines.sort(key=lambda item: abs(float(item["y"]) - label_y))
        candidate_points = [
            *[
                (
                    *center_point(line, image_path, info),
                )
                for line in amount_lines[:2]
            ],
            (
                (float(label["x"]) + 0.07) * float(info["width"]),
                (1 - float(label["y"]) + 0.04) * float(info["height"]),
            ),
            (
                (float(label["x"]) + 0.10) * float(info["width"]),
                (1 - float(label["y"]) + 0.04) * float(info["height"]),
            ),
        ]
        for x, y in candidate_points:
            click_point(x, y)
            time.sleep(0.25)
            if clear_lines:
                click_point(*center_point(clear_lines[0], image_path, info))
                time.sleep(0.2)
                click_point(x, y)
                time.sleep(0.2)
            type_budget_value(target_budget)
            try:
                ensure_budget_value_visible(target_budget)
                return
            except Exception as exc:
                last_error = str(exc)
    raise RuntimeError(last_error)


def ensure_page_budget_saved(target_budget: float) -> None:
    _, lines = current_lines(f"meituan_budget_saved_check_{int(time.time())}.png")
    target_text = f"{int(target_budget)}元"
    for line in lines:
        text = str(line.get("text", "")).replace(" ", "")
        x = float(line.get("x", 0))
        y = float(line.get("y", 0))
        if target_text in text and 0.78 <= x <= 0.95 and 0.38 <= y <= 0.58:
            return
    raise RuntimeError(f"保存后没有在推广预算区域确认 {target_text}，请人工复核。")


def execute_task(task: dict, *, commit: bool) -> dict:
    used_keyword = switch_store_by_url(task)
    if used_keyword:
        wait_for_promo_page_without_reload()
    else:
        used_keyword = choose_store_with_fallback(task)
        ensure_promo_home()
    dismiss_blocking_popups()
    ensure_not_auto_budget_page()
    opened = click_first_text(["点金推广"], wait=2.0)
    dismiss_blocking_popups()
    ensure_not_auto_budget_page()
    effective_budget, spent = feasible_budget(float(task["targetBudget"]))
    if page_budget_already_target(effective_budget):
        return {
            "ok": True,
            "platform": "美团",
            "store": task["store"],
            "keyword": used_keyword,
            "targetBudget": task["targetBudget"],
            "effectiveBudget": effective_budget,
            "currentSpend": spent,
            "openedBy": opened,
            "budgetOpenedBy": "页面已是目标预算",
            "savedBy": "无需保存",
            "committed": False,
            "noChange": True,
        }
    recovered_pause = False
    for attempt in range(2):
        budget_opened = open_budget_settings()
        ensure_not_auto_budget_page()
        ensure_auto_budget_is_off()
        time.sleep(1.5)
        try:
            paste_budget_near_label(effective_budget)
        except Exception:
            if attempt == 0 and recover_zero_range_budget():
                recovered_pause = True
                continue
            raise
        ensure_not_auto_budget_page()
        if commit:
            try:
                saved_by = click_first_text(["确定", "保存", "提交"], wait=1.5)
                time.sleep(2.5)
                ensure_page_budget_saved(effective_budget)
            except Exception:
                if page_budget_already_target(effective_budget):
                    saved_by = "页面已是目标预算，无需保存"
                    commit = False
                elif attempt == 0 and recover_zero_range_budget():
                    recovered_pause = True
                    continue
                else:
                    raise
        else:
            saved_by = "演练未保存"
        break
    else:
        raise RuntimeError("美团预算设置重试后仍未成功。")
    return {
        "ok": True,
        "platform": "美团",
        "store": task["store"],
        "keyword": used_keyword,
        "targetBudget": task["targetBudget"],
        "effectiveBudget": effective_budget,
        "currentSpend": spent,
        "openedBy": opened,
        "budgetOpenedBy": budget_opened,
        "savedBy": saved_by,
        "committed": commit,
        "recoveredPause": recovered_pause,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="美团推广预算自动初始化")
    parser.add_argument("--commit", action="store_true", help="保存预算修改")
    parser.add_argument("--limit", type=int, default=0, help="只执行前 N 家，0 表示全部")
    parser.add_argument("--period", choices=["auto", "午餐", "晚餐"], default="auto", help="执行午餐或晚餐预算；auto 按当前时间判断")
    parser.add_argument("--store", default="", help="只执行名称或关键词包含该文本的门店")
    args = parser.parse_args()
    period = resolve_period(args.period)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"meituan_budget_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    results = []
    errors = []
    try:
        preflight_permissions()
        open_chrome()
        time.sleep(6)
        ensure_promo_home()
        for task in load_tasks(period, args.limit or None, args.store):
            try:
                result = execute_task(task, commit=args.commit)
                results.append(result)
                print(f"美团预算已处理：{task['store']} -> {task['targetBudget']}", flush=True)
            except Exception as exc:
                error = {"ok": False, "store": task.get("store"), "targetBudget": task.get("targetBudget"), "error": str(exc)}
                errors.append(error)
                results.append(error)
                print(f"美团预算失败：{task.get('store')}：{exc}", file=sys.stderr, flush=True)
    finally:
        activate_chrome()
        log_path.write_text(
            json.dumps(
                {
                    "generated_at": datetime.now().isoformat(),
                    "commit": args.commit,
                    "ok": not errors,
                    "results": results,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"美团预算执行日志：{log_path}", flush=True)
    return 0 if results and not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
