from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from kuailv_order_dry_run import (
    ADB_COMMON_PATHS,
    CHANNEL,
    DEFAULT_SERVER,
    DEFAULT_TOKEN,
    analyze_cart_review_xml,
    bounds_center,
    build_line_plan,
    detect_page_text,
    eligible_orders,
    is_product_detail_page,
    node_text,
    parse_ui_nodes,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "kuailv_adb_ranked_candidates"
LATEST_PATH = OUTPUT_DIR / "latest.json"


EXCLUDED_TITLE_WORDS = [
    "搜索",
    "购物车",
    "去结算",
    "合计",
    "全选",
    "加入购物车",
    "选规格",
    "月售",
    "买过",
    "同品",
    "低价",
    "配送",
    "首页",
    "冻品",
    "分类",
    "推荐",
    "全部",
    "销量第",
    "回购率第",
    "口碑好货",
    "新鲜蔬菜",
    "热销精选",
    "蔬菜豆制品",
    "肉禽水产蛋",
]


def now_text() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S%z")


def run_command(args: list[str], timeout: int) -> dict[str, Any]:
    try:
        result = subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)
        return {"args": args, "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
    except Exception as exc:
        return {"args": args, "returncode": -1, "stdout": "", "stderr": str(exc)}


def adb_executable() -> str:
    env_path = os.environ.get("ANDROID_ADB_BIN", "").strip()
    candidates = [Path(env_path)] if env_path else []
    found = shutil.which("adb")
    if found:
        candidates.append(Path(found))
    candidates.extend(ADB_COMMON_PATHS)
    for candidate in candidates:
        if candidate and candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return "adb"


def adb_base(serial: str) -> list[str]:
    base = [adb_executable()]
    if serial:
        base.extend(["-s", serial])
    return base


def read_json_url(url: str, timeout: int) -> dict[str, Any]:
    import urllib.parse
    import urllib.request

    request = urllib.request.Request(url, headers={"User-Agent": "kuailv-adb-ranked-candidate-capture/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def admin_summary_url(server: str, token: str) -> str:
    import urllib.parse

    query = urllib.parse.urlencode({"status": "all", "token": token})
    return f"{server.rstrip('/')}/daily-order/api/admin/summary?{query}"


def load_order(server: str, token: str, date_text: str, order_id: str, timeout: int) -> dict[str, Any]:
    payload = read_json_url(admin_summary_url(server, token), timeout)
    candidates = eligible_orders(payload, date_text, order_id)
    if not candidates:
        suffix = f"订单 {order_id}" if order_id else f"{date_text} 的快驴订单"
        raise RuntimeError(f"没有找到{suffix}。")
    return candidates[0]


def kuailv_items(order: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in order.get("items") or [] if str(item.get("purchase_channel") or "") == CHANNEL]


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def visible_nodes(xml_text: str) -> list[dict[str, Any]]:
    rows = []
    for node in parse_ui_nodes(xml_text):
        text = node_text(node)
        bounds = node.get("bounds") or []
        if not text or len(bounds) != 4:
            continue
        if bounds == [0, 0, 0, 0] or bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
            continue
        rows.append(node)
    rows.sort(key=lambda item: (item["bounds"][1], item["bounds"][0]))
    return rows


def looks_like_title(text: str, bounds: list[int]) -> bool:
    x1, y1, x2, y2 = bounds
    if not (40 <= x1 <= 650 and 250 <= y1 <= 2120 and x2 - x1 >= 90):
        return False
    if not re.search(r"[\u4e00-\u9fff]", text):
        return False
    if any(word in text for word in EXCLUDED_TITLE_WORDS):
        return False
    if "¥" in text or "￥" in text or re.fullmatch(r"\d+(?:\.\d+)?", text):
        return False
    if re.fullmatch(r"[\d.]+(?:斤|kg|g|克|袋|盒|箱|桶|瓶|个).*", normalize_text(text)):
        return False
    return True


def row_texts(nodes: list[dict[str, Any]], y1: int, y2: int) -> list[dict[str, Any]]:
    rows = []
    for node in nodes:
        bounds = node.get("bounds") or []
        if len(bounds) != 4:
            continue
        _cx, cy = bounds_center(tuple(bounds))
        if y1 <= cy <= y2 and 20 <= bounds[0] <= 1060:
            rows.append({"text": node_text(node), "bounds": bounds})
    rows.sort(key=lambda item: (item["bounds"][1], item["bounds"][0]))
    return rows


def parse_price(texts: list[str]) -> float:
    joined = " ".join(texts)
    match = re.search(r"[¥￥]\s*(\d+(?:\.\d+)?)", joined)
    if match:
        return float(match.group(1))
    for index, text in enumerate(texts[:-1]):
        if text in {"¥", "￥"} and re.fullmatch(r"\d+(?:\.\d+)?", texts[index + 1]):
            return float(texts[index + 1])
    return 0.0


def parse_sales(texts: list[str]) -> float:
    joined = " ".join(texts)
    match = re.search(r"月售\s*(\d+(?:\.\d+)?)(万)?\+?", joined)
    if not match:
        return 0.0
    value = float(match.group(1))
    return value * 10000 if match.group(2) else value


def parse_spec(title: str, texts: list[str]) -> str:
    for text in texts:
        if text == title:
            continue
        if any(word in text for word in ["¥", "￥", "月售", "买过", "同品", "低价", "选规格", "加入购物车"]):
            continue
        if re.search(r"\d", text) and any(unit in text for unit in ["斤", "kg", "g", "克", "袋", "盒", "箱", "桶", "瓶", "个"]):
            return text
    return ""


def infer_line_name(title: str, query: str, order: dict[str, Any] | None, explicit: str) -> str:
    if explicit:
        return explicit
    if not order:
        return ""
    haystack = normalize_text(f"{title} {query}")
    for item in kuailv_items(order):
        line = build_line_plan(item)
        terms = [line.get("name"), *(line.get("search_terms") or []), *(line.get("required_keywords") or [])]
        if any(normalize_text(term) and normalize_text(term) in haystack for term in terms):
            return str(line.get("name") or "")
    return ""


def allowed_title_terms(query: str, order: dict[str, Any] | None, line_name: str) -> list[str]:
    terms = [query, line_name]
    if order:
        for item in kuailv_items(order):
            line = build_line_plan(item)
            if line_name and line.get("name") != line_name:
                continue
            names = [line.get("name"), *(line.get("search_terms") or []), *(line.get("required_keywords") or [])]
            if not line_name and query:
                compact_query = normalize_text(query)
                compact_names = [normalize_text(name) for name in names if name]
                if not any(name and (name in compact_query or compact_query in name) for name in compact_names):
                    continue
            terms.extend(str(name) for name in names if name)
    return list(dict.fromkeys(normalize_text(term) for term in terms if normalize_text(term)))


def extract_candidates(
    xml_text: str,
    query: str,
    sort_mode: str,
    search_page: int,
    order: dict[str, Any] | None,
    line_name: str,
) -> list[dict[str, Any]]:
    nodes = visible_nodes(xml_text)
    title_terms = allowed_title_terms(query, order, line_name)
    titles = [node for node in nodes if looks_like_title(node_text(node), node["bounds"])]
    titles.sort(key=lambda item: (item["bounds"][1], item["bounds"][0]))
    candidates: list[dict[str, Any]] = []
    seen_titles: set[tuple[str, int]] = set()
    for index, title_node in enumerate(titles):
        title = node_text(title_node)
        compact_title = normalize_text(title)
        if title_terms and not any(term and term in compact_title for term in title_terms):
            continue
        y1 = max(0, int(title_node["bounds"][1]) - 80)
        next_y = int(titles[index + 1]["bounds"][1]) - 40 if index + 1 < len(titles) else int(title_node["bounds"][1]) + 360
        y2 = min(2300, max(next_y, int(title_node["bounds"][3]) + 160))
        rows = row_texts(nodes, y1, y2)
        texts = [row["text"] for row in rows]
        spec = parse_spec(title, texts)
        price = parse_price(texts)
        sales = parse_sales(texts)
        key = (title, int(title_node["bounds"][1] / 30))
        if key in seen_titles:
            continue
        seen_titles.add(key)
        inferred_line = infer_line_name(title, query, order, line_name)
        if not inferred_line and order:
            continue
        candidates.append(
            {
                "line_name": inferred_line,
                "query": query,
                "sort_mode": sort_mode,
                "search_page": search_page,
                "title": title,
                "spec": spec,
                "price": price,
                "monthly_sales": sales,
                "available": True,
                "source": "adb_xml_visible_search_page",
                "bounds": title_node["bounds"],
                "row_texts": texts[:28],
            }
        )
    return candidates[:30]


def capture_snapshot(serial: str, timeout: int) -> dict[str, Any]:
    session = datetime.now().strftime("%Y%m%d-%H%M%S")
    session_dir = OUTPUT_DIR / session
    session_dir.mkdir(parents=True, exist_ok=True)
    base = adb_base(serial)
    commands = []
    commands.append(run_command(base + ["shell", "uiautomator", "dump", "/sdcard/window_dump.xml"], timeout))
    commands.append(run_command(base + ["pull", "/sdcard/window_dump.xml", str(session_dir / "window_dump.xml")], timeout))
    commands.append(run_command(base + ["shell", "screencap", "-p", "/sdcard/kuailv_adb_ranked_candidates.png"], timeout))
    commands.append(run_command(base + ["pull", "/sdcard/kuailv_adb_ranked_candidates.png", str(session_dir / "screen.png")], timeout))
    xml_path = session_dir / "window_dump.xml"
    return {
        "session_dir": str(session_dir),
        "xml_path": str(xml_path),
        "screen_path": str(session_dir / "screen.png"),
        "commands": commands,
        "xml_text": xml_path.read_text(encoding="utf-8", errors="ignore") if xml_path.exists() else "",
    }


def build_payload(
    xml_text: str,
    query: str,
    sort_mode: str,
    search_page: int,
    order: dict[str, Any] | None,
    line_name: str,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cart_details = analyze_cart_review_xml(xml_text, None)
    if cart_details.get("reached_cart"):
        return {
            "generated_at": now_text(),
            "status": "blocked",
            "message": "当前识别为购物车页/结算检查页，拒绝抽取搜索候选；请先回到搜索结果页并切换排序。",
            "capture": {
                "query": query,
                "sort_mode": sort_mode,
                "search_page": search_page,
                "line_name": line_name,
                "source": "adb_xml",
                "snapshot_dir": (snapshot or {}).get("session_dir", ""),
                "screen": (snapshot or {}).get("screen_path", ""),
            },
            "summary": {"candidate_count": 0},
            "cart_review_details": {
                "keyword_hits": cart_details.get("keyword_hits"),
                "marker_hits": cart_details.get("marker_hits"),
                "visible_cart_items": cart_details.get("visible_cart_items"),
            },
            "items": [],
        }
    nodes = parse_ui_nodes(xml_text)
    if is_product_detail_page(nodes, detect_page_text(xml_text)):
        return {
            "generated_at": now_text(),
            "status": "blocked",
            "message": "当前识别为商品详情页，拒绝抽取搜索候选；请先返回搜索结果页并切换排序。",
            "capture": {
                "query": query,
                "sort_mode": sort_mode,
                "search_page": search_page,
                "line_name": line_name,
                "source": "adb_xml",
                "snapshot_dir": (snapshot or {}).get("session_dir", ""),
                "screen": (snapshot or {}).get("screen_path", ""),
            },
            "summary": {"candidate_count": 0},
            "items": [],
        }
    candidates = extract_candidates(xml_text, query, sort_mode, search_page, order, line_name)
    return {
        "generated_at": now_text(),
        "status": "ready" if candidates else "needs_review",
        "message": "已从当前安卓 XML 抽取可见快驴候选；未点击、未加购、未提交、未付款。",
        "capture": {
            "query": query,
            "sort_mode": sort_mode,
            "search_page": search_page,
            "line_name": line_name,
            "source": "adb_xml",
            "snapshot_dir": (snapshot or {}).get("session_dir", ""),
            "screen": (snapshot or {}).get("screen_path", ""),
        },
        "summary": {
            "candidate_count": len(candidates),
        },
        "items": candidates,
    }


def write_latest(payload: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LATEST_PATH.chmod(0o644)


def print_summary(payload: dict[str, Any]) -> None:
    print(payload["message"])
    print(f"状态：{payload['status']} / {payload['summary']}")
    for item in payload.get("items") or []:
        print(f"- {item.get('line_name') or '-'}: {item.get('title')} {item.get('spec') or ''} ¥{item.get('price')} 月售{item.get('monthly_sales')}")
    print(f"结果文件：{LATEST_PATH}")


def main() -> int:
    parser = argparse.ArgumentParser(description="从当前快驴安卓搜索结果页 XML 抽取排序候选；只读，不点击。")
    parser.add_argument("--server", default=DEFAULT_SERVER)
    parser.add_argument("--token", default=DEFAULT_TOKEN)
    parser.add_argument("--date", default=datetime.now().astimezone().strftime("%Y-%m-%d"))
    parser.add_argument("--order-id", default="")
    parser.add_argument("--line-name", default="")
    parser.add_argument("--query", required=True)
    parser.add_argument("--sort-mode", required=True, choices=["price_asc", "sales_desc", "default"])
    parser.add_argument("--search-page", type=int, default=1)
    parser.add_argument("--xml-file", default="", help="离线 XML 文件；为空时从 ADB 现场采集")
    parser.add_argument("--adb-serial", default=os.environ.get("ANDROID_ADB_SERIAL", ""))
    parser.add_argument("--timeout", type=int, default=25)
    args = parser.parse_args()

    try:
        order = load_order(args.server, args.token, args.date, args.order_id, args.timeout) if args.order_id or args.date else None
        snapshot = None
        if args.xml_file:
            xml_text = Path(args.xml_file).read_text(encoding="utf-8", errors="ignore")
        else:
            snapshot = capture_snapshot(args.adb_serial.strip(), args.timeout)
            xml_text = snapshot.get("xml_text") or ""
        payload = build_payload(xml_text, args.query.strip(), args.sort_mode, max(1, args.search_page), order, args.line_name.strip(), snapshot)
        write_latest(payload)
        print_summary(payload)
        return 0 if payload["status"] in {"ready", "needs_review"} else 1
    except Exception as exc:
        payload = {
            "generated_at": now_text(),
            "status": "failed",
            "message": f"快驴安卓候选抽取失败：{exc}",
        }
        write_latest(payload)
        print(payload["message"])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
