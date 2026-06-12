from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit

from PIL import Image

from parse_balance_ocr import build_result, merge_results, money_to_float, write_outputs


ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent
OUTPUT_DIR = WORKSPACE / "outputs" / "store_inspection"
SCREEN_TOOL = ROOT / "screen_tool.swift"
OCR_TOOL = ROOT / "ocr_image.swift"
URL = "https://e.waimai.meituan.com/#https://waimaieapp.meituan.com/ad/v1/rpc"
THRESHOLD = 200.0

STORES = [
    {"name": "熊小小牛排饭POKEBEAR（安贞店）", "keyword": "安贞"},
    {"name": "熊小小牛排饭POKEBEAR（光谷店）", "keyword": "光谷"},
    {"name": "熊小小牛排饭POKEBEAR（第3档口吉祥美食城店）", "keyword": "第3档口"},
    {"name": "熊小小牛排饭POKEBEAR（双井店）", "keyword": "双井"},
    {"name": "熊小小牛排饭POKEBEAR(第5号档口川湘府美食城店)", "keyword": "川湘府"},
    {"name": "熊小小牛排饭POKEBEAR（五一广场店）", "keyword": "五一广场"},
    {"name": "熊小小牛排饭POKEBEAR（金融街店）", "keyword": "金融街"},
    {"name": "熊小小牛排饭POKEBEAR（丽泽门店）", "keyword": "丽泽"},
]

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


def run(args: list[str], *, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(args, cwd=WORKSPACE, text=True, capture_output=capture)
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"{' '.join(args)} 失败：{detail or result.returncode}")
    return result


def preflight_permissions() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    test_image = OUTPUT_DIR / "permission_test_meituan.png"
    result = run(["screencapture", "-x", str(test_image)], check=False)
    if result.returncode != 0:
        raise RuntimeError("一键巡检需要屏幕录制权限。请在系统设置里给 Terminal 或 Codex 开启“屏幕录制”。")
    if test_image.exists():
        test_image.unlink()

    result = run(["osascript", "-e", 'tell application "System Events" to get UI elements enabled'], check=False)
    if "true" not in (result.stdout or "").lower():
        raise RuntimeError("一键巡检需要辅助功能权限。请在系统设置里给 Terminal 或 Codex 开启“辅助功能”。")


def open_chrome() -> None:
    target_url = recent_meituan_promo_url() or URL
    script = (
        'tell application "Google Chrome"\n'
        "activate\n"
        "if (count of windows) = 0 then make new window\n"
        f'set URL of active tab of front window to "{target_url}"\n'
        "end tell"
    )
    run(["osascript", "-e", script], check=False)


def chrome_history_paths() -> list[Path]:
    base = Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
    return [
        base / "Default" / "History",
        base / "Default" / "Default" / "History",
    ]


def recent_meituan_promo_url() -> str | None:
    query = """
        select url
        from urls
        where url like '%waimaieapp.meituan.com/ad/v1/rpc%'
          and url like '%token=%'
          and url like '%acctId=%'
        order by last_visit_time desc
        limit 1
    """
    for history_path in chrome_history_paths():
        if not history_path.exists():
            continue
        try:
            backup = OUTPUT_DIR / f"chrome_history_{int(time.time() * 1000)}.sqlite"
            backup.write_bytes(history_path.read_bytes())
            try:
                with sqlite3.connect(str(backup)) as conn:
                    row = conn.execute(query).fetchone()
            finally:
                backup.unlink(missing_ok=True)
        except Exception:
            continue
        if not row:
            continue
        url = str(row[0])
        parsed = urlparse(url)
        if parsed.netloc.endswith("waimaieapp.meituan.com") or "waimaieapp.meituan.com/ad/v1/rpc" in url:
            return url
    return None


def wm_poi_id_for_store(store: dict) -> tuple[str, str] | tuple[None, None]:
    joined = " ".join(str(store.get(key, "")) for key in ["name", "keyword"])
    for keyword, wm_poi_id in MEITUAN_WM_POI_IDS.items():
        if keyword in joined:
            return wm_poi_id, keyword
    return None, None


def active_chrome_url() -> str:
    script = (
        'tell application "Google Chrome"\n'
        "if (count of windows) = 0 then return \"\"\n"
        "return URL of active tab of front window\n"
        "end tell"
    )
    return (run(["osascript", "-e", script], check=False).stdout or "").strip()


def wm_poi_id_from_url(url: str) -> str | None:
    urls = [url]
    fragment = urlsplit(url).fragment
    if fragment:
        urls.append(fragment)
    for candidate in urls:
        parts = urlsplit(candidate)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        wm_poi_id = query.get("wmPoiId")
        if wm_poi_id:
            return wm_poi_id
    return None


def verify_active_store(expected_wm_poi_id: str, store_name: str) -> None:
    actual = wm_poi_id_from_url(active_chrome_url())
    if actual != expected_wm_poi_id:
        raise RuntimeError(f"美团切店校验失败：{store_name} 应为 {expected_wm_poi_id}，当前页面是 {actual or '未知门店'}")


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


