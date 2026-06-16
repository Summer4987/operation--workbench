from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from kuailv_order_dry_run import bounds_center, detect_page_text, find_cart_entry_candidates, nearby_texts, parse_ui_nodes


ROOT = Path(__file__).resolve().parents[1]
LATEST_PATH = ROOT / "outputs" / "kuailv_order_dry_run" / "latest.json"
RELEVANT_WORDS = ["纸巾", "购物车", "进货车", "采购车", "去结算", "提交订单", "付款", "数量", "已选", "已加购", "删除", "清空"]


def load_latest() -> dict[str, Any]:
    if not LATEST_PATH.exists():
        return {}
    return json.loads(LATEST_PATH.read_text(encoding="utf-8"))


def session_dir_from_latest(data: dict[str, Any]) -> Path | None:
    adb = data.get("adb") or {}
    session = adb.get("session_dir")
    return Path(session) if session else None


def compact_node(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "text": node.get("text", ""),
        "content_desc": node.get("content_desc", ""),
        "resource_id": node.get("resource_id", ""),
        "class": node.get("class", ""),
        "clickable": node.get("clickable"),
        "bounds": node.get("bounds"),
    }


def image_size(image_path: Path) -> dict[str, int]:
    if not image_path.exists():
        return {}
    try:
        from PIL import Image
    except Exception:
        return {}
    with Image.open(image_path) as image:
        return {"width": image.size[0], "height": image.size[1]}


def node_center(node: dict[str, Any]) -> list[float]:
    center = bounds_center(tuple(node.get("bounds") or [0, 0, 0, 0]))
    return [round(center[0], 1), round(center[1], 1)]


def enrich_node(node: dict[str, Any], nodes: list[dict[str, Any]]) -> dict[str, Any]:
    center = tuple(node_center(node))
    row = compact_node(node)
    row["center"] = list(center)
    row["nearby_texts"] = nearby_texts(nodes, (float(center[0]), float(center[1])), radius_y=130, radius_x=360)[:8]
    return row


def region_clickables(nodes: list[dict[str, Any]], width: int, height: int) -> dict[str, list[dict[str, Any]]]:
    regions = {
        "top": [],
        "upper_middle": [],
        "lower_middle": [],
        "bottom_bar": [],
        "right_edge": [],
    }
    for node in nodes:
        if not node.get("clickable"):
            continue
        cx, cy = bounds_center(tuple(node["bounds"]))
        enriched = enrich_node(node, nodes)
        if cy <= height * 0.18:
            regions["top"].append(enriched)
        if height * 0.18 < cy <= height * 0.62:
            regions["upper_middle"].append(enriched)
        if height * 0.62 < cy < height * 0.90:
            regions["lower_middle"].append(enriched)
        if cy >= height * 0.88 or node["bounds"][3] >= height - 120:
            regions["bottom_bar"].append(enriched)
        if cx >= width * 0.82:
            regions["right_edge"].append(enriched)
    for key, rows in regions.items():
        rows.sort(key=lambda item: (item["bounds"][1], item["bounds"][0]))
        regions[key] = rows[:60]
    return regions


def suspect_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    words = ["返回", "关闭", "取消", "搜索", "购物车", "进货车", "采购车", "首页", "分类", "我的", "去结算", "提交订单"]
    rows = []
    for node in nodes:
        text = " ".join(str(node.get(key) or "") for key in ("text", "content_desc", "resource_id"))
        if any(word in text for word in words) or any(word in text.lower() for word in ["back", "close", "cart", "search"]):
            rows.append(compact_node(node))
    rows.sort(key=lambda item: (item["bounds"][1], item["bounds"][0]))
    return rows[:120]


