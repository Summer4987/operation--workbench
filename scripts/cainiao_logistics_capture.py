from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "cainiao_logistics"
LATEST_PATH = OUTPUT_DIR / "latest.json"
DEFAULT_SERVER = "http://139.155.148.169"
DEFAULT_TOKEN = "daily-order-admin"
DEFAULT_PACKAGE = "com.cainiao.wireless"
REMOTE_XML_PATH = "/sdcard/cainiao_window.xml"
REMOTE_SCREENSHOT_PATH = "/sdcard/cainiao_screen.png"
ADB_COMMON_PATHS = [
    Path.home() / "Library" / "Android" / "sdk" / "platform-tools" / "adb",
    Path("/opt/homebrew/bin/adb"),
    Path("/usr/local/bin/adb"),
]

PICKUP_RE = re.compile(r"(?:取件码|取货码|提货码|凭证码|取件号)\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9\-]{2,15})")
TRACKING_RE = re.compile(r"\b(?!20\d{6,})([A-Z]{1,6}[A-Z0-9]{7,24}|\d{10,24})\b", re.I)
CARRIER_WORDS = ["顺丰", "中通", "圆通", "申通", "韵达", "极兔", "京东", "邮政", "EMS", "德邦", "菜鸟", "丹鸟"]
STATUS_WORDS = ["待取件", "已入库", "已签收", "派送中", "运输中", "已揽收", "已发出", "到达", "已到"]
NOISE_WORDS = ["手机号", "手机尾号", "隐私小号", "订单号", "运单号复制", "复制", "查看", "删除"]
DETAIL_STATUS_WORDS = ["待取件", "已入库", "派送中", "运输中", "已签收", "已到", "已发货", "已下单", "仓库处理中"]
TRACE_SKIP_WORDS = ["延迟得", "复制", "分享", "消息订阅", "全程预测", "隐私小号", "展开", "返回，按钮", "查看商品"]
STORE_ADDRESS_HINTS = {
    "金融城店": ["新街里", "3035", "石羊街道"],
    "银泰城店": ["银泰城", "悦坊", "益州大道1999"],
    "万象城店": ["万象城", "华润柒公馆", "双福一路58"],
    "保利中心店": ["保利中心", "玉林街道", "东区C座"],
}


def now_text() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S%z")


def timestamp_text() -> str:
    return datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")


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


