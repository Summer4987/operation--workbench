from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from PIL import Image

from parse_balance_ocr import build_result, merge_results, money_to_float, normalized, parse_ocr, write_outputs


ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent
OUTPUT_DIR = WORKSPACE / "outputs" / "store_inspection"
SCREEN_TOOL = ROOT / "screen_tool.swift"
OCR_TOOL = ROOT / "ocr_image.swift"
AX_TOOL = ROOT / "ax_dump.swift"
AX_PRESS_TOOL = ROOT / "ax_press.swift"
URL = "https://r.ele.me/doujin-isv-manage/index.html?__path__=accountChain/accountDetail"


def run(args: list[str], *, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(args, cwd=WORKSPACE, text=True, capture_output=capture)
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        command = " ".join(args)
        raise RuntimeError(f"{command} 失败：{detail or result.returncode}")
    return result


def open_chrome() -> None:
    script = (
        'tell application "Google Chrome"\n'
        "activate\n"
        "if (count of windows) = 0 then make new window\n"
        f'set URL of active tab of front window to "{URL}"\n'
        "end tell"
    )
    run(["osascript", "-e", script], check=False)
    run(["open", "-a", "Google Chrome", URL], check=False)


def activate_chrome() -> None:
    run(["osascript", "-e", 'tell application "Google Chrome" to activate'], check=False)
    time.sleep(0.2)


def preflight_permissions() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    test_image = OUTPUT_DIR / "permission_test.png"
    result = run(["screencapture", "-x", str(test_image)], check=False)
    if result.returncode != 0:
        raise RuntimeError(
            "一键巡检需要屏幕录制权限。请在系统设置里给 Terminal 或 Codex 开启“屏幕录制”，"
            f"当前截图失败：{(result.stderr or '').strip()}"
        )
    if test_image.exists():
        test_image.unlink()

    result = run(
        ["osascript", "-e", 'tell application "System Events" to get UI elements enabled'],
        check=False,
    )
    if "true" not in (result.stdout or "").lower():
        raise RuntimeError("一键巡检需要辅助功能权限。请在系统设置里给 Terminal 或 Codex 开启“辅助功能”。")


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


def refresh_page() -> None:
    activate_chrome()
    run(
        [
            "osascript",
            "-e",
            'tell application "Google Chrome" to reload active tab of front window',
        ],
        check=False,
    )
    time.sleep(5)


def ax_nodes() -> list[dict]:
    activate_chrome()
    result = run(["swift", str(AX_TOOL), "Chrome", "28"])
    return json.loads(result.stdout)


def node_text(node: dict) -> str:
    for key in ["title", "value", "description", "help"]:
        value = str(node.get(key, "")).strip()
        if value:
            return value
    return ""


def parse_ax_balance(nodes: list[dict]) -> dict:
    items = []
    row_indexes = [
        index
        for index, node in enumerate(nodes)
        if node.get("role") == "AXRow"
    ]
    for position, start in enumerate(row_indexes):
        row_depth = int(nodes[start].get("depth", 0))
        end = row_indexes[position + 1] if position + 1 < len(row_indexes) else len(nodes)
        segment = [
            node
            for node in nodes[start + 1:end]
            if int(node.get("depth", 0)) > row_depth
        ]
        texts = [
            node_text(node).replace("\u00a0", "").strip()
            for node in segment
            if node.get("role") in {"AXStaticText", "AXLink"}
        ]
        texts = [text for text in texts if text and text != "总店转入"]
        store_index = next(
            (index for index, text in enumerate(texts) if "POKEBEAR" in text or "熊小小" in text),
            None,
        )
        if store_index is None:
            continue
        store_id = next(
            (text for text in texts[:store_index] if re.fullmatch(r"\d{6,}", normalized(text))),
            "",
        )
        amounts = [
            amount
            for text in texts[store_index + 1:]
            if (amount := money_to_float(text)) is not None
        ]
        if not amounts:
            continue
        items.append(
            {
                "platform": "饿了么",
                "store_name": normalized(texts[store_index]),
                "store_id": normalized(store_id),
                "balance": round(float(amounts[0]), 2),
                "source": "日常Chrome辅助功能读取",
            }
        )
    return build_result(items, message="辅助功能没有读取到分店账户明细及转账表格。")


def capture_account_detail() -> dict:
    ax_result = parse_ax_balance(ax_nodes())
    if ax_result.get("items"):
        return ax_result
    return capture_page(f"eleme_balance_ocr_fallback_{int(time.time())}.png")


def click_ax_page(page: int) -> bool:
    target = {1: "left", 2: "right"}.get(page, str(page))
    result = run(["swift", str(AX_PRESS_TOOL), "Chrome", target, "400"], check=False)
    if result.returncode == 0:
        time.sleep(2.2)
        return True
    return False


def click_table_page(page: int) -> None:
    if click_ax_page(page):
        return
    image_path = screenshot(f"eleme_balance_find_page_{page}_{int(time.time())}.png")
    lines = ocr(image_path)
    candidates = []
    for line in lines:
        text = normalized(str(line.get("text", "")))
        if text != str(page):
            continue
        x = float(line.get("x", 0))
        y = float(line.get("y", 0))
        # Pagination is at the bottom of the account-detail table.
        if y <= 0.20 and 0.40 <= x <= 0.70:
            candidates.append(line)
    if not candidates:
        raise RuntimeError(f"没有找到分店账户明细第 {page} 页页码。")
    candidates.sort(key=lambda item: float(item.get("y", 0)))
    click_point(*center_point(candidates[0], image_path, screen_info()))
    time.sleep(2.2)


def find_text(lines: list[dict], text: str, *, min_y: float | None = None, max_y: float | None = None, min_x: float | None = None) -> dict | None:
    candidates = []
    for line in lines:
        value = str(line.get("text", ""))
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
        candidates.append(line)
    candidates.sort(key=lambda item: (float(item.get("width", 1)) * float(item.get("height", 1)), -float(item.get("confidence", 0))))
    return candidates[0] if candidates else None


def click_text(text: str, *, wait: float = 1.2, min_y: float | None = None, max_y: float | None = None, min_x: float | None = None) -> bool:
    image_path = screenshot(f"workflow_find_{text}_{int(time.time())}.png")
    lines = ocr(image_path)
    target = find_text(lines, text, min_y=min_y, max_y=max_y, min_x=min_x)
    if not target:
        return False
    point = center_point(target, image_path, screen_info())
    click_point(*point)
    time.sleep(wait)
    return True


def dismiss_restore_popup() -> None:
    image_path = screenshot(f"chrome_restore_popup_{int(time.time())}.png")
    lines = ocr(image_path)
    page_text = "\n".join(str(line.get("text", "")) for line in lines)
    if "要恢复页面吗" not in page_text:
        return
    info = screen_info()
    click_point(float(info["width"]) * 0.978, float(info["height"]) * 0.162)
    time.sleep(0.8)


def write_failure(message: str) -> None:
    data = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "failed",
        "message": message,
        "threshold": 100.0,
        "summary": {
            "platform_count": 1,
            "store_count": 0,
            "warning_count": 0,
            "lowest_balance": 0.0,
        },
        "items": [],
    }
    write_outputs(data)