def scan_bottom_colors(image_path: Path, nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not image_path.exists():
        return []
    try:
        from PIL import Image
    except Exception:
        return []

    image = Image.open(image_path).convert("RGB")
    width, height = image.size
    pixels = image.load()
    visited: set[tuple[int, int]] = set()
    candidates = []

    def is_attention_color(x: int, y: int) -> bool:
        r, g, b = pixels[x, y]
        orange = r >= 200 and 70 <= g <= 190 and b <= 110 and r - g >= 35
        red = r >= 190 and g <= 95 and b <= 95
        green = g >= 140 and r <= 120 and b <= 130
        return orange or red or green

    y_start = max(0, height - 360)
    for y in range(y_start, height, 4):
        for x in range(0, width, 4):
            if (x, y) in visited or not is_attention_color(x, y):
                continue
            stack = [(x, y)]
            component = []
            visited.add((x, y))
            while stack:
                px, py = stack.pop()
                component.append((px, py))
                for nx, ny in ((px + 4, py), (px - 4, py), (px, py + 4), (px, py - 4)):
                    if nx < 0 or nx >= width or ny < y_start or ny >= height or (nx, ny) in visited:
                        continue
                    if is_attention_color(nx, ny):
                        visited.add((nx, ny))
                        stack.append((nx, ny))
            if len(component) < 25:
                continue
            xs = [point[0] for point in component]
            ys = [point[1] for point in component]
            x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
            if x2 - x1 < 8 or y2 - y1 < 8:
                continue
            center = ((x1 + x2) / 2, (y1 + y2) / 2)
            candidates.append(
                {
                    "center": [round(center[0], 1), round(center[1], 1)],
                    "bounds": [x1, y1, x2, y2],
                    "color": list(pixels[int(center[0]), int(center[1])]),
                    "nearby_texts": nearby_texts(nodes, center, radius_y=180, radius_x=760),
                }
            )
    candidates.sort(key=lambda item: (item["bounds"][1], item["bounds"][0]))
    return candidates[:30]


def main() -> int:
    parser = argparse.ArgumentParser(description="只读分析快驴 latest/session 截图和控件树，定位底部入口与购物车线索。")
    parser.add_argument("--session-dir", default="", help="指定 session 目录；默认读取 latest.json 的 adb.session_dir")
    args = parser.parse_args()

    latest = load_latest()
    session_dir = Path(args.session_dir) if args.session_dir else session_dir_from_latest(latest)
    if not session_dir:
        print(json.dumps({"status": "missing_session", "latest_path": str(LATEST_PATH)}, ensure_ascii=False, indent=2))
        return 1
    xml_path = session_dir / "window_dump.xml"
    image_path = session_dir / "screen.png"
    xml_text = xml_path.read_text(encoding="utf-8", errors="ignore") if xml_path.exists() else ""
    nodes = parse_ui_nodes(xml_text)
    detected = detect_page_text(xml_text)
    size = image_size(image_path)
    width = int(size.get("width") or 1080)
    height = int(size.get("height") or 2400)
    bottom_nodes = [compact_node(node) for node in nodes if node["bounds"][1] >= 2100 or node["bounds"][3] >= 2200]
    clickable = [compact_node(node) for node in nodes if node.get("clickable")]
    relevant_detected = [text for text in detected if any(word in text for word in RELEVANT_WORDS)]
    summary = {
        "status": "ready",
        "latest_mode": latest.get("mode"),
        "latest_session_dir": (latest.get("adb") or {}).get("session_dir"),
        "session_dir": str(session_dir),
        "xml_exists": xml_path.exists(),
        "screen_exists": image_path.exists(),
        "screen_size": size,
        "detected_text_first_120": detected[:120],
        "relevant_detected": relevant_detected,
        "clickable_count": len(clickable),
        "clickable_first_150": clickable[:150],
        "suspect_nodes": suspect_nodes(nodes),
        "region_clickables": region_clickables(nodes, width, height),
        "bottom_nodes": bottom_nodes[:120],
        "bottom_color_candidates": scan_bottom_colors(image_path, nodes),
        "cart_entry_candidates": find_cart_entry_candidates(nodes, image_path),
        "cart_text_seen": any(any(word in text for word in ["购物车", "进货车", "采购车", "去结算", "提交订单"]) for text in detected),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
