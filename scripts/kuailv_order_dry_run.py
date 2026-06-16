from __future__ import annotations

import argparse
import json
import os
import random
import re
import signal
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "kuailv_order_dry_run"
LATEST_PATH = OUTPUT_DIR / "latest.json"
DEFAULT_SERVER = "http://139.155.148.169"
DEFAULT_TOKEN = "daily-order-admin"
CHANNEL = "快驴"
ADB_COMMON_PATHS = [
    Path.home() / "Library" / "Android" / "sdk" / "platform-tools" / "adb",
    Path("/opt/homebrew/bin/adb"),
    Path("/usr/local/bin/adb"),
]


PACK_RULES: dict[str, dict[str, Any]] = {
    "洋葱": {
        "pack_sizes": [20, 10, 5],
        "allowed_overage": 0,
        "keywords": ["洋葱"],
        "accept": ["洋葱"],
        "prefer": ["20斤", "10斤", "5斤"],
        "lesson": "银泰城 XML 坐标确认黄皮洋葱 20斤的标题/规格/选规格按钮在同一商品卡，40 斤需求优先按 20斤 x2。",
    },
    "白玉菇": {
        "pack_sizes": [4, 1],
        "allowed_overage": 1,
        "keywords": ["白玉菇"],
        "accept": ["白玉菇"],
        "prefer": ["4斤", "1斤"],
        "lesson": "银泰城实跑时白玉菇按 4斤规格连加；需求 15 斤可提示 4斤 x4 会超 1 斤，需要购物车复核。",
    },
    "土豆": {
        "pack_sizes": [10, 5],
        "allowed_overage": 0,
        "keywords": ["土豆"],
        "accept": ["土豆"],
        "prefer": ["10斤", "5斤"],
        "lesson": "银泰城实跑时 15/20 斤都可用 10斤和 5斤拆分；先用大规格减少重复点击。",
    },
    "圣女果": {
        "pack_sizes": [6, 5, 3],
        "allowed_overage": 1,
        "prefer_single_pack": 6,
        "keywords": ["圣女果", "小番茄"],
        "accept": ["圣女果", "小番茄"],
        "prefer": ["6斤", "整件", "销量", "回购"],
        "lesson": "银泰城实跑确认 5 斤需求可用 6斤整件款，允许超 1 斤。",
    },
    "豆腐": {
        "pack_sizes": [1],
        "allowed_overage": 0,
        "keywords": ["胆水老豆腐", "老豆腐", "豆腐"],
        "accept": ["胆水老豆腐", "老豆腐", "400g"],
        "prefer": ["其辉", "胆水老豆腐", "400g"],
        "reject": ["嫩豆腐", "5斤", "2盒", "内酯豆腐", "豆腐干", "千页豆腐"],
        "lesson": "银泰城实跑误点过“嫩豆腐 5斤 x2盒”；脚本必须把嫩豆腐、5斤、2盒列为强排除，购物车里也要复核删除。",
    },
    "胡萝卜": {
        "pack_sizes": [10, 5],
        "allowed_overage": 0,
        "keywords": ["胡萝卜"],
        "accept": ["胡萝卜"],
        "prefer": ["10斤", "5斤"],
        "lesson": "银泰城实跑前已定策略：10 斤需求先比 5斤 x2 与 10斤 x1，脚本先给两种规格候选。",
    },
    "樟树椒": {
        "pack_sizes": [5, 3, 1],
        "allowed_overage": 2,
        "keywords": ["樟树椒", "青椒"],
        "accept": ["樟树椒"],
        "prefer": ["5斤", "3斤", "1斤"],
        "reject": ["螺丝椒", "尖椒", "小米椒"],
        "lesson": "樟树椒不要直接按泛词青椒下单；青椒只作兜底搜索词，命中必须回到樟树椒。",
    },
    "大蒜": {"pack_sizes": [5, 3, 1], "allowed_overage": 2, "keywords": ["大蒜"], "accept": ["大蒜"], "prefer": ["3斤", "5斤"]},
    "玉米粒": {"pack_sizes": [1], "allowed_overage": 0, "keywords": ["玉米粒"], "accept": ["玉米粒"], "prefer": ["玉米粒"]},
    "鸡蛋": {"pack_sizes": [1], "allowed_overage": 0, "keywords": ["鸡蛋"], "accept": ["鸡蛋"], "prefer": ["360个", "箱"]},
    "大豆油": {"pack_sizes": [1], "allowed_overage": 0, "keywords": ["大豆油"], "accept": ["大豆油"], "prefer": ["桶"]},
    "薄盐生抽": {"pack_sizes": [1], "allowed_overage": 0, "keywords": ["薄盐生抽", "生抽"], "accept": ["薄盐生抽", "生抽"], "prefer": ["薄盐"]},
    "洗洁精": {"pack_sizes": [1], "allowed_overage": 0, "keywords": ["洗洁精"], "accept": ["洗洁精"], "prefer": ["桶"]},
}

EXCLUDED_KEYWORDS = ["嫩豆腐", "内酯豆腐", "豆腐干", "千页豆腐", "腐竹", "腐乳"]

LEARNED_OPERATOR_SKILLS = [
    "进入商品详情页后不要在详情页顶部硬切搜索；优先返回搜索结果页，再执行下一次搜索。",
    "购物车角标变化只能说明加购发生，不能证明商品正确；最终必须进购物车逐项核对。",
    "误加商品时优先在当前列表或购物车减回 0；如果页面焦点不稳，停止继续加购并转入购物车核对。",
    "每个搜索词最多等待短时间，超过阈值保存截图/控件树并换下一个词，避免单页长时间卡住。",
    "所有真实流程停在提交订单前；付款和提交订单永远需要人工确认。",
]

CART_REVIEW_KEYWORDS = ["购物车", "进货车", "采购车", "去结算", "结算", "合计", "删除", "清空", "全选", "编辑", "提交订单"]
CART_XML_MARKERS = ["cart-page-wrap", "cart-page", "去结算", "合计:", "全选"]
CART_RISK_WORDS = ["纸巾", "嫩豆腐", "5斤", "2盒", "胆水老豆腐", "老豆腐", "400g", "去结算", "合计", "全选"]
OTHER_PRODUCT_CONTEXT_WORDS = ["金针菇", "鸡翅", "西兰花", "樟树椒", "蟹味菇", "大豆油", "海藻沙拉", "玉米", "豆腐", "纸巾", "胡萝卜", "土豆", "白玉菇"]


@dataclass
class CommandResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str


def now_text() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S%z")


def today_text() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d")


def read_json_url(url: str, timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "kuailv-order-dry-run/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def admin_summary_url(server: str, token: str) -> str:
    query = urllib.parse.urlencode({"status": "all", "token": token})
    return f"{server.rstrip('/')}/daily-order/api/admin/summary?{query}"


def order_day(order: dict[str, Any]) -> str:
    submitted_at = str(order.get("submitted_at") or "")
    return submitted_at[:10]


def kuailv_items(order: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in order.get("items") or [] if str(item.get("purchase_channel") or "") == CHANNEL]


def eligible_orders(payload: dict[str, Any], date_text: str, order_id: str = "") -> list[dict[str, Any]]:
    orders = payload.get("orders") or []
    matched = []
    for order in orders:
        if order_id and order.get("order_id") != order_id:
            continue
        if not order_id and order_day(order) != date_text:
            continue
        if kuailv_items(order):
            matched.append(order)
    return matched


def load_order(server: str, token: str, date_text: str, order_id: str, seed: str, timeout: int) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = read_json_url(admin_summary_url(server, token), timeout)
    candidates = eligible_orders(payload, date_text, order_id)
    if not candidates:
        suffix = f"订单 {order_id}" if order_id else f"{date_text} 的快驴订单"
        raise RuntimeError(f"没有找到{suffix}。")
    if order_id:
        selected = candidates[0]
    else:
        rng = random.Random(seed or f"{date_text}-{len(candidates)}")
        selected = rng.choice(candidates)
    return payload, selected


def split_packs(quantity: float, pack_sizes: list[float], allowed_overage: float) -> tuple[list[dict[str, float]], float]:
    target = float(quantity)
    best: tuple[float, float, int, list[dict[str, float]]] | None = None

    def search(index: int, remaining: float, current: list[dict[str, float]]) -> None:
        nonlocal best
        if index >= len(pack_sizes):
            total = sum(line["pack_size"] * line["count"] for line in current)
            if total < target:
                return
            overage = total - target
            if overage > allowed_overage:
                return
            package_count = sum(int(line["count"]) for line in current)
            score = (overage, package_count, -max((line["pack_size"] for line in current), default=0))
            if best is None or score < best[:3]:
                best = (score[0], score[1], score[2], [dict(line) for line in current])
            return
        pack = float(pack_sizes[index])
        max_count = int((target + allowed_overage) // pack) + 2
        for count in range(max_count + 1):
            next_current = [dict(line) for line in current]
            if count:
                next_current.append({"pack_size": pack, "count": float(count)})
            search(index + 1, remaining - pack * count, next_current)

    search(0, target, [])
    if best:
        lines = best[3]
        return lines, sum(line["pack_size"] * line["count"] for line in lines)

    fallback_pack = float(pack_sizes[0] if pack_sizes else 1)
    count = int((target + fallback_pack - 0.000001) // fallback_pack)
    if count * fallback_pack < target:
        count += 1
    return [{"pack_size": fallback_pack, "count": float(count)}], count * fallback_pack


def format_number(value: float) -> str:
    if abs(value - int(value)) < 0.000001:
        return str(int(value))
    return f"{value:g}"


def build_line_plan(item: dict[str, Any]) -> dict[str, Any]:
    name = str(item.get("name") or "")
    quantity = float(item.get("quantity") or 0)
    unit = str(item.get("unit") or "")
    rule = PACK_RULES.get(name, {"pack_sizes": [1], "allowed_overage": 0, "keywords": [name]})
    pack_sizes = [float(v) for v in rule["pack_sizes"]]
    allowed_overage = float(rule.get("allowed_overage") or 0)
    prefer_single_pack = float(rule.get("prefer_single_pack") or 0)
    if prefer_single_pack and quantity <= prefer_single_pack <= quantity + allowed_overage:
        pack_lines, planned_quantity = [{"pack_size": prefer_single_pack, "count": 1.0}], prefer_single_pack
    else:
        pack_lines, planned_quantity = split_packs(quantity, pack_sizes, allowed_overage)
    search_terms = list(rule.get("keywords") or [name])
    accept_keywords = list(rule.get("accept") or [name.replace("（自主填写）", "")])
    reject_keywords = list(dict.fromkeys(list(rule.get("reject") or []) + (EXCLUDED_KEYWORDS if "豆腐" in name else [])))
    prefer_keywords = list(rule.get("prefer") or [])
    return {
        "sku": item.get("sku", ""),
        "name": name,
        "requested_quantity": quantity,
        "unit": unit,
        "search_terms": search_terms,
        "preferred_keyword": search_terms[0] if search_terms else name,
        "required_keywords": accept_keywords,
        "preferred_spec_keywords": prefer_keywords,
        "excluded_keywords": reject_keywords,
        "pack_strategy": [
            {
                "pack_size": line["pack_size"],
                "count": int(line["count"]),
                "label": f"{format_number(line['pack_size'])}{unit} x {int(line['count'])}",
            }
            for line in pack_lines
        ],
        "planned_quantity": planned_quantity,
        "overage": round(planned_quantity - quantity, 3),
        "action": "manual_note_only" if item.get("sku") == "MEAL-001" else "search_and_add",
        "note": item.get("note", ""),
        "learned_lesson": rule.get("lesson", ""),
        "selection_policy": [
            "商品标题或规格必须命中 required_keywords。",
            "商品标题或规格命中 excluded_keywords 时禁止加购。",
            "多个候选同时可用时，优先命中 preferred_spec_keywords 且能用最少点击满足数量的规格。",
            "需求数量与包装规格不完全匹配时，只允许在 overage 范围内略超；超出则转人工确认。",
        ],
        "cart_validation": {
            "expected_name_keywords": accept_keywords,
            "expected_quantity": planned_quantity,
            "expected_unit": unit,
            "reject_if_seen": reject_keywords,
        },
    }


def build_plan(order: dict[str, Any]) -> dict[str, Any]:
    lines = [build_line_plan(item) for item in kuailv_items(order)]
    actionable = [line for line in lines if line["action"] == "search_and_add"]
    return {
        "order_id": order.get("order_id", ""),
        "store_name": order.get("store_name", ""),
        "store_address": order.get("store_address", ""),
        "submitted_at": order.get("submitted_at", ""),
        "channel": CHANNEL,
        "line_count": len(lines),
        "actionable_line_count": len(actionable),
        "lines": lines,
        "learned_operator_skills": LEARNED_OPERATOR_SKILLS,
        "recovery_playbook": [
            "如果误进详情页：返回搜索结果页，不在详情页连续搜索。",
            "如果加错商品：先减回 0 或进购物车删除，再继续下一项。",
            "如果搜索结果没有命中 required_keywords：不要泛搜强行下单，记录 blocked_item。",
            "如果购物车出现 reject_if_seen 里的词：整单标记需要人工处理。",
        ],
        "safety": {
            "dry_run": True,
            "stop_before_submit": True,
            "forbidden_actions": ["提交订单", "付款", "自动替换缺货商品", "自动切换收货地址"],
        },
    }


def run_command(args: list[str], timeout: int) -> CommandResult:
    try:
        completed = subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)
        return CommandResult(args=args, returncode=completed.returncode, stdout=completed.stdout, stderr=completed.stderr)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout or b"").decode("utf-8", errors="ignore")
        stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode("utf-8", errors="ignore")
        return CommandResult(args=args, returncode=124, stdout=stdout, stderr=f"timeout after {timeout}s\n{stderr}".strip())


def install_process_watchdog(max_runtime: int) -> None:
    if max_runtime <= 0 or not hasattr(signal, "SIGALRM"):
        return

    def timeout_handler(_signum: int, _frame: Any) -> None:
        raise TimeoutError(f"process watchdog timeout after {max_runtime}s")

    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(max_runtime)


def adb_base(serial: str) -> list[str]:
    base = [adb_executable()]
    if serial:
        base.extend(["-s", serial])
    return base


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


def adb_available() -> bool:
    return adb_executable() != "adb" or bool(shutil.which("adb"))


def adb_devices(timeout: int) -> list[str]:
    result = run_command([adb_executable(), "devices"], timeout)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "adb devices 失败").strip())
    devices = []
    for line in result.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append(parts[0])
    return devices


