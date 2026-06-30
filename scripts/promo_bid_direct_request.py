from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "promo_bid_direct_request"
LATEST_PATH = OUTPUT_DIR / "latest.json"
EXECUTOR_LATEST_PATH = ROOT / "outputs" / "promo_bid_direct_executor" / "latest.json"

PLATFORM_ALIASES = {
    "meituan": ("美团", "美团外卖", "mt"),
    "eleme": ("饿了么", "饿了么外卖", "ele", "elm"),
}
PRICE_PATTERNS = (
    r"(?:出价|价格|点金|竞价)[^\d]{0,8}(?:调到|调整到|改到|改为|改成|设为|设置为|到)\s*(\d+(?:\.\d+)?)",
    r"(?:调到|调整到|改到|改为|改成|设为|设置为)\s*(\d+(?:\.\d+)?)",
    r"(\d+(?:\.\d+)?)\s*元",
)
ACTION_WORDS = ("出价", "点金", "竞价", "推广价", "推广价格", "cpc", "bid")


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def normalize(text: str) -> str:
    return "".join(str(text or "").lower().split())


def detect_platform(text: str) -> str:
    normalized = normalize(text)
    for platform, aliases in PLATFORM_ALIASES.items():
        if any(normalize(alias) in normalized for alias in aliases):
            return platform
    return ""


def detect_target_bid(text: str) -> float | None:
    for pattern in PRICE_PATTERNS:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        value = float(match.group(1))
        if value > 0:
            return value
    return None


def detect_store(text: str) -> str:
    cleaned = re.sub(r"\d+(?:\.\d+)?\s*元?", " ", text)
    cleaned = re.sub(r"(调到|调整到|改到|改为|改成|设为|设置为|出价|点金|推广|竞价|价格)", " ", cleaned)
    for aliases in PLATFORM_ALIASES.values():
        for alias in aliases:
            cleaned = cleaned.replace(alias, " ")
    candidates = re.findall(r"[\u4e00-\u9fa5A-Za-z0-9（）()·\-]{2,24}(?:店|门店)?", cleaned)
    stop_words = {"直接", "帮我", "把", "给我", "执行", "保存", "调整", "修改", "门店", "价格"}
    candidates = [item.strip(" ，,。.") for item in candidates if item.strip(" ，,。.") not in stop_words]
    if not candidates:
        return ""
    return max(candidates, key=len)


def detect_scope(text: str) -> str:
    quoted = re.findall(r"[「『\"]([^」』\"]+)[」』\"]", text)
    if quoted:
        return quoted[0].strip()
    if "关键词" in text:
        match = re.search(r"关键词[:：]?\s*([\u4e00-\u9fa5A-Za-z0-9（）()·\-]{2,24})", text)
        if match:
            return match.group(1).strip()
    if "点金" in text:
        return "点金推广"
    if "出价" in text:
        return "推广出价"
    return ""


def looks_like_direct_bid_request(text: str) -> bool:
    normalized = normalize(text)
    return any(normalize(word) in normalized for word in ACTION_WORDS) and bool(detect_target_bid(text))


def parse_request(text: str) -> dict[str, Any]:
    target_bid = detect_target_bid(text)
    request = {
        "platform": detect_platform(text),
        "store": detect_store(text),
        "scope": detect_scope(text),
        "target_bid": target_bid,
        "raw_text": text,
    }
    missing = []
    if not request["platform"]:
        missing.append("平台（美团/饿了么）")
    if not request["store"]:
        missing.append("门店")
    if target_bid is None:
        missing.append("目标出价")
    if not request["scope"]:
        request["scope"] = "推广出价"
    request["missing_fields"] = missing
    return request


def write_latest(payload: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LATEST_PATH.chmod(0o600)


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def run_executor(request: dict[str, Any]) -> dict[str, Any]:
    command = [
        sys.executable,
        "scripts/meituan_promo_bid_direct_executor.py",
        "--platform",
        str(request["platform"]),
        "--store",
        str(request["store"]),
        "--target-bid",
        str(request["target_bid"]),
        "--commit",
        "--json",
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=180,
    )
    payload = read_json(EXECUTOR_LATEST_PATH)
    if not payload:
        payload = {
            "status": "failed",
            "message": (completed.stdout or "").strip() or f"执行器退出码 {completed.returncode}",
            "execution": {"attempted": True, "executed": False, "reason": "executor_output_missing"},
        }
    payload["returncode"] = completed.returncode
    payload["command"] = command
    if completed.returncode != 0 and payload.get("status") in {"success", "preflight_ok"}:
        payload["status"] = "failed"
    return payload


def build_payload(text: str, *, execute: bool) -> dict[str, Any]:
    request = parse_request(text)
    generated_at = now_text()
    if request["missing_fields"]:
        return {
            "generated_at": generated_at,
            "status": "needs_clarification",
            "request": request,
            "message": "我还差" + "、".join(request["missing_fields"]) + "，补齐后我才能改出价。你可以直接说：美团 银泰城店 点金出价调到 1.8 元。",
            "execution": {"attempted": False, "executed": False, "reason": "missing_required_fields"},
        }
    if not execute:
        return {
            "generated_at": generated_at,
            "status": "ready",
            "request": request,
            "message": (
                f"已识别直接改价指令：{request['platform']}｜{request['store']}｜"
                f"{request['scope']} -> {request['target_bid']}。"
            ),
            "execution": {"attempted": False, "executed": False, "reason": "execute_not_requested"},
        }
    executor_payload = run_executor(request)
    executed = bool((executor_payload.get("execution") or {}).get("executed"))
    if executed:
        message = f"已把 {request['store']} 的{request['scope']}调到 {request['target_bid']} 元。"
    else:
        message = executor_payload.get("message") or "出价执行失败，我已记录执行日志。"
    return {
        "generated_at": generated_at,
        "status": "executed" if executed else executor_payload.get("status") or "failed",
        "request": request,
        "message": message,
        "execution": executor_payload.get("execution") or {"attempted": True, "executed": False, "reason": "execution_failed"},
        "executor": executor_payload,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="解析 Hermes 微信直接出价指令。明确价格时可进入直接执行入口。")
    parser.add_argument("text", nargs="+")
    parser.add_argument("--execute", action="store_true", help="字段完整时尝试真实执行；没有执行器时明确失败。")
    parser.add_argument("--json", action="store_true", help="输出 JSON。")
    args = parser.parse_args()
    payload = build_payload(" ".join(args.text), execute=args.execute)
    write_latest(payload)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(payload["message"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