def run_command(args: list[str], timeout: int) -> dict[str, Any]:
    try:
        result = subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)
        return {"args": args, "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
    except Exception as exc:
        return {"args": args, "returncode": -1, "stdout": "", "stderr": str(exc)}


def run_command_with_input(args: list[str], payload: bytes, timeout: int) -> dict[str, Any]:
    try:
        result = subprocess.run(args, input=payload, capture_output=True, timeout=timeout, check=False)
        return {
            "args": args,
            "returncode": result.returncode,
            "stdout": result.stdout.decode("utf-8", errors="replace"),
            "stderr": result.stderr.decode("utf-8", errors="replace"),
        }
    except Exception as exc:
        return {"args": args, "returncode": -1, "stdout": "", "stderr": str(exc)}


def ensure_ok(result: dict[str, Any], action: str) -> None:
    if result["returncode"] != 0:
        detail = (result.get("stderr") or result.get("stdout") or "").strip()
        raise RuntimeError(f"{action}失败：{detail or result['args']}")


def launch_cainiao(serial: str, package: str, timeout: int) -> list[dict[str, Any]]:
    commands = []
    base = adb_base(serial)
    commands.append(run_command(base + ["shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"], timeout))
    time.sleep(3)
    return commands


def capture_snapshot(serial: str, evidence_dir: Path, timeout: int, label: str = "window") -> tuple[str, Path, list[dict[str, Any]]]:
    commands: list[dict[str, Any]] = []
    base = adb_base(serial)

    dump = run_command(base + ["shell", "uiautomator", "dump", REMOTE_XML_PATH], timeout)
    commands.append(dump)
    ensure_ok(dump, "导出安卓控件树")

    xml_path = evidence_dir / f"{label}_dump.xml"
    pull_xml = run_command(base + ["pull", REMOTE_XML_PATH, str(xml_path)], timeout)
    commands.append(pull_xml)
    ensure_ok(pull_xml, "拉取安卓控件树")

    shot = run_command(base + ["shell", "screencap", "-p", REMOTE_SCREENSHOT_PATH], timeout)
    commands.append(shot)
    if shot["returncode"] == 0:
        pull_shot = run_command(base + ["pull", REMOTE_SCREENSHOT_PATH, str(evidence_dir / f"{label}.png")], timeout)
        commands.append(pull_shot)

    return xml_path.read_text(encoding="utf-8", errors="replace"), xml_path, commands


def capture_from_device(serial: str, package: str, evidence_dir: Path, timeout: int) -> tuple[str, Path, list[dict[str, Any]]]:
    commands = launch_cainiao(serial, package, timeout)
    xml_text, xml_path, capture_commands = capture_snapshot(serial, evidence_dir, timeout, "window")
    return xml_text, xml_path, commands + capture_commands


def parse_bounds(value: str) -> list[int]:
    match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", value or "")
    if not match:
        return []
    return [int(part) for part in match.groups()]


def bounds_center(bounds: list[int]) -> tuple[int, int]:
    x1, y1, x2, y2 = bounds
    return ((x1 + x2) // 2, (y1 + y2) // 2)


def extract_ui_nodes(xml_text: str) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text)
    nodes = []
    for node in root.iter("node"):
        text = str(node.attrib.get("text") or node.attrib.get("content-desc") or "").strip()
        bounds = parse_bounds(str(node.attrib.get("bounds") or ""))
        if text and bounds:
            nodes.append({"text": text, "bounds": bounds, "clickable": node.attrib.get("clickable") == "true"})
    nodes.sort(key=lambda item: (item["bounds"][1], item["bounds"][0]))
    return nodes


def extract_ui_texts(xml_text: str) -> list[str]:
    root = ET.fromstring(xml_text)
    texts: list[str] = []
    for node in root.iter("node"):
        for key in ("text", "content-desc"):
            value = str(node.attrib.get(key) or "").strip()
            if value:
                texts.append(value)
    return texts


def list_detail_targets(xml_text: str, max_details: int) -> list[dict[str, int]]:
    targets: list[dict[str, int]] = []
    seen_y: set[int] = set()
    for node in extract_ui_nodes(xml_text):
        text = node["text"]
        bounds = node["bounds"]
        x1, y1, x2, y2 = bounds
        if x1 < 250 or y1 < 260 or y2 > 2240:
            continue
        if not any(word in text for word in DETAIL_STATUS_WORDS):
            continue
        cx, cy = bounds_center(bounds)
        key_y = round(cy / 80) * 80
        if key_y in seen_y:
            continue
        seen_y.add(key_y)
        targets.append({"x": max(500, cx), "y": cy, "text": text})
    return targets[:max_details]


def popup_cancel_target(xml_text: str) -> dict[str, int] | None:
    texts = extract_ui_texts(xml_text)
    if not ("你的鼓励，是菜鸟前进的动力~" in texts and "好评" in texts):
        return None
    for node in extract_ui_nodes(xml_text):
        if node["text"] == "取消":
            cx, cy = bounds_center(node["bounds"])
            return {"x": cx, "y": cy, "text": node["text"]}
    return None


def clean_code(value: str) -> str:
    return re.sub(r"^[：:\s]+|[，。,.;；\s]+$", "", value.strip())


def first_match(words: list[str], candidates: list[str]) -> str:
    for word in words:
        for candidate in candidates:
            if candidate and candidate in word:
                return candidate
    return ""


def infer_store_name(texts: list[str], fallback: str = "") -> str:
    context = " ".join(texts)
    for store_name, hints in STORE_ADDRESS_HINTS.items():
        if any(hint in context for hint in hints):
            return store_name
    return fallback


def infer_goods_name(texts: list[str]) -> str:
    for text in texts:
        if "买给" not in text and not text.startswith("淘宝 |"):
            continue
        clean = re.sub(r"^淘宝\s*\|\s*", "", text).strip()
        clean = re.sub(r"^买给【[^】]+】的", "", clean).strip()
        clean = re.sub(r"\s+", " ", clean)
        if clean:
            return clean[:42]
    for text in texts:
        if any(word in text for word in ["餐盒", "打包盒", "汤桶", "裙带菜", "海木耳", "包装袋", "纸碗"]):
            return text[:42]
    return "菜鸟裹裹包裹"


def logistics_trace_summary(texts: list[str]) -> str:
    rows = []
    for text in texts:
        if not text or any(word in text for word in TRACE_SKIP_WORDS):
            continue
        if re.search(r"\d{2}\.\d{2}\s+\d{2}:\d{2}", text) or text.startswith("【") or text.startswith("送至"):
            rows.append(text)
            continue
        if any(word in text for word in ["已到达", "已发往", "派送", "签收", "待取件", "驿站", "已入库"]):
            rows.append(text)
    cleaned = []
    seen = set()
    for row in rows:
        row = re.sub(r"\s+", " ", row).strip()
        if row and row not in seen:
            seen.add(row)
            cleaned.append(row)
    return "；".join(cleaned)[:300]


def nearby_text(texts: list[str], index: int, radius: int = 4) -> str:
    start = max(0, index - radius)
    end = min(len(texts), index + radius + 1)
    return " ".join(texts[start:end])


def forward_text(texts: list[str], index: int, radius: int = 4) -> str:
    end = min(len(texts), index + radius + 1)
    return " ".join(texts[index:end])


def find_pickup_codes(texts: list[str]) -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    for index, text in enumerate(texts):
        for match in PICKUP_RE.finditer(text):
            found.append((clean_code(match.group(1)), index))
        if any(label in text for label in ["取件码", "取货码", "提货码", "凭证码", "取件号"]) and index + 1 < len(texts):
            next_text = clean_code(texts[index + 1])
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9\-]{2,15}", next_text):
                found.append((next_text, index))
    return dedupe_pairs(found)