def save_adb_snapshot(serial: str, session_dir: Path, timeout: int, plan: dict[str, Any]) -> dict[str, Any]:
    session_dir.mkdir(parents=True, exist_ok=True)
    snapshot: dict[str, Any] = {"captured": False, "files": {}, "errors": []}
    base = adb_base(serial)

    try:
        run_command(base + ["shell", "uiautomator", "dump", "/sdcard/window_dump.xml"], timeout)
        pull_xml = run_command(base + ["pull", "/sdcard/window_dump.xml", str(session_dir / "window_dump.xml")], timeout)
        if pull_xml.returncode == 0:
            snapshot["files"]["ui_xml"] = str(session_dir / "window_dump.xml")
    except Exception as exc:
        snapshot["errors"].append(f"控件树保存失败：{exc}")

    try:
        remote_png = "/sdcard/kuailv_order_dry_run.png"
        run_command(base + ["shell", "screencap", "-p", remote_png], timeout)
        pull_png = run_command(base + ["pull", remote_png, str(session_dir / "screen.png")], timeout)
        if pull_png.returncode == 0:
            snapshot["files"]["screen"] = str(session_dir / "screen.png")
    except Exception as exc:
        snapshot["errors"].append(f"截图保存失败：{exc}")

    xml_text = ""
    xml_path = session_dir / "window_dump.xml"
    if xml_path.exists():
        xml_text = xml_path.read_text(encoding="utf-8", errors="ignore")
    snapshot["captured"] = bool(snapshot["files"])
    snapshot["detected_text"] = detect_page_text(xml_text)
    snapshot["plan_match"] = analyze_page_against_plan(xml_text, plan)
    snapshot["ui_analysis"] = analyze_snapshot_ui(xml_text, Path(snapshot["files"].get("screen", "")), plan)
    snapshot["cart_review_details"] = analyze_cart_review_xml(xml_text)
    snapshot["cart_review_page"] = bool(snapshot["cart_review_details"].get("reached_cart"))
    snapshot["kuailv_hint_found"] = any(text in xml_text for text in ["快驴", "美团", "购物车", "搜索"])
    return snapshot


def detect_page_text(xml_text: str, limit: int = 160) -> list[str]:
    if not xml_text:
        return []
    values = re.findall(r'text="([^"]+)"', xml_text)
    values += re.findall(r'content-desc="([^"]+)"', xml_text)
    cleaned = []
    for value in values:
        value = value.strip()
        if value and value not in cleaned:
            cleaned.append(value)
    return cleaned[:limit]


def all_page_text(xml_text: str) -> list[str]:
    return detect_page_text(xml_text, limit=10000)


def parse_bounds(value: str) -> tuple[int, int, int, int] | None:
    match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", value or "")
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def bounds_center(bounds: tuple[int, int, int, int]) -> tuple[float, float]:
    x1, y1, x2, y2 = bounds
    return ((x1 + x2) / 2, (y1 + y2) / 2)


def node_text(node: dict[str, Any]) -> str:
    return " ".join(str(node.get(key) or "").strip() for key in ("text", "content_desc", "resource_id") if str(node.get(key) or "").strip())


def parse_ui_nodes(xml_text: str) -> list[dict[str, Any]]:
    if not xml_text:
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    nodes = []
    for index, elem in enumerate(root.iter("node")):
        bounds = parse_bounds(elem.attrib.get("bounds", ""))
        if not bounds:
            continue
        nodes.append(
            {
                "index": index,
                "text": elem.attrib.get("text", ""),
                "content_desc": elem.attrib.get("content-desc", ""),
                "class": elem.attrib.get("class", ""),
                "resource_id": elem.attrib.get("resource-id", ""),
                "clickable": elem.attrib.get("clickable", "") == "true",
                "bounds": list(bounds),
            }
        )
    return nodes


def nearby_texts(nodes: list[dict[str, Any]], center: tuple[float, float], radius_y: int = 140, radius_x: int = 760, limit: int = 12) -> list[dict[str, Any]]:
    cx, cy = center
    rows = []
    for node in nodes:
        text = node_text(node)
        if not text:
            continue
        bounds = tuple(node["bounds"])
        nx, ny = bounds_center(bounds)
        if abs(ny - cy) <= radius_y and abs(nx - cx) <= radius_x:
            rows.append({"text": text, "bounds": node["bounds"], "distance_y": round(abs(ny - cy), 1)})
    rows.sort(key=lambda item: (item["distance_y"], item["bounds"][1], item["bounds"][0]))
    return rows[:limit]


def candidate_text(candidate: dict[str, Any], radius: str = "nearby_texts") -> str:
    return " ".join(str(row.get("text") or "") for row in candidate.get(radius) or [])


def visible_text_nodes(nodes: list[dict[str, Any]], limit: int = 420) -> list[dict[str, Any]]:
    rows = []
    for node in nodes:
        text = node_text(node)
        bounds = tuple(node.get("bounds") or [])
        if not text or len(bounds) != 4:
            continue
        if bounds == (0, 0, 0, 0) or bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
            continue
        rows.append(
            {
                "text": text,
                "bounds": list(bounds),
                "resource_id": node.get("resource_id", ""),
                "content_desc": node.get("content_desc", ""),
                "class": node.get("class", ""),
            }
        )
    rows.sort(key=lambda item: (item["bounds"][1], item["bounds"][0]))
    return rows[:limit]


def candidate_context(nodes: list[dict[str, Any]], center: tuple[float, float]) -> list[dict[str, Any]]:
    # Include the product title above the spec row, but keep the window narrow
    # enough that the previous product's risky spec does not bleed into a target row.
    return nearby_texts(nodes, center, radius_y=360, radius_x=760)


def candidate_card_context(nodes: list[dict[str, Any]], center: tuple[float, float]) -> list[dict[str, Any]]:
    # Text controls in Kuailv product cards can be far apart vertically:
    # title, spec, and "选规格" may span more than 500 px.
    return nearby_texts(nodes, center, radius_y=760, radius_x=820, limit=28)


def add_button_card_context(nodes: list[dict[str, Any]], center: tuple[float, float]) -> list[dict[str, Any]]:
    # XML "选规格"/"加入购物车" controls often sit at the right edge of the
    # product card. Bind them to text immediately to the left and slightly below
    # the button so the next product row does not pollute the safety score.
    cx, cy = center
    rows = []
    for node in nodes:
        text = node_text(node)
        if not text:
            continue
        bounds = tuple(node["bounds"])
        nx, ny = bounds_center(bounds)
        if nx > cx + 80:
            continue
        if cy - 180 <= ny <= cy + 180 and abs(nx - cx) <= 900:
            rows.append({"text": text, "bounds": node["bounds"], "distance_y": round(abs(ny - cy), 1)})
    rows.sort(key=lambda item: (item["distance_y"], item["bounds"][1], item["bounds"][0]))
    return rows[:24]


