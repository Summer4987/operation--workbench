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
    pack_lines, planned_quantity = split_packs(quantity, [float(v) for v in rule["pack_sizes"]], float(rule.get("allowed_overage") or 0))
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
    base = ["adb"]
    if serial:
        base.extend(["-s", serial])
    return base


def adb_available() -> bool:
    return bool(shutil.which("adb"))


def adb_devices(timeout: int) -> list[str]:
    result = run_command(["adb", "devices"], timeout)
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
    parser.add_argument("--mode", choices=["plan-only", "adb-dry-run"], default="plan-only", help="plan-only 只生成计划；adb-dry-run 额外采集安卓截图/控件树")
    parser.add_argument("--adb-serial", default=os.environ.get("ANDROID_ADB_SERIAL", ""), help="ADB 设备号")
    parser.add_argument("--timeout", type=int, default=12, help="网络和 adb 命令超时秒数")
    args = parser.parse_args()

    started_at = now_text()
    try:
        _, order = load_order(args.server, args.token, args.date, args.order_id.strip(), args.seed, args.timeout)
        plan = build_plan(order)
        adb_result = run_adb_dry_run(plan, args.adb_serial.strip(), args.timeout) if args.mode == "adb-dry-run" else {"status": "skipped", "message": "plan-only 模式未连接安卓。"}
        payload = {
            "generated_at": started_at,
            "status": "ready" if adb_result.get("status") in {"skipped", "ready_for_manual_review"} else "blocked",
            "mode": args.mode,
            "source": admin_summary_url(args.server, "***"),
            "message": "快驴订货 dry-run 计划已生成；未提交订单，未付款。",
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