def promo_page_ready(lines: list[dict]) -> bool:
    return any(
        find_text(lines, text)
        for text in ["账户余额", "点金推广", "推广首页", "推广实况", "推广预算"]
    )


def wait_for_promo_page_without_reload(timeout_seconds: int = 15) -> None:
    deadline = time.time() + timeout_seconds
    last_text = ""
    while time.time() < deadline:
        _, lines = current_lines(f"meituan_promo_ready_no_reload_{int(time.time())}.png")
        last_text = "\n".join(str(line.get("text", "")) for line in lines)
        if promo_page_ready(lines):
            return
        if find_text(lines, "门店推广"):
            click_text("门店推广", wait=2.5)
            continue
        time.sleep(1)
    raise RuntimeError("切店后没有进入美团点金推广页，已停止，避免反复刷新。")


def switch_store_by_url(store: dict) -> str | None:
    wm_poi_id, keyword = wm_poi_id_for_store(store)
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
    time.sleep(6)
    try:
        wait_for_promo_page_without_reload()
        verify_active_store(wm_poi_id, store["name"])
        return keyword
    except Exception as exc:
        print(f"美团 URL 切店未生效，改用搜索切店：{exc}", flush=True)
        return None


def activate_chrome() -> None:
    run(["osascript", "-e", 'tell application "Google Chrome" to activate'], check=False)
    time.sleep(0.2)


def screen_info() -> dict:
    result = run(["swift", str(SCREEN_TOOL), "info"])
    return json.loads(result.stdout)


def screenshot(name: str) -> Path:
    activate_chrome()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / name
    run(["screencapture", "-x", str(path)])
    return path


def ocr(image_path: Path) -> list[dict]:
    result = run(["swift", str(OCR_TOOL), str(image_path)])
    ocr_path = image_path.with_suffix(".ocr.json")
    ocr_path.write_text(result.stdout, encoding="utf-8")
    return json.loads(result.stdout)


def image_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.size


def center_point(line: dict, image_path: Path, info: dict) -> tuple[float, float]:
    image_width, image_height = image_size(image_path)
    scale_x = image_width / float(info["width"])
    scale_y = image_height / float(info["height"])
    center_x_px = (float(line["x"]) + float(line["width"]) / 2) * image_width
    center_y_px = (1 - float(line["y"]) - float(line["height"]) / 2) * image_height
    return center_x_px / scale_x, center_y_px / scale_y


def click_point(x: float, y: float) -> None:
    activate_chrome()
    run(["swift", str(SCREEN_TOOL), "click", f"{x:.1f}", f"{y:.1f}"])


def press_key(key: str) -> None:
    activate_chrome()
    run(["swift", str(SCREEN_TOOL), "key", key])


def run_with_input(args: list[str], text: str) -> None:
    result = subprocess.run(args, cwd=WORKSPACE, input=text, text=True, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "").strip())


def paste_keyword(text: str) -> None:
    activate_chrome()
    run_with_input(["pbcopy"], text)
    run(["osascript", "-e", 'tell application "System Events" to keystroke "a" using command down'], capture=False)
    run(["osascript", "-e", 'tell application "System Events" to keystroke "v" using command down'], capture=False)


def find_text(lines: list[dict], text: str, *, min_y: float | None = None, max_y: float | None = None, min_x: float | None = None) -> dict | None:
    candidates = []
    for line in lines:
        value = str(line.get("text", "")).strip()
        if text not in value:
            continue
        x = float(line.get("x", 0))
        y = float(line.get("y", 0))
        if min_y is not None and y < min_y:
            continue
        if max_y is not None and y > max_y:
            continue
        if min_x is not None and x < min_x:
            continue
        candidates.append({**line, "x": x, "y": y})
    candidates.sort(key=lambda item: (-float(item.get("confidence", 0)), float(item.get("width", 1)) * float(item.get("height", 1))))
    return candidates[0] if candidates else None


def click_text(text: str, *, wait: float = 1.0, min_y: float | None = None, max_y: float | None = None, min_x: float | None = None) -> bool:
    image_path = screenshot(f"meituan_find_{text}_{int(time.time())}.png")
    lines = ocr(image_path)
    target = find_text(lines, text, min_y=min_y, max_y=max_y, min_x=min_x)
    if not target:
        return False
    click_point(*center_point(target, image_path, screen_info()))
    time.sleep(wait)
    return True


def current_lines(name: str) -> tuple[Path, list[dict]]:
    image_path = screenshot(name)
    return image_path, ocr(image_path)


def dismiss_restore_popup() -> None:
    image_path, lines = current_lines(f"chrome_restore_popup_{int(time.time())}.png")
    page_text = "\n".join(str(line.get("text", "")) for line in lines)
    if "要恢复页面吗" not in page_text:
        return
    info = screen_info()
    click_point(float(info["width"]) * 0.978, float(info["height"]) * 0.162)
    time.sleep(0.8)


