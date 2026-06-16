from __future__ import annotations

import argparse
import json
import os
import random
import re
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
        "lesson": "银泰城实跑时 40 斤按 20斤 x2 处理，优先整件，减少加购次数。",
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
    completed = subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)
    return CommandResult(args=args, returncode=completed.returncode, stdout=completed.stdout, stderr=completed.stderr)


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
    snapshot["kuailv_hint_found"] = any(text in xml_text for text in ["快驴", "美团", "购物车", "搜索"])
    return snapshot


def detect_page_text(xml_text: str) -> list[str]:
    if not xml_text:
        return []
    values = re.findall(r'text="([^"]+)"', xml_text)
    values += re.findall(r'content-desc="([^"]+)"', xml_text)
    cleaned = []
    for value in values:
        value = value.strip()
        if value and value not in cleaned:
            cleaned.append(value)
    return cleaned[:80]


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


def nearby_texts(nodes: list[dict[str, Any]], center: tuple[float, float], radius_y: int = 140, radius_x: int = 760) -> list[dict[str, Any]]:
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
    return rows[:12]


def candidate_text(candidate: dict[str, Any], radius: str = "nearby_texts") -> str:
    return " ".join(str(row.get("text") or "") for row in candidate.get(radius) or [])


def candidate_context(nodes: list[dict[str, Any]], center: tuple[float, float]) -> list[dict[str, Any]]:
    # Include the product title above the spec row, but keep the window narrow
    # enough that the previous product's risky spec does not bleed into a target row.
    return nearby_texts(nodes, center, radius_y=360, radius_x=760)


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
    y_end = min(height, int(height * 0.92))
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
    pack_hits = [pack_label] if pack_label and pack_label in row_text else []
    identity_keywords = [word for word in required if not looks_like_spec_keyword(word)]
    identity_hits = [word for word in identity_keywords if word in all_text]
    reasons = []
    if not context_required_hits:
        reasons.append("missing_required_keyword")
    if identity_keywords and not identity_hits:
        reasons.append("missing_identity_keyword")
    if excluded_hits:
        reasons.append("excluded_keyword_seen")
    if pack_label and not pack_hits:
        reasons.append("pack_label_not_on_row")
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
        "pack_hits": pack_hits,
        "center": candidate.get("center"),
        "bounds": candidate.get("bounds"),
    }