def capture_page(name: str) -> dict:
    image_path = screenshot(name)
    lines = ocr(image_path)
    return parse_ocr(lines)


def wait_for_account_detail(timeout_seconds: int = 12) -> dict:
    deadline = time.time() + timeout_seconds
    last_result: dict | None = None
    while time.time() < deadline:
        result = capture_account_detail()
        last_result = result
        if result.get("items"):
            return result
        time.sleep(1.2)
    return last_result or capture_page("eleme_balance_wait_account_detail_final.png")


def is_correct_balance_page(result: dict) -> bool:
    return bool(result.get("items")) and any(
        item.get("source") == "日常Chrome截图识别" for item in result.get("items", [])
    )


def main() -> int:
    try:
        preflight_permissions()
        open_chrome()
        time.sleep(6)
        press_key("escape")
        time.sleep(0.5)
        dismiss_restore_popup()
        press_key("cmd0")
        time.sleep(0.3)

        first_result = wait_for_account_detail()
        if not first_result.get("items"):
            refresh_page()
            first_result = wait_for_account_detail()
        if not first_result.get("items"):
            raise RuntimeError("没有识别到“分店账户明细及转账”的余额表。请确认页面显示店铺ID、店铺名称、账户余额。")

        results = [first_result]

        if click_ax_page(2):
            second_result = capture_account_detail()
            if second_result.get("items"):
                results.append(second_result)

        if click_ax_page(1):
            back_result = capture_account_detail()
            if back_result.get("items"):
                results.append(back_result)

        if len(merge_results(results).get("items", [])) < 13 and click_ax_page(2):
            second_result = capture_account_detail()
            if second_result.get("items"):
                results.append(second_result)

        second_result = capture_page("eleme_balance_workflow_account_page2.png")
        if second_result.get("items"):
            results.append(second_result)

        click_ax_page(1)

        data = merge_results(results)
        write_outputs(data)
        if not data.get("items"):
            raise RuntimeError("截图已完成，但没有解析到门店余额。")
        summary = data["summary"]
        print(f"一键巡检完成：{summary['store_count']} 家门店，{summary['warning_count']} 家低余额，最低 {summary['lowest_balance']:.2f} 元。")
        return 0
    except Exception as exc:
        write_failure(str(exc))
        print(f"一键巡检失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