def detect_orange_controls(image_path: Path, nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not image_path or not image_path.exists():
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

    def is_orange(x: int, y: int) -> bool:
        r, g, b = pixels[x, y]
        return r >= 210 and 85 <= g <= 185 and b <= 85 and r - g >= 45

    # Kuailv add/quantity buttons observed as orange circles on the right side.
    x_start = max(0, int(width * 0.72))
    y_start = max(0, int(height * 0.28))
    y_end = min(height, int(height * 0.965))
    for y in range(y_start, y_end, 3):
        for x in range(x_start, width - 10, 3):
            if (x, y) in visited or not is_orange(x, y):
                continue
            stack = [(x, y)]
            component = []
            visited.add((x, y))
            while stack:
                px, py = stack.pop()
                component.append((px, py))
                for nx, ny in ((px + 3, py), (px - 3, py), (px, py + 3), (px, py - 3)):
                    if nx < x_start or nx >= width or ny < y_start or ny >= y_end or (nx, ny) in visited:
                        continue
                    if is_orange(nx, ny):
                        visited.add((nx, ny))
                        stack.append((nx, ny))
            if len(component) < 80:
                continue
            xs = [point[0] for point in component]
            ys = [point[1] for point in component]
            x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
            box_width = x2 - x1 + 1
            box_height = y2 - y1 + 1
            if not (24 <= box_width <= 90 and 24 <= box_height <= 90):
                continue
            center = ((x1 + x2) / 2, (y1 + y2) / 2)
            sample = pixels[int(center[0]), int(center[1])]
            candidates.append(
                {
                    "center": [round(center[0], 1), round(center[1], 1)],
                    "bounds": [x1, y1, x2, y2],
                    "color": list(sample),
                    "nearby_texts": nearby_texts(nodes, center),
                    "context_texts": candidate_context(nodes, center),
                }
            )
    candidates.sort(key=lambda item: (item["center"][1], item["center"][0]))
    return candidates[:40]


def detect_xml_add_controls(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = []
    for node in nodes:
        text = node_text(node)
        bounds = tuple(node["bounds"])
        if bounds == (0, 0, 0, 0) or bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
            continue
        cx, cy = bounds_center(bounds)
        if not (280 <= cy <= 2325 and cx >= 700):
            continue
        if any(word in text for word in ["去结算", "提交订单", "付款", "合计", "全选", "购物车"]):
            continue
        rid = str(node.get("resource_id") or "").lower()
        reasons = []
        if any(word in text for word in ["选规格", "加入购物车", "加购物车", "加购"]):
            reasons.append("xml_add_text")
        if "activity-button" in rid and "fly-end" not in rid:
            reasons.append("xml_activity_button")
        if not reasons:
            continue
        candidates.append(
            {
                "center": [round(cx, 1), round(cy, 1)],
                "bounds": list(bounds),
                "source": "xml_add_control",
                "control_text": text,
                "nearby_texts": nearby_texts(nodes, (cx, cy), radius_y=220, radius_x=900, limit=16),
                "context_texts": add_button_card_context(nodes, (cx, cy)),
                "detection_reasons": reasons,
            }
        )
    candidates.sort(key=lambda item: (item["center"][1], item["center"][0]))
    return candidates[:40]


def dedup_add_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped = []
    by_key: dict[tuple[int, int], dict[str, Any]] = {}
    seen: set[tuple[int, int]] = set()

    def merge_text_rows(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged = list(existing or [])
        row_keys = {
            (str(row.get("text") or ""), tuple(row.get("bounds") or []))
            for row in merged
        }
        for row in incoming or []:
            key = (str(row.get("text") or ""), tuple(row.get("bounds") or []))
            if key in row_keys:
                continue
            row_keys.add(key)
            merged.append(row)
        return merged[:40]

    for candidate in candidates:
        center = candidate.get("center") or [0, 0]
        key = (int(round(float(center[0]) / 18)), int(round(float(center[1]) / 18)))
        if key in seen:
            existing = by_key[key]
            existing["nearby_texts"] = merge_text_rows(existing.get("nearby_texts") or [], candidate.get("nearby_texts") or [])
            existing["context_texts"] = merge_text_rows(existing.get("context_texts") or [], candidate.get("context_texts") or [])
            if not existing.get("source") and candidate.get("source"):
                existing["source"] = candidate.get("source")
            if not existing.get("control_text") and candidate.get("control_text"):
                existing["control_text"] = candidate.get("control_text")
            reasons = list(existing.get("detection_reasons") or [])
            for reason in candidate.get("detection_reasons") or []:
                if reason not in reasons:
                    reasons.append(reason)
            if reasons:
                existing["detection_reasons"] = reasons
            continue
        seen.add(key)
        by_key[key] = candidate
        deduped.append(candidate)
    deduped.sort(key=lambda item: (float((item.get("center") or [0, 0])[1]), float((item.get("center") or [0, 0])[0])))
    return deduped[:60]


def score_candidate_for_line(candidate: dict[str, Any], line: dict[str, Any], pack_label: str = "") -> dict[str, Any]:
    row_text = candidate_text(candidate, "nearby_texts")
    context_text = candidate_text(candidate, "context_texts")
    all_text = f"{context_text} {row_text}"
    required = [word for word in line.get("required_keywords") or [] if word]
    excluded = [word for word in line.get("excluded_keywords") or [] if word]
    preferred = [word for word in line.get("preferred_spec_keywords") or [] if word]
    row_required_hits = [word for word in required if word in row_text]
    context_required_hits = [word for word in required if word in all_text]
    row_preferred_hits = [word for word in preferred if word in row_text]
    context_preferred_hits = [word for word in preferred if word in all_text]
    excluded_hits = [word for word in excluded if word in all_text]
    allowed_identity_words = set(required + [str(line.get("name") or "")])
    other_product_hits = [word for word in OTHER_PRODUCT_CONTEXT_WORDS if word in all_text and not any(word in identity for identity in allowed_identity_words)]
    row_pack_hit = bool(pack_label and valid_pack_label_hit(row_text, pack_label))
    context_pack_hit = bool(pack_label and valid_pack_label_hit(context_text, pack_label))
    pack_hits = [pack_label] if pack_label and (row_pack_hit or context_pack_hit) else []
    identity_keywords = [word for word in required if not looks_like_spec_keyword(word)]
    identity_hits = [word for word in identity_keywords if word in all_text]
    reasons = []
    if not context_required_hits:
        reasons.append("missing_required_keyword")
    if identity_keywords and not identity_hits:
        reasons.append("missing_identity_keyword")
    if excluded_hits:
        reasons.append("excluded_keyword_seen")
    if other_product_hits:
        reasons.append("other_product_context_seen")
    if pack_label and not pack_hits:
        reasons.append("pack_label_not_in_card_context")
    allowed = not reasons
    score = 0
    score += 100 if allowed else 0
    score += 20 * len(row_required_hits)
    score += 12 * len(row_preferred_hits)
    score += 8 * len(context_preferred_hits)
    score += 5 * len(pack_hits)
    score -= 80 * len(excluded_hits)
    return {
        "allowed": allowed,
        "score": score,
        "reasons": reasons,
        "line_name": line.get("name", ""),
        "pack_label": pack_label,
        "row_text": row_text,
        "context_text": context_text,
        "row_required_hits": row_required_hits,
        "context_required_hits": context_required_hits,
        "row_preferred_hits": row_preferred_hits,
        "context_preferred_hits": context_preferred_hits,
        "identity_keywords": identity_keywords,
        "identity_hits": identity_hits,
        "excluded_hits": excluded_hits,
        "other_product_hits": other_product_hits,
        "pack_hits": pack_hits,
        "pack_label_scope": "nearby_row" if row_pack_hit else ("card_context" if context_pack_hit else ""),
        "center": candidate.get("center"),
        "bounds": candidate.get("bounds"),
    }


def looks_like_spec_keyword(word: str) -> bool:
    return bool(re.search(r"\d", word)) or word in {"斤", "盒", "箱", "桶", "瓶", "袋", "g", "kg"}


def valid_pack_label_hit(text: str, pack_label: str) -> bool:
    if not text or not pack_label:
        return False
    for match in re.finditer(re.escape(pack_label), text):
        start, end = match.span()
        prefix = text[max(0, start - 6) : start]
        suffix = text[end : min(len(text), end + 6)]
        if "同品" in prefix or "低价" in suffix:
            continue
        if end < len(text) and text[end].isdigit():
            continue
        if start > 0 and text[start - 1].isdigit():
            continue
        return True
    return False


def annotate_add_candidates(candidates: list[dict[str, Any]], plan: dict[str, Any]) -> list[dict[str, Any]]:
    annotated = []
    actionable_lines = [line for line in plan.get("lines") or [] if line.get("action") == "search_and_add"]
    for candidate in candidates:
        line_scores = []
        for line in actionable_lines:
            for pack_label in line_pack_labels(line):
                line_scores.append(score_candidate_for_line(candidate, line, pack_label))
        line_scores.sort(key=lambda item: item["score"], reverse=True)
        enriched = dict(candidate)
        enriched["line_scores"] = line_scores[:8]
        enriched["best_allowed_match"] = next((item for item in line_scores if item.get("allowed")), None)
        annotated.append(enriched)
    return annotated


def line_pack_labels(line: dict[str, Any]) -> list[str]:
    labels = [str(pack.get("label") or "").split(" x ", 1)[0] for pack in line.get("pack_strategy") or []]
    labels.extend(str(word) for word in line.get("preferred_spec_keywords") or [] if re.search(r"\d", str(word)))
    labels = list(dict.fromkeys(label for label in labels if label))
    return labels or [""]


def search_target_words(plan: dict[str, Any], query: str) -> list[str]:
    normalized_query = query.replace(" ", "")
    words = []
    for line in plan.get("lines") or []:
        if line.get("action") != "search_and_add":
            continue
        names = [str(line.get("name") or "")]
        names.extend(str(term) for term in line.get("search_terms") or [])
        names.extend(str(word) for word in line.get("required_keywords") or [])
        compact_names = [name.replace(" ", "") for name in names if name]
        if not normalized_query or not any(name and (name in normalized_query or normalized_query in name) for name in compact_names):
            continue
        words.extend(str(word) for word in line.get("required_keywords") or [] if word)
        words.extend(str(word) for word in line.get("preferred_spec_keywords") or [] if word)
    if not words and query:
        words.append(query)
    return list(dict.fromkeys(word for word in words if word))


def search_result_hits(snapshot: dict[str, Any], target_words: list[str]) -> dict[str, Any]:
    analysis = snapshot.get("ui_analysis") or {}
    candidates = analysis.get("orange_add_candidates") or []
    candidate_rows = []
    for candidate in candidates:
        text = f"{candidate_text(candidate, 'nearby_texts')} {candidate_text(candidate, 'context_texts')}"
        hits = [word for word in target_words if word and word in text]
        if hits:
            candidate_rows.append(
                {
                    "center": candidate.get("center"),
                    "bounds": candidate.get("bounds"),
                    "source": candidate.get("source"),
                    "control_text": candidate.get("control_text"),
                    "hits": hits,
                    "text": text,
                }
            )
    page_rows = []
    for text in snapshot.get("detected_text") or []:
        hits = [word for word in target_words if word and word in str(text)]
        if hits:
            page_rows.append({"text": text, "hits": hits})
    page_node_rows = []
    for node in analysis.get("visible_text_nodes") or []:
        text = str(node.get("text") or "")
        hits = [word for word in target_words if word and word in text]
        if hits:
            page_node_rows.append(
                {
                    "text": text,
                    "hits": hits,
                    "bounds": node.get("bounds"),
                    "resource_id": node.get("resource_id"),
                    "content_desc": node.get("content_desc"),
                    "class": node.get("class"),
                }
            )
    return {
        "target_words": target_words,
        "hit_count": len(candidate_rows),
        "hits": candidate_rows[:8],
        "candidate_hit_count": len(candidate_rows),
        "candidate_hits": candidate_rows[:8],
        "page_text_hit_count": len(page_rows),
        "page_text_hits": page_rows[:12],
        "page_node_hit_count": len(page_node_rows),
        "page_node_hits": page_node_rows[:20],
    }


def target_text_position(result_check: dict[str, Any]) -> dict[str, Any]:
    hits = [
        row
        for row in result_check.get("page_node_hits") or []
        if len(row.get("bounds") or []) == 4
    ]
    if not hits:
        return {}
    hits.sort(key=lambda row: (row["bounds"][1], row["bounds"][0]))
    clusters: list[list[dict[str, Any]]] = []
    for row in hits:
        if not clusters:
            clusters.append([row])
            continue
        last_bounds = clusters[-1][-1]["bounds"]
        if row["bounds"][1] - last_bounds[3] <= 360:
            clusters[-1].append(row)
        else:
            clusters.append([row])

    def cluster_score(cluster: list[dict[str, Any]]) -> float:
        texts = " ".join(str(row.get("text") or "") for row in cluster)
        bounds = [row["bounds"] for row in cluster]
        top = min(item[1] for item in bounds)
        bottom = max(item[3] for item in bounds)
        score = len(cluster) * 10
        if re.search(r"\d", texts):
            score += 25
        if any(token in texts for token in ["400g", "斤", "盒", "箱", "桶", "瓶"]):
            score += 20
        if any(token in texts for token in ["[", "]", "胆水"]):
            score += 12
        score += ((top + bottom) / 2) / 10000
        return score

    selected = max(clusters, key=cluster_score)
    bounds = [row["bounds"] for row in selected]
    top = min(item[1] for item in bounds)
    bottom = max(item[3] for item in bounds)
    return {
        "top": top,
        "bottom": bottom,
        "center_y": round((top + bottom) / 2, 1),
        "hit_count": len(selected),
        "texts": [row.get("text") for row in selected[:8]],
        "all_hit_count": len(hits),
        "cluster_count": len(clusters),
    }


def target_guided_scroll_args(result_check: dict[str, Any]) -> list[str]:
    position = target_text_position(result_check)
    if not position:
        return ["540", "1980", "540", "900", "450"]
    bottom = float(position.get("bottom") or 0)
    top = float(position.get("top") or 0)
    if bottom >= 2180:
        return ["540", "1850", "540", "1180", "360"]
    if bottom >= 1980:
        return ["540", "1780", "540", "1320", "320"]
    if 0 < top <= 620:
        return ["540", "900", "540", "1380", "320"]
    return ["540", "1980", "540", "900", "450"]


def select_safe_candidate(analysis: dict[str, Any], item_name: str, pack_label: str = "") -> dict[str, Any] | None:
    matches = []
    for candidate in analysis.get("orange_add_candidates") or []:
        for score in candidate.get("line_scores") or []:
            if not score.get("allowed"):
                continue
            if item_name and score.get("line_name") != item_name:
                continue
            if pack_label and score.get("pack_label") != pack_label:
                continue
            item = dict(score)
            item["candidate"] = {
                key: candidate.get(key)
                for key in ("center", "bounds", "color", "source", "control_text", "nearby_texts", "context_texts")
            }
            matches.append(item)
    matches.sort(key=lambda item: item.get("score", 0), reverse=True)
    return matches[0] if matches else None


def top_rejected_candidate(analysis: dict[str, Any], item_name: str, pack_label: str = "") -> dict[str, Any] | None:
    matches = []
    for candidate in analysis.get("orange_add_candidates") or []:
        for score in candidate.get("line_scores") or []:
            if score.get("allowed"):
                continue
            if item_name and score.get("line_name") != item_name:
                continue
            if pack_label and score.get("pack_label") != pack_label:
                continue
            item = dict(score)
            item["candidate"] = {
                key: candidate.get(key)
                for key in ("center", "bounds", "color", "source", "control_text", "nearby_texts", "context_texts")
            }
            matches.append(item)
    matches.sort(key=lambda item: item.get("score", 0), reverse=True)
    return matches[0] if matches else None


def safe_add_recommendations(analysis: dict[str, Any], plan: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for line in plan.get("lines") or []:
        if line.get("action") != "search_and_add":
            continue
        for pack_label in line_pack_labels(line):
            selected = select_safe_candidate(analysis, str(line.get("name") or ""), pack_label)
            rejected = None if selected else top_rejected_candidate(analysis, str(line.get("name") or ""), pack_label)
            rows.append(
                {
                    "line_name": line.get("name", ""),
                    "pack_label": pack_label,
                    "allowed": bool(selected),
                    "selected": selected,
                    "top_rejected": rejected,
                }
            )
    return rows


def extract_delivery_text(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for node in nodes:
        text = node_text(node)
        if any(keyword in text for keyword in ("配送", "送至", "地址", "银泰", "金融", "万象", "保利")):
            rows.append({"text": text, "bounds": node["bounds"]})
    return rows[:20]


def analyze_snapshot_ui(xml_text: str, image_path: Path, plan: dict[str, Any]) -> dict[str, Any]:
    nodes = parse_ui_nodes(xml_text)
    clickable = [
        {
            "text": node.get("text", ""),
            "content_desc": node.get("content_desc", ""),
            "class": node.get("class", ""),
            "resource_id": node.get("resource_id", ""),
            "bounds": node.get("bounds", []),
        }
        for node in nodes
        if node.get("clickable")
    ][:120]
    bottom_nodes = [
        {"text": node_text(node), "class": node.get("class", ""), "clickable": node.get("clickable"), "bounds": node["bounds"]}
        for node in nodes
        if node["bounds"][1] >= 2150 or node["bounds"][3] >= 2210
    ][:80]
    orange_candidates = annotate_add_candidates(dedup_add_candidates(detect_orange_controls(image_path, nodes) + detect_xml_add_controls(nodes)), plan)
    cart_entry_candidates = find_cart_entry_candidates(nodes, image_path)
    search_entry_candidates = find_search_entry_candidates(nodes, image_path)
    delivery_rows = extract_delivery_text(nodes)
    delivery_text = " ".join(row["text"] for row in delivery_rows)
    expected_store = str(plan.get("store_name") or "")
    analysis = {
        "node_count": len(nodes),
        "clickable_nodes": clickable,
        "bottom_nodes": bottom_nodes,
        "delivery_candidates": delivery_rows,
        "delivery_store_match": bool(expected_store and expected_store in delivery_text),
        "expected_store": expected_store,
        "orange_add_candidates": orange_candidates,
        "cart_entry_candidates": cart_entry_candidates,
        "search_entry_candidates": search_entry_candidates,
        "visible_text_nodes": visible_text_nodes(nodes),
        "cart_review_page": is_cart_review_page(detect_page_text(xml_text)),
    }
    analysis["safe_add_recommendations"] = safe_add_recommendations(analysis, plan)
    analysis["blocked_orange_candidates"] = [
        {
            "center": candidate.get("center"),
            "bounds": candidate.get("bounds"),
            "nearby_texts": candidate.get("nearby_texts"),
            "top_reasons": [
                {
                    "line_name": score.get("line_name"),
                    "pack_label": score.get("pack_label"),
                    "reasons": score.get("reasons"),
                    "excluded_hits": score.get("excluded_hits"),
                    "row_text": score.get("row_text"),
                }
                for score in (candidate.get("line_scores") or [])[:3]
                if not score.get("allowed")
            ],
        }
        for candidate in orange_candidates
        if not candidate.get("best_allowed_match")
    ][:20]
    return {
        **analysis,
    }


def is_cart_review_page(detected_text: list[str] | str) -> bool:
    text = detected_text if isinstance(detected_text, str) else " ".join(str(item) for item in detected_text)
    strong_hits = [word for word in CART_REVIEW_KEYWORDS if word in text]
    if any(word in text for word in CART_XML_MARKERS):
        return True
    return len(strong_hits) >= 2


def analyze_cart_review_xml(xml_text: str) -> dict[str, Any]:
    texts = all_page_text(xml_text)
    text_blob = " ".join(texts)
    keyword_hits = [word for word in CART_REVIEW_KEYWORDS if word in text_blob]
    marker_hits = [word for word in CART_XML_MARKERS if word in xml_text or word in text_blob]
    risk_hits = [word for word in CART_RISK_WORDS if word in text_blob]
    relevant_texts = [
        text
        for text in texts
        if any(word in text for word in CART_RISK_WORDS + ["¥", "￥", "去结算", "合计", "全选", "购物车"])
    ]
    nodes = parse_ui_nodes(xml_text)
    cart_nodes = extract_cart_review_nodes(nodes)
    return {
        "reached_cart": bool(marker_hits or len(keyword_hits) >= 2),
        "keyword_hits": keyword_hits,
        "marker_hits": marker_hits,
        "risk_hits": risk_hits,
        "visible_relevant_text": relevant_texts[:80],
        "cart_item_candidates": cart_nodes["cart_item_candidates"],
        "checkout_nodes": cart_nodes["checkout_nodes"],
        "background_risk_nodes": cart_nodes["background_risk_nodes"],
    }


def extract_cart_review_nodes(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    if not nodes:
        return {"cart_item_candidates": [], "checkout_nodes": [], "background_risk_nodes": []}

    max_y = max((int(node["bounds"][3]) for node in nodes), default=2400)
    control_words = ["购物车", "去结算", "结算", "合计", "全选", "删除", "清空", "编辑", "提交订单", "付款"]
    item_words = ["胆水老豆腐", "老豆腐", "400g", "嫩豆腐", "纸巾", "5斤", "2盒", "¥", "￥"]
    checkout_nodes = []
    item_candidates = []
    background_risk_nodes = []

    for node in nodes:
        text = node_text(node)
        if not text:
            continue
        bounds = node["bounds"]
        x1, y1, x2, y2 = [int(value) for value in bounds]
        if [x1, y1, x2, y2] == [0, 0, 0, 0]:
            zone = "hidden"
        elif y1 >= int(max_y * 0.88) or y2 >= int(max_y * 0.92):
            zone = "bottom_cart_review"
        elif y1 >= int(max_y * 0.72):
            zone = "lower_page"
        else:
            zone = "background_or_product_list"

        row = {
            "text": text,
            "class": node.get("class", ""),
            "clickable": node.get("clickable"),
            "resource_id": node.get("resource_id", ""),
            "bounds": bounds,
            "center": [round(value, 1) for value in bounds_center(tuple(bounds))],
            "zone": zone,
        }

        if any(word in text for word in control_words):
            checkout_nodes.append(row)
            continue

        if any(word in text for word in item_words):
            expected_hits = [word for word in ["胆水老豆腐", "老豆腐", "400g"] if word in text]
            risk_hits = [word for word in ["纸巾", "嫩豆腐", "5斤", "2盒"] if word in text]
            row["expected_hits"] = expected_hits
            row["risk_hits"] = risk_hits
            row["cart_likelihood"] = cart_node_likelihood(zone, expected_hits, risk_hits, text)
            if zone in {"bottom_cart_review", "lower_page"} and expected_hits:
                item_candidates.append(row)
            elif risk_hits:
                background_risk_nodes.append(row)

    item_candidates.sort(key=lambda item: (-int(item.get("cart_likelihood", 0)), item["bounds"][1], item["bounds"][0]))
    background_risk_nodes.sort(key=lambda item: (item["bounds"][1], item["bounds"][0]))
    checkout_nodes.sort(key=lambda item: (item["bounds"][1], item["bounds"][0]))
    return {
        "cart_item_candidates": item_candidates[:20],
        "checkout_nodes": checkout_nodes[:30],
        "background_risk_nodes": background_risk_nodes[:20],
    }


def cart_node_likelihood(zone: str, expected_hits: list[str], risk_hits: list[str], text: str) -> int:
    score = 0
    if zone == "bottom_cart_review":
        score += 45
    elif zone == "lower_page":
        score += 25
    elif zone == "hidden":
        score -= 60
    score += 20 * len(expected_hits)
    score -= 30 * len(risk_hits)
    if "¥" in text or "￥" in text:
        score += 5
    return score


def attention_color_components(image_path: Path, *, y_start_ratio: float = 0.82) -> list[dict[str, Any]]:
    if not image_path or not image_path.exists():
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

    def is_attention(x: int, y: int) -> bool:
        r, g, b = pixels[x, y]
        orange = r >= 200 and 70 <= g <= 190 and b <= 115 and r - g >= 35
        red = r >= 190 and g <= 105 and b <= 105
        green = g >= 135 and r <= 135 and b <= 135
        return orange or red or green

    y_start = max(0, int(height * y_start_ratio))
    for y in range(y_start, height, 4):
        for x in range(0, width, 4):
            if (x, y) in visited or not is_attention(x, y):
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
                    if is_attention(nx, ny):
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
            candidates.append({"center": [round(center[0], 1), round(center[1], 1)], "bounds": [x1, y1, x2, y2], "color": list(pixels[int(center[0]), int(center[1])])})
    candidates.sort(key=lambda item: (item["bounds"][1], item["bounds"][0]))
    return candidates[:40]


def find_cart_entry_candidates(nodes: list[dict[str, Any]], image_path: Path) -> list[dict[str, Any]]:
    image_width = 1080
    image_height = 2400
    try:
        from PIL import Image

        if image_path and image_path.exists():
            with Image.open(image_path) as image:
                image_width, image_height = image.size
    except Exception:
        pass

    rows: list[dict[str, Any]] = []
    bottom_clickables = [node for node in nodes if node.get("clickable") and node["bounds"][1] >= int(image_height * 0.90)]
    bottom_clickables.sort(key=lambda item: item["bounds"][0])
    for tab_position, node in enumerate(bottom_clickables, start=1):
        bounds = tuple(node["bounds"])
        cx, cy = bounds_center(bounds)
        index_guess = round(cx / (image_width / max(len(bottom_clickables), 1))) if bottom_clickables else 0
        score = 15
        reasons = ["bottom_clickable_tab"]
        if int(image_width * 0.35) <= cx <= int(image_width * 0.85):
            score += 8
            reasons.append("middle_or_right_bottom_tab")
        if len(bottom_clickables) == 5 and tab_position == 4:
            score += 35
            reasons.append("common_kuailv_cart_tab_position")
        rows.append(
            {
                "kind": "bottom_tab",
                "center": [round(cx, 1), round(cy, 1)],
                "bounds": list(bounds),
                "score": score,
                "reasons": reasons,
                "index_guess": index_guess,
                "tab_position": tab_position,
                "text": node_text(node),
            }
        )

    for node in nodes:
        text = node_text(node)
        bounds = tuple(node["bounds"])
        cx, cy = bounds_center(bounds)
        if cy < int(image_height * 0.78):
            continue
        rid = str(node.get("resource_id") or "")
        reasons = []
        score = 0
        if "cart" in rid.lower() or "shopping" in rid.lower():
            score += 80
            reasons.append("cart_like_resource_id")
        if any(word in text for word in ["购物车", "进货车", "采购车"]):
            score += 90
            reasons.append("cart_text")
        if "activity-button" in rid or "fly-end" in rid:
            score += 20
            reasons.append("floating_activity_or_fly_end")
        if re.fullmatch(r"\d{1,3}", text):
            score += 10
            reasons.append("numeric_badge")
        if not reasons:
            continue
        rows.append(
            {
                "kind": "xml_bottom_hint",
                "center": [round(cx, 1), round(cy, 1)],
                "bounds": list(bounds),
                "score": score,
                "reasons": reasons,
                "text": text,
                "clickable": node.get("clickable"),
                "resource_id": rid,
            }
        )

    for component in attention_color_components(image_path):
        cx, cy = component["center"]
        if cy < int(image_height * 0.78):
            continue
        nearby = nearby_texts(nodes, (float(cx), float(cy)), radius_y=170, radius_x=260)
        score = 8
        reasons = ["bottom_attention_color"]
        nearby_blob = " ".join(row.get("text", "") for row in nearby)
        if re.search(r"\b\d{1,3}\b", nearby_blob):
            score += 8
            reasons.append("near_numeric_badge")
        if any(word in nearby_blob for word in ["购物车", "进货车", "采购车"]):
            score += 80
            reasons.append("near_cart_text")
        rows.append(
            {
                "kind": "bottom_color",
                "center": component["center"],
                "bounds": component["bounds"],
                "score": score,
                "reasons": reasons,
                "color": component.get("color"),
                "nearby_texts": nearby,
            }
        )

    deduped = []
    seen: set[tuple[int, int]] = set()
    for row in sorted(rows, key=lambda item: item.get("score", 0), reverse=True):
        cx, cy = row.get("center") or [0, 0]
        key = (int(round(float(cx) / 12)), int(round(float(cy) / 12)))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped[:20]


def find_search_entry_candidates(nodes: list[dict[str, Any]], image_path: Path) -> list[dict[str, Any]]:
    image_width = 1080
    image_height = 2400
    try:
        from PIL import Image

        if image_path and image_path.exists():
            with Image.open(image_path) as image:
                image_width, image_height = image.size
    except Exception:
        pass

    rows = []
    forbidden_words = ["去结算", "提交订单", "付款", "合计", "全选"]
    for node in nodes:
        text = node_text(node)
        blob = f"{text} {node.get('class') or ''} {node.get('resource_id') or ''}".lower()
        bounds = tuple(node["bounds"])
        if bounds == (0, 0, 0, 0) or bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
            continue
        cx, cy = bounds_center(bounds)
        if cy > image_height * 0.45:
            continue
        if any(word in text for word in forbidden_words) or "商品介绍" in text or "desc-content" in blob:
            continue
        reasons = []
        score = 0
        if any(word in text for word in ["搜索", "请输入"]):
            score += 70
            reasons.append("search_text")
        if "search" in blob:
            score += 55
            reasons.append("search_resource_or_desc")
        if "edittext" in blob:
            score += 120
            reasons.append("edit_text")
        if node.get("clickable"):
            score += 10
            reasons.append("clickable")
        width = bounds[2] - bounds[0]
        if width >= image_width * 0.35:
            score += 45
            reasons.append("wide_input_like")
        if text.strip() == "搜索" and width < image_width * 0.22 and "edittext" not in blob:
            score -= 95
            reasons.append("small_search_submit_button")
        if cy <= image_height * 0.22:
            score += 8
            reasons.append("top_header_area")
        if not reasons or score < 50:
            continue
        rows.append(
            {
                "kind": "search_entry",
                "center": [round(cx, 1), round(cy, 1)],
                "bounds": list(bounds),
                "score": score,
                "reasons": reasons,
                "text": text,
                "clickable": node.get("clickable"),
                "class": node.get("class", ""),
                "resource_id": node.get("resource_id", ""),
            }
        )
    rows.sort(key=lambda item: (-item.get("score", 0), item["bounds"][1], item["bounds"][0]))
    deduped = []
    seen: set[tuple[int, int]] = set()
    for row in rows:
        cx, cy = row.get("center") or [0, 0]
        key = (int(round(float(cx) / 16)), int(round(float(cy) / 16)))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped[:12]


def analyze_page_against_plan(xml_text: str, plan: dict[str, Any]) -> dict[str, Any]:
    text = " ".join(detect_page_text(xml_text))
    hits = []
    risks = []
    for line in plan.get("lines") or []:
        required = [word for word in line.get("required_keywords") or [] if word]
        excluded = [word for word in line.get("excluded_keywords") or [] if word]
        matched = [word for word in required if word in text]
        blocked = [word for word in excluded if word in text]
        if matched:
            hits.append({"name": line.get("name"), "matched": matched})
        if blocked:
            risks.append({"name": line.get("name"), "blocked_keywords": blocked})
    return {
        "target_hits": hits,
        "risk_hits": risks,
        "has_search_hint": any(word in text for word in ["搜索", "请输入", "商品"]),
        "has_cart_hint": any(word in text for word in ["购物车", "去结算", "结算", "提交订单"]),
    }


def run_adb_dry_run(plan: dict[str, Any], serial: str, timeout: int) -> dict[str, Any]:
    if not adb_available():
        return {
            "status": "blocked",
            "message": "当前机器未找到 adb，无法连接安卓机；请在 Mac mini 上运行。",
            "device_serial": serial,
        }
    devices = adb_devices(timeout)
    if serial and serial not in devices:
        return {
            "status": "blocked",
            "message": f"未找到指定 adb 设备 {serial}；在线设备：{', '.join(devices) or '无'}。",
            "device_serial": serial,
        }
    if not serial:
        if len(devices) != 1:
            return {
                "status": "blocked",
                "message": f"需要指定 adb 设备；在线设备数量 {len(devices)}。",
                "devices": devices,
            }
        serial = devices[0]

    session = datetime.now().strftime("%Y%m%d-%H%M%S")
    session_dir = OUTPUT_DIR / session
    snapshot = save_adb_snapshot(serial, session_dir, timeout, plan)
    return {
        "status": "ready_for_manual_review" if snapshot.get("captured") else "blocked",
        "message": "已保存安卓截图和控件树；本轮 dry-run 不会提交订单或付款。",
        "device_serial": serial,
        "session_dir": str(session_dir),
        "snapshot": snapshot,
        "next_manual_steps": [
            "确认安卓机已打开快驴下单页且收货门店正确。",
            "按 plan.lines 的 search_terms 搜索候选商品。",
            "只选择 required_keywords 命中且 excluded_keywords 未命中的商品。",
            "若命中 learned_lesson 中提到的误加风险，先暂停并保存购物车截图。",
            "加购后进入购物车核对商品、规格、数量，提交前停止。",
        ],
    }


def resolve_adb_serial(serial: str, timeout: int) -> tuple[str, dict[str, Any] | None]:
    if not adb_available():
        return "", {
            "status": "blocked",
            "message": "当前机器未找到 adb，无法连接安卓机；请在 Mac mini 上运行。",
            "device_serial": serial,
        }
    devices = adb_devices(timeout)
    if serial and serial not in devices:
        return "", {
            "status": "blocked",
            "message": f"未找到指定 adb 设备 {serial}；在线设备：{', '.join(devices) or '无'}。",
            "device_serial": serial,
        }
    if not serial:
        if len(devices) != 1:
            return "", {
                "status": "blocked",
                "message": f"需要指定 adb 设备；在线设备数量 {len(devices)}。",
                "devices": devices,
            }
        serial = devices[0]
    return serial, None


def run_adb_safe_tap(plan: dict[str, Any], serial: str, timeout: int, item_name: str, pack_label: str) -> dict[str, Any]:
    serial, blocked = resolve_adb_serial(serial, timeout)
    if blocked:
        return blocked
    if not item_name or not pack_label:
        return {"status": "blocked", "message": "safe-tap 需要同时指定 --tap-item 和 --tap-pack。", "device_serial": serial}

    session = datetime.now().strftime("%Y%m%d-%H%M%S-safe-tap")
    session_dir = OUTPUT_DIR / session
    before_dir = session_dir / "before"
    after_dir = session_dir / "after"
    before = save_adb_snapshot(serial, before_dir, timeout, plan)
    analysis = before.get("ui_analysis") or {}
    if not before.get("captured"):
        return {"status": "blocked", "message": "safe-tap 前截图/控件树采集失败，未点击。", "device_serial": serial, "session_dir": str(session_dir), "before": before}
    if not analysis.get("delivery_store_match"):
        return {
            "status": "blocked",
            "message": "收货门店未匹配订单门店，未点击。",
            "device_serial": serial,
            "session_dir": str(session_dir),
            "before": before,
        }
    selected = select_safe_candidate(analysis, item_name, pack_label)
    if not selected:
        return {
            "status": "blocked",
            "message": f"未找到安全加购候选：{item_name} / {pack_label}，未点击。",
            "device_serial": serial,
            "session_dir": str(session_dir),
            "before": before,
        }

    center = selected.get("center") or []
    if len(center) != 2:
        return {"status": "blocked", "message": "安全候选缺少 center，未点击。", "device_serial": serial, "session_dir": str(session_dir), "selected": selected}
    x, y = int(round(float(center[0]))), int(round(float(center[1])))
    tap_result = run_command(adb_base(serial) + ["shell", "input", "tap", str(x), str(y)], timeout)
    time.sleep(1.5)
    after = save_adb_snapshot(serial, after_dir, timeout, plan)
    post_tap_validation = validate_post_tap(selected, after)
    status = "tapped_for_manual_review" if tap_result.returncode == 0 and after.get("captured") else "blocked"
    return {
        "status": status,
        "message": "已执行一次受保护加购 tap；已保存前后截图和控件树。未提交订单，未付款；加购结果仍需购物车复核。",
        "device_serial": serial,
        "session_dir": str(session_dir),
        "selected": selected,
        "tap": {"x": x, "y": y, "returncode": tap_result.returncode, "stderr": tap_result.stderr.strip(), "stdout": tap_result.stdout.strip()},
        "before": before,
        "after": after,
        "post_tap_validation": post_tap_validation,
        "safety": {
            "delivery_store_match_required": True,
            "single_tap_only": True,
            "cart_review_required": True,
            "forbidden_actions": ["提交订单", "付款", "自动切换收货地址"],
        },
    }


def run_adb_cart_open(
    plan: dict[str, Any],
    serial: str,
    timeout: int,
    candidate_index: int,
    cart_tap_x: int,
    cart_tap_y: int,
    pre_back_count: int,
    pre_nav_tap_x: int,
    pre_nav_tap_y: int,
) -> dict[str, Any]:
    serial, blocked = resolve_adb_serial(serial, timeout)
    if blocked:
        return blocked

    session = datetime.now().strftime("%Y%m%d-%H%M%S-cart-open")
    session_dir = OUTPUT_DIR / session
    before_dir = session_dir / "before"
    after_dir = session_dir / "after"
    before = save_adb_snapshot(serial, before_dir, timeout, plan)
    analysis = before.get("ui_analysis") or {}
    if not before.get("captured"):
        return {"status": "blocked", "message": "cart-open 前截图/控件树采集失败，未点击。", "device_serial": serial, "session_dir": str(session_dir), "before": before}

    if not analysis.get("delivery_store_match"):
        return {
            "status": "blocked",
            "message": "收货门店未匹配订单门店，未点击购物车入口。",
            "device_serial": serial,
            "session_dir": str(session_dir),
            "before": before,
        }

    mid = None
    if pre_back_count > 0:
        for _ in range(pre_back_count):
            run_command(adb_base(serial) + ["shell", "input", "keyevent", "BACK"], timeout)
            time.sleep(0.8)
        mid = save_adb_snapshot(serial, session_dir / "after-back", timeout, plan)
        analysis = (mid.get("ui_analysis") or {}) if mid.get("captured") else analysis

    pre_nav = None
    if pre_nav_tap_x > 0 and pre_nav_tap_y > 0:
        pre_allowed, pre_reasons = pre_cart_navigation_allowed(before, pre_nav_tap_x, pre_nav_tap_y)
        if not pre_allowed:
            return {
                "status": "blocked",
                "message": "预导航坐标不满足顶部退出搜索守卫，未点击。",
                "device_serial": serial,
                "session_dir": str(session_dir),
                "before": before,
                "pre_navigation_guard": {"allowed": False, "reasons": pre_reasons, "x": pre_nav_tap_x, "y": pre_nav_tap_y},
            }
        pre_tap_result = run_command(adb_base(serial) + ["shell", "input", "tap", str(pre_nav_tap_x), str(pre_nav_tap_y)], timeout)
        if pre_tap_result.returncode != 0:
            return {
                "status": "blocked",
                "message": "预导航 tap 执行失败，未继续点击购物车入口。",
                "device_serial": serial,
                "session_dir": str(session_dir),
                "before": before,
                "pre_navigation_tap": {
                    "x": pre_nav_tap_x,
                    "y": pre_nav_tap_y,
                    "returncode": pre_tap_result.returncode,
                    "stderr": pre_tap_result.stderr.strip(),
                    "stdout": pre_tap_result.stdout.strip(),
                },
            }
        time.sleep(1.2)
        pre_nav = save_adb_snapshot(serial, session_dir / "after-pre-nav", timeout, plan)
        analysis = (pre_nav.get("ui_analysis") or {}) if pre_nav.get("captured") else analysis

    candidates = analysis.get("cart_entry_candidates") or []
    if cart_tap_x > 0 and cart_tap_y > 0:
        selected = {
            "kind": "manual_cart_navigation_coordinate",
            "center": [cart_tap_x, cart_tap_y],
            "bounds": [cart_tap_x, cart_tap_y, cart_tap_x, cart_tap_y],
            "score": 0,
            "reasons": ["operator_selected_after_previous_candidates_no_change"],
        }
    elif not candidates:
        return {
            "status": "blocked",
            "message": "未找到购物车入口候选，未点击。",
            "device_serial": serial,
            "session_dir": str(session_dir),
            "before": before,
        }
    elif candidate_index < 0 or candidate_index >= len(candidates):
        return {
            "status": "blocked",
            "message": f"候选下标 {candidate_index} 超出范围，未点击。",
            "device_serial": serial,
            "session_dir": str(session_dir),
            "before": before,
            "cart_entry_candidates": candidates,
        }
    else:
        selected = candidates[candidate_index]
    center = selected.get("center") or []
    if len(center) != 2:
        return {"status": "blocked", "message": "购物车候选缺少 center，未点击。", "device_serial": serial, "session_dir": str(session_dir), "selected": selected}

    x, y = int(round(float(center[0]))), int(round(float(center[1])))
    tap_result = run_command(adb_base(serial) + ["shell", "input", "tap", str(x), str(y)], timeout)
    time.sleep(1.8)
    after = save_adb_snapshot(serial, after_dir, timeout, plan)
    after_detected = after.get("detected_text") or []
    cart_details = after.get("cart_review_details") or {}
    reached_cart = bool(cart_details.get("reached_cart")) or is_cart_review_page(after_detected)
    status = "cart_review_ready" if tap_result.returncode == 0 and after.get("captured") and reached_cart else "cart_open_unproven"
    return {
        "status": status,
        "message": "已执行一次受保护购物车入口 tap；已保存前后截图和控件树。未加购、未删除、未提交订单、未付款。",
        "device_serial": serial,
        "session_dir": str(session_dir),
        "selected": selected,
        "tap": {"x": x, "y": y, "returncode": tap_result.returncode, "stderr": tap_result.stderr.strip(), "stdout": tap_result.stdout.strip()},
        "before": before,
        "after_back": mid,
        "pre_navigation_tap": {
            "x": pre_nav_tap_x,
            "y": pre_nav_tap_y,
            "returncode": pre_tap_result.returncode,
            "stderr": pre_tap_result.stderr.strip(),
            "stdout": pre_tap_result.stdout.strip(),
        }
        if pre_nav
        else None,
        "after_pre_nav": pre_nav,
        "after": after,
        "cart_review": {
            "reached_cart": reached_cart,
            "cart_keywords_seen": cart_details.get("keyword_hits") or [word for word in CART_REVIEW_KEYWORDS if word in " ".join(str(text) for text in after_detected)],
            "cart_marker_hits": cart_details.get("marker_hits") or [],
            "risk_hits": cart_details.get("risk_hits") or [],
            "visible_relevant_text": cart_details.get("visible_relevant_text") or [],
            "detected_text": after_detected,
        },
        "safety": {
            "delivery_store_match_required": True,
            "pre_back_count": pre_back_count,
            "pre_navigation_tap": {"x": pre_nav_tap_x, "y": pre_nav_tap_y} if pre_nav else None,
            "controlled_navigation_taps_only": True,
            "forbidden_actions": ["加购", "删除", "清空", "切换收货地址", "提交订单", "付款"],
        },
    }


def adb_clear_focused_text(serial: str, timeout: int, max_delete: int = 28) -> list[dict[str, Any]]:
    results = []
    commands = [
        ["shell", "input", "keyevent", "123"],
        ["shell", "input", "keyevent", *["67" for _ in range(max_delete)]],
    ]
    for command in commands:
        result = run_command(adb_base(serial) + command, timeout)
        results.append({"args": command, "returncode": result.returncode, "stderr": result.stderr.strip(), "stdout": result.stdout.strip()})
        time.sleep(0.15)
    return results


def adb_input_query_text(serial: str, query: str, timeout: int) -> dict[str, Any]:
    attempts = []
    if not query:
        return {"entered": False, "attempts": attempts, "message": "未指定搜索词。"}

    input_timeout = max(3, min(timeout, 6))
    broadcast_result = run_command(adb_base(serial) + ["shell", "am", "broadcast", "-a", "ADB_INPUT_TEXT", "--es", "msg", query], input_timeout)
    attempts.append(
        {
            "method": "adb_keyboard_broadcast",
            "returncode": broadcast_result.returncode,
            "stderr": broadcast_result.stderr.strip(),
            "stdout": broadcast_result.stdout.strip(),
        }
    )
    if broadcast_result.returncode == 0 and "Broadcast completed" in broadcast_result.stdout:
        time.sleep(0.8)
        return {"entered": True, "attempts": attempts, "requires_after_query_check": True}

    clipboard_result = run_command(adb_base(serial) + ["shell", "cmd", "clipboard", "set", query], input_timeout)
    attempts.append(
        {
            "method": "cmd_clipboard_set",
            "returncode": clipboard_result.returncode,
            "stderr": clipboard_result.stderr.strip(),
            "stdout": clipboard_result.stdout.strip(),
        }
    )
    if clipboard_result.returncode == 0:
        paste_result = run_command(adb_base(serial) + ["shell", "input", "keyevent", "279"], input_timeout)
        attempts.append(
            {
                "method": "paste_keyevent_279",
                "returncode": paste_result.returncode,
                "stderr": paste_result.stderr.strip(),
                "stdout": paste_result.stdout.strip(),
            }
        )
        time.sleep(0.8)
        return {"entered": paste_result.returncode == 0, "attempts": attempts}

    if query.isascii():
        escaped = query.replace("%", "%25").replace(" ", "%s")
        text_result = run_command(adb_base(serial) + ["shell", "input", "text", escaped], input_timeout)
        attempts.append(
            {
                "method": "input_text_ascii",
                "returncode": text_result.returncode,
                "stderr": text_result.stderr.strip(),
                "stdout": text_result.stdout.strip(),
            }
        )
        time.sleep(0.8)
        return {"entered": text_result.returncode == 0, "attempts": attempts}

    return {"entered": False, "attempts": attempts, "message": "中文搜索词无法通过 clipboard/paste 输入。"}


def run_adb_search(
    plan: dict[str, Any],
    serial: str,
    timeout: int,
    query: str,
    candidate_index: int,
    search_tap_x: int,
    search_tap_y: int,
    pre_back_count: int,
    press_enter: bool,
) -> dict[str, Any]:
    serial, blocked = resolve_adb_serial(serial, timeout)
    if blocked:
        return blocked
    if not query:
        return {"status": "blocked", "message": "adb-search 需要指定 --search-query。", "device_serial": serial}

    session = datetime.now().strftime("%Y%m%d-%H%M%S-search")
    session_dir = OUTPUT_DIR / session
    before_dir = session_dir / "before"
    after_dir = session_dir / "after"
    before = save_adb_snapshot(serial, before_dir, timeout, plan)
    analysis = before.get("ui_analysis") or {}
    if not before.get("captured"):
        return {"status": "blocked", "message": "adb-search 前截图/控件树采集失败，未点击。", "device_serial": serial, "session_dir": str(session_dir), "before": before}

    after_back = None
    back_results = []
    if pre_back_count > 0:
        for _ in range(pre_back_count):
            result = run_command(adb_base(serial) + ["shell", "input", "keyevent", "BACK"], timeout)
            back_results.append({"returncode": result.returncode, "stderr": result.stderr.strip(), "stdout": result.stdout.strip()})
            time.sleep(0.8)
        after_back = save_adb_snapshot(serial, session_dir / "after-back", timeout, plan)
        analysis = (after_back.get("ui_analysis") or {}) if after_back.get("captured") else analysis

    if analysis.get("cart_review_page"):
        return {
            "status": "blocked",
            "message": "当前仍像购物车/结算页，未点击搜索框；如需关闭购物车浮层，请明确增加 --search-pre-back-count。",
            "device_serial": serial,
            "session_dir": str(session_dir),
            "before": before,
            "after_back": after_back,
            "back_results": back_results,
        }

    if not analysis.get("delivery_store_match"):
        return {
            "status": "blocked",
            "message": "收货门店未匹配订单门店，未点击搜索框。",
            "device_serial": serial,
            "session_dir": str(session_dir),
            "before": before,
            "after_back": after_back,
        }

    candidates = analysis.get("search_entry_candidates") or []
    if search_tap_x > 0 and search_tap_y > 0:
        selected = {
            "kind": "manual_search_coordinate",
            "center": [search_tap_x, search_tap_y],
            "bounds": [search_tap_x, search_tap_y, search_tap_x, search_tap_y],
            "score": 0,
            "reasons": ["operator_selected_search_coordinate"],
        }
    elif not candidates:
        return {
            "status": "blocked",
            "message": "未找到搜索入口候选，未点击。",
            "device_serial": serial,
            "session_dir": str(session_dir),
            "before": before,
            "after_back": after_back,
        }
    elif candidate_index < 0 or candidate_index >= len(candidates):
        return {
            "status": "blocked",
            "message": f"搜索候选下标 {candidate_index} 超出范围，未点击。",
            "device_serial": serial,
            "session_dir": str(session_dir),
            "before": before,
            "after_back": after_back,
            "search_entry_candidates": candidates,
        }
    else:
        selected = candidates[candidate_index]

    center = selected.get("center") or []
    if len(center) != 2:
        return {"status": "blocked", "message": "搜索候选缺少 center，未点击。", "device_serial": serial, "session_dir": str(session_dir), "selected": selected}

    x, y = int(round(float(center[0]))), int(round(float(center[1])))
    tap_result = run_command(adb_base(serial) + ["shell", "input", "tap", str(x), str(y)], timeout)
    time.sleep(0.8)
    clear_results = adb_clear_focused_text(serial, timeout)
    input_result = adb_input_query_text(serial, query, timeout)
    enter_result = None
    if press_enter:
        enter = run_command(adb_base(serial) + ["shell", "input", "keyevent", "ENTER"], timeout)
        enter_result = {"returncode": enter.returncode, "stderr": enter.stderr.strip(), "stdout": enter.stdout.strip()}
        time.sleep(2.0)
    else:
        time.sleep(1.2)
    after = save_adb_snapshot(serial, after_dir, timeout, plan)
    after_text_blob = " ".join(str(text) for text in after.get("detected_text") or [])
    query_visible_after = query in after_text_blob
    target_words = search_target_words(plan, query)
    result_check = search_result_hits(after, target_words)
    search_key_retry = None
    after_search_key = None
    scroll_retry = None
    scroll_retries = []
    after_target_scroll = None

    if press_enter and after.get("captured") and query_visible_after and not result_check.get("candidate_hit_count"):
        search_key = run_command(adb_base(serial) + ["shell", "input", "keyevent", "KEYCODE_SEARCH"], timeout)
        search_key_retry = {"returncode": search_key.returncode, "stderr": search_key.stderr.strip(), "stdout": search_key.stdout.strip()}
        time.sleep(2.0)
        after_search_key = save_adb_snapshot(serial, session_dir / "after-search-key", timeout, plan)
        retry_check = search_result_hits(after_search_key, target_words)
        if retry_check.get("candidate_hit_count") or retry_check.get("page_text_hit_count"):
            after = after_search_key
            result_check = retry_check
            after_text_blob = " ".join(str(text) for text in after.get("detected_text") or [])
            query_visible_after = query in after_text_blob

    for scroll_index in range(1, 4):
        if not (after.get("captured") and query_visible_after and result_check.get("page_text_hit_count") and not result_check.get("candidate_hit_count")):
            break
        scroll_args = target_guided_scroll_args(result_check)
        before_target_position = target_text_position(result_check)
        swipe = run_command(adb_base(serial) + ["shell", "input", "swipe", *scroll_args], timeout)
        scroll_retry = {
            "index": scroll_index,
            "returncode": swipe.returncode,
            "stderr": swipe.stderr.strip(),
            "stdout": swipe.stdout.strip(),
            "args": scroll_args,
            "before_target_position": before_target_position,
        }
        scroll_retries.append(scroll_retry)
        time.sleep(1.5)
        scroll_dir = session_dir / ("after-target-scroll" if scroll_index == 1 else f"after-target-scroll-{scroll_index}")
        after_target_scroll = save_adb_snapshot(serial, scroll_dir, timeout, plan)
        scroll_check = search_result_hits(after_target_scroll, target_words)
        scroll_retry["after_target_position"] = target_text_position(scroll_check)
        if scroll_check.get("candidate_hit_count") or scroll_check.get("page_text_hit_count"):
            after = after_target_scroll
            result_check = scroll_check
            after_text_blob = " ".join(str(text) for text in after.get("detected_text") or [])
            query_visible_after = query in after_text_blob
        if scroll_check.get("candidate_hit_count"):
            break
    status = (
        "search_ready_for_manual_review"
        if tap_result.returncode == 0
        and input_result.get("entered")
        and after.get("captured")
        and query_visible_after
        and result_check.get("candidate_hit_count")
        else "blocked"
    )
    message = "已执行一次受保护搜索输入并保存前后截图；未加购、未删除、未提交订单、未付款。"
    if query_visible_after and result_check.get("page_text_hit_count") and not result_check.get("candidate_hit_count"):
        message = "搜索结果文本已命中目标，但未找到目标卡片的加购候选；已阻断。未加购、未删除、未提交订单、未付款。"
    elif query_visible_after and not result_check.get("candidate_hit_count"):
        message = "搜索词可见，但结果候选卡片未命中目标关键词；按未刷新/未命中阻断。未加购、未删除、未提交订单、未付款。"
    return {
        "status": status,
        "message": message,
        "device_serial": serial,
        "session_dir": str(session_dir),
        "query": query,
        "selected": selected,
        "tap": {"x": x, "y": y, "returncode": tap_result.returncode, "stderr": tap_result.stderr.strip(), "stdout": tap_result.stdout.strip()},
        "clear_results": clear_results,
        "input_result": input_result,
        "enter_result": enter_result,
        "before": before,
        "after_back": after_back,
        "back_results": back_results,
        "after": after,
        "after_search_key": after_search_key,
        "after_target_scroll": after_target_scroll,
        "query_visible_after": query_visible_after,
        "search_result_check": result_check,
        "search_key_retry": search_key_retry,
        "scroll_retry": scroll_retry,
        "scroll_retries": scroll_retries,
        "safety": {
            "delivery_store_match_required": True,
            "pre_back_count": pre_back_count,
            "single_search_tap_only": True,
            "controlled_scroll_retry": bool(scroll_retries),
            "max_controlled_scroll_retries": 3,
            "forbidden_actions": ["加购", "删除", "清空", "切换收货地址", "提交订单", "付款"],
        },
    }


def pre_cart_navigation_allowed(before: dict[str, Any], x: int, y: int) -> tuple[bool, list[str]]:
    detected = before.get("detected_text") or []
    text_blob = " ".join(str(text) for text in detected)
    reasons = []
    if y > 420:
        reasons.append("pre_navigation_y_not_top_area")
    if x > 260:
        reasons.append("pre_navigation_x_not_left_header_area")
    if not any(word in text_blob for word in ["首页", "搜索", "猜你想找"]):
        reasons.append("search_header_not_detected")
    if any(word in text_blob for word in ["去结算", "提交订单", "付款"]):
        reasons.append("checkout_or_payment_text_visible")
    return not reasons, reasons


def validate_post_tap(selected: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    detected_text = after.get("detected_text") or []
    text_blob = " ".join(str(text) for text in detected_text)
    selected_text = f"{selected.get('row_text') or ''} {selected.get('context_text') or ''}"
    identity_hits = [word for word in selected.get("identity_hits") or [] if word]
    relevant_after_text = [
        text
        for text in detected_text
        if any(keyword in str(text) for keyword in ["数量", "购物车", "去结算", "提交订单", "付款", "已加购", "加入"])
    ]
    reasons = []
    if not after.get("captured"):
        reasons.append("after_snapshot_missing")
    if not identity_hits:
        reasons.append("selected_identity_not_proven")
    if not relevant_after_text:
        reasons.append("no_after_quantity_or_cart_signal")
    if any(word in text_blob for word in ["提交订单", "付款"]):
        reasons.append("submit_or_payment_text_visible")
    return {
        "cart_review_required": True,
        "add_result_proven": False,
        "reasons": reasons,
        "selected_identity_hits": identity_hits,
        "selected_text": selected_text,
        "after_relevant_text": relevant_after_text,
        "has_cart_hint": (after.get("plan_match") or {}).get("has_cart_hint"),
    }


def write_latest(payload: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LATEST_PATH.chmod(0o644)


def print_summary(payload: dict[str, Any]) -> None:
    plan = payload.get("plan") or {}
    print(payload.get("message", ""))
    print(f"订单：{plan.get('order_id')} / {plan.get('store_name')} / {plan.get('submitted_at')}")
    for line in plan.get("lines") or []:
        packs = "；".join(item["label"] for item in line.get("pack_strategy") or [])
        print(
            f"- {line['name']} {format_number(float(line['requested_quantity']))}{line['unit']}"
            f" -> 搜索 {line.get('preferred_keyword')} -> {packs or '人工处理'}"
        )
    print(f"结果文件：{LATEST_PATH}")


def main() -> int:
    parser = argparse.ArgumentParser(description="快驴订货 dry-run：随机读取当天订单，生成筛选和加购计划，可在 Mac mini 上采集安卓现场。")
    parser.add_argument("--server", default=os.environ.get("DAILY_ORDER_SERVER", DEFAULT_SERVER), help="daily-order 服务地址")
    parser.add_argument("--token", default=os.environ.get("DAILY_ORDER_ADMIN_TOKEN", DEFAULT_TOKEN), help="daily-order 后台 token")
    parser.add_argument("--date", default=today_text(), help="订单日期，默认今天")
    parser.add_argument("--order-id", default="", help="指定订单；为空时从日期内快驴订单随机选择")
    parser.add_argument("--seed", default="", help="随机种子；为空时按日期稳定随机")
    parser.add_argument(
        "--mode",
        choices=["plan-only", "adb-dry-run", "adb-safe-tap", "adb-cart-open", "adb-search"],
        default="plan-only",
        help="plan-only 只生成计划；adb-dry-run 采集安卓现场；adb-safe-tap 只允许一次受保护加购 tap；adb-cart-open 只允许一次购物车导航 tap；adb-search 只允许一次受保护搜索输入",
    )
    parser.add_argument("--adb-serial", default=os.environ.get("ANDROID_ADB_SERIAL", ""), help="ADB 设备号")
    parser.add_argument("--tap-item", default="", help="adb-safe-tap 的目标品项名，例如：豆腐")
    parser.add_argument("--tap-pack", default="", help="adb-safe-tap 的目标规格标签，例如：400g")
    parser.add_argument("--cart-candidate-index", type=int, default=0, help="adb-cart-open 使用的购物车入口候选下标，默认最高分候选 0")
    parser.add_argument("--cart-tap-x", type=int, default=0, help="adb-cart-open 坐标覆盖：指定 x 时仍会执行前后截图和购物车判定")
    parser.add_argument("--cart-tap-y", type=int, default=0, help="adb-cart-open 坐标覆盖：指定 y 时仍会执行前后截图和购物车判定")
    parser.add_argument("--cart-pre-back-count", type=int, default=0, help="adb-cart-open 前先按 Back 的次数，用于退出搜索浮层；仍会保存中间截图")
    parser.add_argument("--cart-pre-nav-tap-x", type=int, default=0, help="adb-cart-open 前先点一次顶部退出搜索候选 x；只允许左上搜索页导航区域")
    parser.add_argument("--cart-pre-nav-tap-y", type=int, default=0, help="adb-cart-open 前先点一次顶部退出搜索候选 y；只允许左上搜索页导航区域")
    parser.add_argument("--search-query", default="", help="adb-search 的搜索词，例如：洋葱")
    parser.add_argument("--search-candidate-index", type=int, default=0, help="adb-search 使用的搜索入口候选下标，默认最高分候选 0")
    parser.add_argument("--search-tap-x", type=int, default=0, help="adb-search 坐标覆盖：指定 x 时仍会执行前后截图和守卫")
    parser.add_argument("--search-tap-y", type=int, default=0, help="adb-search 坐标覆盖：指定 y 时仍会执行前后截图和守卫")
    parser.add_argument("--search-pre-back-count", type=int, default=0, help="adb-search 前先按 Back 的次数，用于关闭购物车浮层；仍会保存中间截图")
    parser.add_argument("--search-no-enter", action="store_true", help="adb-search 输入后不按 Enter，仅保存输入后的页面")
    parser.add_argument("--timeout", type=int, default=12, help="网络和 adb 命令超时秒数")
    parser.add_argument("--max-runtime", type=int, default=240, help="脚本整体最长运行秒数；0 表示不启用进程级 watchdog")
    args = parser.parse_args()

    started_at = now_text()
    try:
        install_process_watchdog(args.max_runtime)
        _, order = load_order(args.server, args.token, args.date, args.order_id.strip(), args.seed, args.timeout)
        plan = build_plan(order)
        if args.mode == "adb-dry-run":
            adb_result = run_adb_dry_run(plan, args.adb_serial.strip(), args.timeout)
        elif args.mode == "adb-safe-tap":
            adb_result = run_adb_safe_tap(plan, args.adb_serial.strip(), args.timeout, args.tap_item.strip(), args.tap_pack.strip())
        elif args.mode == "adb-cart-open":
            adb_result = run_adb_cart_open(
                plan,
                args.adb_serial.strip(),
                args.timeout,
                args.cart_candidate_index,
                args.cart_tap_x,
                args.cart_tap_y,
                max(0, args.cart_pre_back_count),
                args.cart_pre_nav_tap_x,
                args.cart_pre_nav_tap_y,
            )
        elif args.mode == "adb-search":
            adb_result = run_adb_search(
                plan,
                args.adb_serial.strip(),
                args.timeout,
                args.search_query.strip(),
                args.search_candidate_index,
                args.search_tap_x,
                args.search_tap_y,
                max(0, args.search_pre_back_count),
                not args.search_no_enter,
            )
        else:
            adb_result = {"status": "skipped", "message": "plan-only 模式未连接安卓。"}
        payload = {
            "generated_at": started_at,
            "status": "ready" if adb_result.get("status") in {"skipped", "ready_for_manual_review", "tapped_for_manual_review", "cart_review_ready", "search_ready_for_manual_review"} else "blocked",
            "mode": args.mode,
            "source": admin_summary_url(args.server, "***"),
            "message": "快驴订货计划已生成；未提交订单，未付款。",
            "plan": plan,
            "adb": adb_result,
        }
        write_latest(payload)
        print_summary(payload)
        return 0 if payload["status"] == "ready" else 1
    except Exception as exc:
        payload = {
            "generated_at": started_at,
            "status": "failed",
            "mode": args.mode,
            "message": f"快驴订货 dry-run 失败：{exc}",
            "plan": {},
            "adb": {},
        }
        write_latest(payload)
        print(payload["message"], file=sys.stderr)
        print(f"结果文件：{LATEST_PATH}", file=sys.stderr)
        return 1
    finally:
        if hasattr(signal, "alarm"):
            signal.alarm(0)


if __name__ == "__main__":
    raise SystemExit(main())