def dedupe_pairs(pairs: list[tuple[str, int]]) -> list[tuple[str, int]]:
    seen = set()
    rows = []
    for value, index in pairs:
        key = value.upper()
        if key in seen:
            continue
        seen.add(key)
        rows.append((value, index))
    return rows


def find_tracking_numbers(texts: list[str]) -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    for index, text in enumerate(texts):
        if any(word in text for word in NOISE_WORDS):
            continue
        for match in TRACKING_RE.finditer(text):
            number = clean_code(match.group(1)).upper()
            after = text[match.end() : match.end() + 6]
            if len(number) < 8 or number.startswith("400"):
                continue
            if re.fullmatch(r"1[3-9]\d{9}", number):
                continue
            if re.match(r"-\d{3,5}", after):
                continue
            found.append((number, index))
    return dedupe_pairs(found)


def infer_status(context: str, pickup_code: str, status_hint: str = "") -> str:
    if status_hint in STATUS_WORDS:
        return "待取件" if status_hint in ["待取件", "已入库", "已到", "到达"] and pickup_code else status_hint
    for word in STATUS_WORDS:
        if word in context:
            return "待取件" if word in ["待取件", "已入库", "已到", "到达"] and pickup_code else word
    return "待取件" if pickup_code else "运输中"


def build_record(
    store_name: str,
    pickup_code: str,
    tracking_number: str,
    context: str,
    captured_at: str,
    index: int,
    goods: str = "菜鸟裹裹包裹",
    status_hint: str = "",
) -> dict[str, str]:
    carrier = first_match([context], CARRIER_WORDS)
    digest_source = "|".join([store_name, pickup_code, tracking_number, context])
    fallback_tracking = f"CAINIAO-{hashlib.sha1(digest_source.encode('utf-8')).hexdigest()[:10].upper()}"
    latest = context[:180]
    return {
        "store_name": store_name,
        "goods": goods or "菜鸟裹裹包裹",
        "supplier": "菜鸟裹裹",
        "carrier": carrier or "菜鸟裹裹",
        "tracking_number": tracking_number or fallback_tracking,
        "status": infer_status(context, pickup_code, status_hint),
        "pickup_code": pickup_code,
        "latest_trace": latest or "菜鸟裹裹采集到物流更新",
        "updated_at": captured_at,
        "remark": "",
    }