def ensure_promo_home() -> None:
    for attempt in range(3):
        open_chrome()
        time.sleep(4)
        press_key("escape")
        time.sleep(0.5)
        dismiss_restore_popup()
        _, lines = current_lines(f"meituan_promo_home_check_{attempt}.png")
        if promo_page_ready(lines):
            return
        if click_text("门店推广", wait=5.5):
            continue
        open_chrome()
        time.sleep(5)
    raise RuntimeError("没有进入美团“门店推广”的账户余额页，请确认日常 Chrome 已登录美团商家版。")


def open_store_dropdown() -> None:
    image_path, lines = current_lines(f"meituan_store_dropdown_open_{int(time.time())}.png")
    target = find_text(lines, "熊小小", min_x=0.60, min_y=0.65)
    if target:
        click_point(*center_point(target, image_path, screen_info()))
    else:
        info = screen_info()
        click_point(float(info["width"]) * 0.79, float(info["height"]) * 0.28)
    time.sleep(1)


def choose_store(keyword: str) -> None:
    open_store_dropdown()
    info = screen_info()
    click_point(float(info["width"]) * 0.765, float(info["height"]) * 0.265)
    time.sleep(0.2)
    paste_keyword(keyword)
    time.sleep(1.2)
    image_path, lines = current_lines(f"meituan_store_search_{keyword}_{int(time.time())}.png")
    candidates = []
    for line in lines:
        text = str(line.get("text", "")).strip()
        x = float(line.get("x", 0))
        y = float(line.get("y", 0))
        if x < 0.62 or y > 0.72 or y < 0.18:
            continue
        if "POKEBEAR" in text or "熊小小" in text:
            candidates.append({**line, "x": x, "y": y})
    if not candidates:
        raise RuntimeError(f"没有找到美团门店搜索结果：{keyword}")
    candidates.sort(key=lambda line: -line["y"])
    click_point(*center_point(candidates[0], image_path, screen_info()))
    time.sleep(6)


def parse_balance(lines: list[dict]) -> float | None:
    clean = []
    for line in lines:
        text = str(line.get("text", "")).strip()
        if text:
            clean.append({**line, "text": text, "x": float(line.get("x", 0)), "y": float(line.get("y", 0))})

    labels = [line for line in clean if "账户余额" in line["text"]]
    labels.sort(key=lambda line: line["x"])
    for label in labels:
        candidates = []
        for index, line in enumerate(clean):
            amount = money_to_float(line["text"])
            if amount is None:
                continue
            has_yuan = "元" in line["text"]
            if not has_yuan:
                next_lines = [
                    other for other in clean
                    if abs(other["x"] - line["x"]) <= 0.04 and 0.0 < line["y"] - other["y"] <= 0.04
                ]
                has_yuan = any("元" in other["text"] for other in next_lines)
            if not has_yuan:
                continue
            if abs(line["x"] - label["x"]) <= 0.10 and 0.015 <= label["y"] - line["y"] <= 0.085:
                candidates.append((abs(label["y"] - line["y"]), amount))
        candidates.sort(key=lambda item: item[0])
        if candidates:
            return candidates[0][1]
    return None


def inspect_store(store: dict) -> dict:
    expected_wm_poi_id, _ = wm_poi_id_for_store(store)
    used_keyword = switch_store_by_url(store)
    if used_keyword:
        wait_for_promo_page_without_reload()
    else:
        choose_store(store["keyword"])
        ensure_promo_home()
    balance = None
    for attempt in range(3):
        click_text("推广首页", wait=2.5)
        if expected_wm_poi_id:
            verify_active_store(expected_wm_poi_id, store["name"])
        _, lines = current_lines(f"meituan_balance_{store['keyword']}_{attempt}_{int(time.time())}.png")
        balance = parse_balance(lines)
        if balance is not None:
            break
        time.sleep(1.5)
    if balance is None:
        raise RuntimeError(f"没有识别到美团余额：{store['name']}")
    return {
        "platform": "美团",
        "store_name": store["name"],
        "store_id": expected_wm_poi_id or "",
        "balance": round(balance, 2),
        "status": "warning" if balance < THRESHOLD else "normal",
        "source": "日常Chrome截图识别",
    }


def write_failure(message: str) -> None:
    data = build_result([], THRESHOLD, message)
    write_outputs(data)


def main() -> int:
    try:
        preflight_permissions()
        open_chrome()
        time.sleep(7)
        press_key("escape")
        time.sleep(0.5)
        dismiss_restore_popup()
        ensure_promo_home()
        items = []
        errors = []
        for store in STORES:
            try:
                items.append(inspect_store(store))
                print(f"已识别美团余额：{store['name']}", flush=True)
            except Exception as exc:
                errors.append(str(exc))
                print(f"跳过：{exc}", file=sys.stderr, flush=True)
        data = build_result(items, THRESHOLD, "；".join(errors) if errors else "")
        write_outputs(data)
        if not items:
            raise RuntimeError(data["message"] or "美团余额巡检没有识别到任何门店。")
        summary = data["summary"]
        print(f"美团余额巡检完成：{summary['store_count']} 家门店，{summary['warning_count']} 家低余额。", flush=True)
        return 0 if not errors else 1
    except Exception as exc:
        write_failure(str(exc))
        print(f"美团余额巡检失败：{exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