def looks_like_spec_keyword(word: str) -> bool:
    return bool(re.search(r"\d", word)) or word in {"斤", "盒", "箱", "桶", "瓶", "袋", "g", "kg"}


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
            item["candidate"] = {key: candidate.get(key) for key in ("center", "bounds", "color", "nearby_texts", "context_texts")}
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
            rows.append(
                {
                    "line_name": line.get("name", ""),
                    "pack_label": pack_label,
                    "allowed": bool(selected),
                    "selected": selected,
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
    orange_candidates = annotate_add_candidates(detect_orange_controls(image_path, nodes), plan)
    cart_entry_candidates = find_cart_entry_candidates(nodes, image_path)
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


def is_cart_review_page(detected_text: list[str]) -> bool:
    text = " ".join(str(item) for item in detected_text)
    strong_hits = [word for word in CART_REVIEW_KEYWORDS if word in text]
    if any(word in text for word in ["提交订单", "去结算", "合计"]):
        return True
    return len(strong_hits) >= 2


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


def run_adb_cart_open(plan: dict[str, Any], serial: str, timeout: int, candidate_index: int) -> dict[str, Any]:
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

    candidates = analysis.get("cart_entry_candidates") or []
    if not candidates:
        return {
            "status": "blocked",
            "message": "未找到购物车入口候选，未点击。",
            "device_serial": serial,
            "session_dir": str(session_dir),
            "before": before,
        }
    if candidate_index < 0 or candidate_index >= len(candidates):
        return {
            "status": "blocked",
            "message": f"候选下标 {candidate_index} 超出范围，未点击。",
            "device_serial": serial,
            "session_dir": str(session_dir),
            "before": before,
            "cart_entry_candidates": candidates,
        }

    selected = candidates[candidate_index]
    center = selected.get("center") or []
    if len(center) != 2:
        return {"status": "blocked", "message": "购物车候选缺少 center，未点击。", "device_serial": serial, "session_dir": str(session_dir), "selected": selected}

    x, y = int(round(float(center[0]))), int(round(float(center[1])))
    tap_result = run_command(adb_base(serial) + ["shell", "input", "tap", str(x), str(y)], timeout)
    time.sleep(1.8)
    after = save_adb_snapshot(serial, after_dir, timeout, plan)
    after_detected = after.get("detected_text") or []
    reached_cart = is_cart_review_page(after_detected)
    status = "cart_review_ready" if tap_result.returncode == 0 and after.get("captured") and reached_cart else "cart_open_unproven"
    return {
        "status": status,
        "message": "已执行一次受保护购物车入口 tap；已保存前后截图和控件树。未加购、未删除、未提交订单、未付款。",
        "device_serial": serial,
        "session_dir": str(session_dir),
        "selected": selected,
        "tap": {"x": x, "y": y, "returncode": tap_result.returncode, "stderr": tap_result.stderr.strip(), "stdout": tap_result.stdout.strip()},
        "before": before,
        "after": after,
        "cart_review": {
            "reached_cart": reached_cart,
            "cart_keywords_seen": [word for word in CART_REVIEW_KEYWORDS if word in " ".join(str(text) for text in after_detected)],
            "detected_text": after_detected,
        },
        "safety": {
            "delivery_store_match_required": True,
            "single_navigation_tap_only": True,
            "forbidden_actions": ["加购", "删除", "清空", "提交订单", "付款", "自动切换收货地址"],
        },
    }


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
        choices=["plan-only", "adb-dry-run", "adb-safe-tap", "adb-cart-open"],
        default="plan-only",
        help="plan-only 只生成计划；adb-dry-run 采集安卓现场；adb-safe-tap 只允许一次受保护加购 tap；adb-cart-open 只允许一次购物车导航 tap",
    )
    parser.add_argument("--adb-serial", default=os.environ.get("ANDROID_ADB_SERIAL", ""), help="ADB 设备号")
    parser.add_argument("--tap-item", default="", help="adb-safe-tap 的目标品项名，例如：豆腐")
    parser.add_argument("--tap-pack", default="", help="adb-safe-tap 的目标规格标签，例如：400g")
    parser.add_argument("--cart-candidate-index", type=int, default=0, help="adb-cart-open 使用的购物车入口候选下标，默认最高分候选 0")
    parser.add_argument("--timeout", type=int, default=12, help="网络和 adb 命令超时秒数")
    args = parser.parse_args()

    started_at = now_text()
    try:
        _, order = load_order(args.server, args.token, args.date, args.order_id.strip(), args.seed, args.timeout)
        plan = build_plan(order)
        if args.mode == "adb-dry-run":
            adb_result = run_adb_dry_run(plan, args.adb_serial.strip(), args.timeout)
        elif args.mode == "adb-safe-tap":
            adb_result = run_adb_safe_tap(plan, args.adb_serial.strip(), args.timeout, args.tap_item.strip(), args.tap_pack.strip())
        elif args.mode == "adb-cart-open":
            adb_result = run_adb_cart_open(plan, args.adb_serial.strip(), args.timeout, args.cart_candidate_index)
        else:
            adb_result = {"status": "skipped", "message": "plan-only 模式未连接安卓。"}
        payload = {
            "generated_at": started_at,
            "status": "ready" if adb_result.get("status") in {"skipped", "ready_for_manual_review", "tapped_for_manual_review", "cart_review_ready"} else "blocked",
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


if __name__ == "__main__":
    raise SystemExit(main())