def parse_logistics_records(xml_text: str, store_name: str, captured_at: str | None = None) -> dict[str, Any]:
    captured_at = captured_at or now_text()
    texts = extract_ui_texts(xml_text)
    detected_store_name = infer_store_name(texts, "")
    inferred_store_name = detected_store_name or store_name
    goods = infer_goods_name(texts)
    trace_summary = logistics_trace_summary(texts)
    prefer_trace_summary = bool(trace_summary and (detected_store_name or any(text.startswith("送至") for text in texts)))
    status_hint = first_match(texts, STATUS_WORDS) if prefer_trace_summary else ""
    pickups = find_pickup_codes(texts)
    trackings = find_tracking_numbers(texts)
    records: list[dict[str, str]] = []

    used_tracking: set[str] = set()
    for row_index, (pickup, pickup_index) in enumerate(pickups, start=1):
        context = trace_summary if prefer_trace_summary else nearby_text(texts, pickup_index)
        tracking = ""
        preceding = [(number, pickup_index - number_index) for number, number_index in trackings if 0 <= pickup_index - number_index <= 8]
        following = [(number, number_index - pickup_index) for number, number_index in trackings if 0 < number_index - pickup_index <= 3]
        if preceding:
            tracking = min(preceding, key=lambda item: item[1])[0]
        elif following:
            tracking = min(following, key=lambda item: item[1])[0]
        if tracking:
            used_tracking.add(tracking)
        records.append(build_record(inferred_store_name, pickup, tracking, context, captured_at, row_index, goods, status_hint))

    for number, number_index in trackings:
        if number in used_tracking:
            continue
        context = trace_summary if prefer_trace_summary else forward_text(texts, number_index)
        record_status_hint = status_hint or first_match(forward_text(texts, number_index).split(" "), STATUS_WORDS)
        records.append(build_record(inferred_store_name, "", number, context, captured_at, len(records) + 1, goods, record_status_hint))

    return {
        "captured_at": captured_at,
        "store_name": inferred_store_name,
        "text_count": len(texts),
        "texts": texts,
        "pickup_codes": [{"code": code, "index": index} for code, index in pickups],
        "tracking_numbers": [{"number": number, "index": index} for number, index in trackings],
        "records": records,
    }


