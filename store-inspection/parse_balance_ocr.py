from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
LATEST_JSON = ROOT / "latest.json"
LATEST_DATA_JS = ROOT / "latest-data.js"


def money_to_float(text: str) -> float | None:
    cleaned = text.replace(",", "").replace("￥", "").replace("¥", "").strip()
    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    if not match:
        return None
    return float(match.group(0))


def normalized(text: str) -> str:
    return re.sub(r"\s+", "", text)


def canonical_store_name(text: str) -> str:
    value = normalized(text)
    if re.search(r"第13档口|熙悦美食城|熙悦|丽泽", value):
        return "熊小小牛排饭POKEBEAR（丽泽门店）" if "熊小小" in value or "POKEBEAR" in value else "丽泽门店"
    return value


def store_key(name: str) -> str:
    key = canonical_store_name(name)
    key = key.replace("（", "(").replace("）", ")")
    key = key.replace(" ", "")
    return key


def item_key(item: dict) -> str:
    return f"{item.get('platform', '')}::{store_key(item.get('store_name', ''))}"


def build_result(items: list[dict], threshold: float = 200.0, message: str = "") -> dict:
    items = list(items)
    for item in items:
        item["store_name"] = canonical_store_name(item.get("store_name", ""))
        item["status"] = "warning" if float(item.get("balance", 0)) < threshold else "normal"
    items.sort(key=lambda item: (item["status"] != "warning", item.get("platform", ""), item["balance"], item["store_name"]))
    warning_count = sum(1 for item in items if item["status"] == "warning")
    lowest = min((float(item["balance"]) for item in items), default=0.0)
    platforms = {item.get("platform", "") for item in items if item.get("platform")}
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "ok" if items else "failed",
        "message": message if not items else "",
        "threshold": threshold,
        "summary": {
            "platform_count": len(platforms),
            "store_count": len(items),
            "warning_count": warning_count,
            "lowest_balance": round(lowest, 2),
        },
        "items": items,
    }


def parse_ocr(lines: list[dict], threshold: float = 200.0) -> dict:
    clean_lines = []
    for line in lines:
        text = str(line.get("text", "")).strip()
        if text:
            clean_lines.append({**line, "text": text, "x": float(line.get("x", 0)), "y": float(line.get("y", 0))})

    balance_header = next((line for line in clean_lines if "余额" in line["text"] and "元" in line["text"]), None)
    balance_x = float(balance_header["x"]) if balance_header else 0.70
    id_header = next((line for line in clean_lines if "店铺ID" in line["text"]), None)
    id_x = float(id_header["x"]) if id_header else 0.44

    items = []
    store_lines = [line for line in clean_lines if "POKEBEAR" in line["text"] or "熊小小" in line["text"]]
    for store_line in store_lines:
        y = store_line["y"]
        nearby = [line for line in clean_lines if abs(line["y"] - y) <= 0.018]
        store_name = store_line["text"]

        id_candidates = [
            line for line in nearby
            if re.fullmatch(r"\d{6,}", normalized(line["text"])) and abs(line["x"] - id_x) <= 0.08
        ]
        id_candidates.sort(key=lambda line: abs(line["x"] - id_x))
        store_id = normalized(id_candidates[0]["text"]) if id_candidates else ""

        balance_candidates = []
        for line in nearby:
            amount = money_to_float(line["text"])
            if amount is None:
                continue
            if abs(line["x"] - balance_x) <= 0.08:
                balance_candidates.append((abs(line["x"] - balance_x), amount))
        balance_candidates.sort(key=lambda item: item[0])
        if not store_name or not balance_candidates:
            continue

        balance = balance_candidates[0][1]
        items.append(
            {
                "platform": "饿了么",
                "store_name": normalized(store_name),
                "store_id": store_id,
                "balance": balance,
                "status": "warning" if balance < threshold else "normal",
                "source": "日常Chrome截图识别",
            }
        )

    deduped = {}
    for item in items:
        name_key = store_key(item["store_name"])
        existing = deduped.get(name_key)
        if not existing:
            deduped[name_key] = item
            continue
        if not existing.get("store_id") and item.get("store_id"):
            deduped[name_key] = item
    items = list(deduped.values())
    return build_result(items, threshold, "截图识别没有解析到门店余额，请确认页面停留在分店账户余额表。")


def write_outputs(data: dict) -> None:
    LATEST_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LATEST_DATA_JS.write_text(
        "window.INSPECTION_DATA = " + json.dumps(data, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8",
    )


def merge_results(results: list[dict], threshold: float = 200.0) -> dict:
    items_by_store = {}
    for result in results:
        for item in result.get("items", []):
            key = item_key(item)
            if not key:
                continue
            existing = items_by_store.get(key)
            if not existing:
                items_by_store[key] = item
                continue
            if not existing.get("store_id") and item.get("store_id"):
                items_by_store[key] = item
    return build_result(list(items_by_store.values()), threshold, "截图识别没有解析到门店余额，请确认页面停留在分店账户余额表。")


def main() -> int:
    if len(sys.argv) < 2:
        print("用法：parse_balance_ocr.py ocr.json [ocr2.json ...]", file=sys.stderr)
        return 2
    results = []
    for path in sys.argv[1:]:
        lines = json.loads(Path(path).read_text(encoding="utf-8"))
        results.append(parse_ocr(lines))
    data = merge_results(results)
    write_outputs(data)
    print(f"识别完成：{data['summary']['store_count']} 家门店，{data['summary']['warning_count']} 家低余额。")
    return 0 if data["items"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