def post_logistics_record(server: str, token: str, record: dict[str, str], timeout: int) -> dict[str, Any]:
    query = urllib.parse.urlencode({"token": token})
    url = f"{server.rstrip('/')}/daily-order/api/logistics-ingest?{query}"
    data = json.dumps(record, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "cainiao-logistics-capture/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def post_logistics_record_via_ssh(host: str, token: str, record: dict[str, str], timeout: int) -> dict[str, Any]:
    query = urllib.parse.urlencode({"token": token})
    remote_url = f"http://127.0.0.1:8010/daily-order/api/admin/logistics?{query}"
    payload = json.dumps(record, ensure_ascii=False).encode("utf-8")
    command = [
        "ssh",
        host,
        f"curl -fsS -X POST {remote_url!r} -H 'Content-Type: application/json' --data-binary @-",
    ]
    result = run_command_with_input(command, payload, timeout)
    ensure_ok(result, f"通过 {host} 写入物流看板")
    return json.loads(result["stdout"])


def dedupe_records(records: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str, str, str]] = set()
    rows = []
    for record in records:
        key = (
            record.get("store_name", ""),
            record.get("tracking_number", ""),
            record.get("pickup_code", ""),
            record.get("latest_trace", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        rows.append(record)
    return rows


def scan_detail_pages(
    serial: str,
    package: str,
    evidence_dir: Path,
    store_name: str,
    captured_at: str,
    max_details: int,
    scroll_pages: int,
    timeout: int,
    reset_list: bool = True,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    commands = launch_cainiao(serial, package, timeout)
    all_records: list[dict[str, str]] = []
    detail_summaries = []
    scanned = 0
    base = adb_base(serial)
    if reset_list:
        for _ in range(3):
            swipe_down = run_command(base + ["shell", "input", "swipe", "520", "900", "520", "2050", "500"], timeout)
            commands.append(swipe_down)
            time.sleep(0.5)
    for page_index in range(scroll_pages + 1):
        page_dir = evidence_dir / f"list-page-{page_index + 1}"
        page_dir.mkdir(parents=True, exist_ok=True)
        list_xml, _list_path, list_commands = capture_snapshot(serial, page_dir, timeout, "list")
        commands.extend(list_commands)
        popup = popup_cancel_target(list_xml)
        if popup:
            cancel = run_command(base + ["shell", "input", "tap", str(popup["x"]), str(popup["y"])], timeout)
            commands.append(cancel)
            time.sleep(1)
            list_xml, _list_path, list_commands = capture_snapshot(serial, page_dir, timeout, "list_after_popup")
            commands.extend(list_commands)
            write_json(page_dir / "popup_cancelled.json", popup)
        targets = list_detail_targets(list_xml, max_details - scanned)
        write_json(page_dir / "targets.json", targets)
        if not targets and page_index == 0:
            parsed = parse_logistics_records(list_xml, store_name, captured_at)
            all_records.extend(parsed["records"])
            detail_summaries.append({"kind": "current-page", "record_count": len(parsed["records"]), "store_name": parsed["store_name"]})
            if parsed["records"]:
                back = run_command(base + ["shell", "input", "keyevent", "4"], timeout)
                commands.append(back)
                time.sleep(1)
                list_xml, _list_path, list_commands = capture_snapshot(serial, page_dir, timeout, "list_after_back")
                commands.extend(list_commands)
                targets = list_detail_targets(list_xml, max_details - scanned)
                write_json(page_dir / "targets_after_back.json", targets)
            if not targets:
                break
        for target_index, target in enumerate(targets, start=1):
            if scanned >= max_details:
                break
            scanned += 1
            tap = run_command(base + ["shell", "input", "tap", str(target["x"]), str(target["y"])], timeout)
            commands.append(tap)
            ensure_ok(tap, "点击包裹详情")
            time.sleep(2)
            detail_dir = evidence_dir / f"detail-{scanned:02d}"
            detail_dir.mkdir(parents=True, exist_ok=True)
            detail_xml, _detail_path, detail_commands = capture_snapshot(serial, detail_dir, timeout, "detail")
            commands.extend(detail_commands)
            popup = popup_cancel_target(detail_xml)
            if popup:
                cancel = run_command(base + ["shell", "input", "tap", str(popup["x"]), str(popup["y"])], timeout)
                commands.append(cancel)
                time.sleep(1)
                detail_xml, _detail_path, detail_commands = capture_snapshot(serial, detail_dir, timeout, "detail_after_popup")
                commands.extend(detail_commands)
                write_json(detail_dir / "popup_cancelled.json", popup)
            parsed = parse_logistics_records(detail_xml, store_name, captured_at)
            write_json(detail_dir / "parsed.json", parsed)
            write_json(detail_dir / "target.json", target)
            all_records.extend(parsed["records"])
            detail_summaries.append(
                {
                    "kind": "detail",
                    "target": target,
                    "record_count": len(parsed["records"]),
                    "tracking_numbers": [item["number"] for item in parsed["tracking_numbers"]],
                    "pickup_codes": [item["code"] for item in parsed["pickup_codes"]],
                    "store_name": parsed["store_name"],
                }
            )
            back = run_command(base + ["shell", "input", "keyevent", "4"], timeout)
            commands.append(back)
            time.sleep(1)
        if scanned >= max_details or page_index >= scroll_pages:
            break
        swipe = run_command(base + ["shell", "input", "swipe", "520", "2050", "520", "900", "500"], timeout)
        commands.append(swipe)
        time.sleep(1)
    records = dedupe_records([record for record in all_records if record.get("store_name")])
    parsed = {
        "captured_at": captured_at,
        "scan_details": True,
        "detail_count": scanned,
        "record_count": len(records),
        "records": records,
        "details": detail_summaries,
    }
    return parsed, commands


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_latest(evidence_dir: Path, summary: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    write_json(LATEST_PATH, {"evidence_dir": str(evidence_dir), **summary})


def error_payload(exc: Exception, evidence_dir: Path) -> dict[str, Any]:
    return {
        "ok": False,
        "captured_at": now_text(),
        "error": str(exc),
        "evidence_dir": str(evidence_dir),
        "agent_next_action": "检查 evidence_dir 里的 screen.png、window_dump.xml 和 commands.json，确认菜鸟裹裹是否登录、页面是否在包裹列表或详情页。",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="从安卓菜鸟裹裹采集物流单号、取件码，并同步到门店物流看板。")
    parser.add_argument("--store-name", default="", help="门店名兜底值；详情页有地址时会自动识别门店。")
    parser.add_argument("--server", default=os.environ.get("DAILY_ORDER_SERVER", DEFAULT_SERVER))
    parser.add_argument("--token", default=os.environ.get("DAILY_ORDER_ADMIN_TOKEN", DEFAULT_TOKEN))
    parser.add_argument("--commit-via-ssh", default=os.environ.get("DAILY_ORDER_COMMIT_SSH", ""), help="通过 SSH 到云主机本机接口写入，例如 ubuntu@139.155.148.169。")
    parser.add_argument("--serial", default=os.environ.get("CAINIAO_ADB_SERIAL", ""))
    parser.add_argument("--package", default=os.environ.get("CAINIAO_PACKAGE", DEFAULT_PACKAGE))
    parser.add_argument("--fixture-ui-dump", default="", help="用于测试/调试的安卓 uiautomator XML 文件；提供后不连接真机。")
    parser.add_argument("--scan-details", action="store_true", help="从菜鸟列表页逐个点击包裹详情采集。")
    parser.add_argument("--max-details", type=int, default=8)
    parser.add_argument("--scroll-pages", type=int, default=0)
    parser.add_argument("--no-reset-list", action="store_true", help="不在扫描前把菜鸟列表拉回顶部。")
    parser.add_argument("--commit", action="store_true", help="真实写入物流看板；默认只生成证据包和解析结果。")
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--evidence-dir", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    evidence_dir = Path(args.evidence_dir).expanduser() if args.evidence_dir else OUTPUT_DIR / timestamp_text()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {
        "ok": False,
        "captured_at": now_text(),
        "store_name": args.store_name,
        "commit": bool(args.commit),
        "records_written": 0,
    }
    try:
        commands: list[dict[str, Any]] = []
        if args.scan_details and args.fixture_ui_dump:
            raise RuntimeError("--scan-details 不能和 --fixture-ui-dump 同时使用。")
        if args.scan_details:
            parsed, commands = scan_detail_pages(
                args.serial,
                args.package,
                evidence_dir,
                args.store_name,
                summary["captured_at"],
                args.max_details,
                args.scroll_pages,
                args.timeout,
                not args.no_reset_list,
            )
        elif args.fixture_ui_dump:
            xml_path = Path(args.fixture_ui_dump).expanduser()
            xml_text = xml_path.read_text(encoding="utf-8", errors="replace")
            shutil.copyfile(xml_path, evidence_dir / "window_dump.xml")
            parsed = parse_logistics_records(xml_text, args.store_name, summary["captured_at"])
        else:
            xml_text, _xml_path, commands = capture_from_device(args.serial, args.package, evidence_dir, args.timeout)
            parsed = parse_logistics_records(xml_text, args.store_name, summary["captured_at"])
        write_json(evidence_dir / "commands.json", commands)

        write_json(evidence_dir / "parsed.json", parsed)
        responses = []
        if args.commit:
            for record in parsed["records"]:
                if args.commit_via_ssh:
                    responses.append(post_logistics_record_via_ssh(args.commit_via_ssh, args.token, record, args.timeout))
                else:
                    responses.append(post_logistics_record(args.server, args.token, record, args.timeout))
        summary.update(
            {
                "ok": True,
                "record_count": len(parsed["records"]),
                "detail_count": parsed.get("detail_count", 0),
                "records_written": len(responses),
                "pickup_codes": [item.get("pickup_code") for item in parsed["records"] if item.get("pickup_code")],
                "tracking_numbers": [item.get("tracking_number") for item in parsed["records"] if item.get("tracking_number")],
                "evidence_dir": str(evidence_dir),
            }
        )
        write_json(evidence_dir / "summary.json", summary)
        if responses:
            write_json(evidence_dir / "api_responses.json", responses)
        write_latest(evidence_dir, summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        payload = error_payload(exc, evidence_dir)
        write_json(evidence_dir / "error.json", payload)
        write_latest(evidence_dir, payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
