from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from task_run_state import classify_failure_text, record_task_event


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "inventory_health"
LATEST_PATH = OUTPUT_DIR / "latest.json"
DEFAULT_SERVER = "http://139.155.148.169"
TASK_ID = "flow.inventory"


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def write_latest(payload: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LATEST_PATH.chmod(0o644)


def fetch_inventory_summary(server: str, timeout: int) -> dict[str, Any]:
    url = f"{server.rstrip('/')}/api/summary"
    with urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def normalize_summary(payload: dict[str, Any], server: str) -> dict[str, Any]:
    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError("库存云端 /api/summary 缺少 items 列表。")
    stats = payload.get("stats")
    if not isinstance(stats, dict):
        raise ValueError("库存云端 /api/summary 缺少 stats 对象。")

    product_count = int(stats.get("product_count") or len(items))
    warning_count = int(stats.get("warning_count") or 0)
    if product_count <= 0:
        raise ValueError("库存云端没有返回任何商品。")

    warning_items = []
    for item in items:
        try:
            balance = float(item.get("balance") or 0)
            threshold = float(item.get("warning_threshold") or 0)
        except Exception:
            continue
        if balance <= threshold:
            warning_items.append(
                {
                    "sku": item.get("sku", ""),
                    "name": item.get("name", ""),
                    "balance": balance,
                    "warning_threshold": threshold,
                    "unit": item.get("unit", ""),
                }
            )

    return {
        "generated_at": now_text(),
        "status": "ok",
        "source": "cloud",
        "server": server.rstrip("/"),
        "stats": {
            "product_count": product_count,
            "warning_count": warning_count,
        },
        "warning_items": warning_items[:12],
        "message": f"库存云端可访问：{product_count} 个商品，预警 {warning_count} 项。",
    }


def build_failed_payload(server: str, exc: Exception) -> dict[str, Any]:
    message = f"库存云端健康检查失败：{exc}"
    return {
        "generated_at": now_text(),
        "status": "failed",
        "source": "cloud",
        "server": server.rstrip("/"),
        "message": message,
        "failure_type": classify_failure_text(message),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="检查库存云端服务并写入 AI 业务中心任务状态")
    parser.add_argument("--server", default=DEFAULT_SERVER, help="库存云端服务地址")
    parser.add_argument("--timeout", type=int, default=8, help="请求超时秒数")
    parser.add_argument("--strict", action="store_true", help="健康检查失败时返回非 0")
    args = parser.parse_args()

    record_task_event(TASK_ID, "running", message="库存云端健康检查开始。", step="cloud-summary")
    try:
        payload = normalize_summary(fetch_inventory_summary(args.server, args.timeout), args.server)
        write_latest(payload)
        record_task_event(
            TASK_ID,
            "success",
            message=payload["message"],
            step="cloud-summary",
            log_path=LATEST_PATH,
            extra={"warning_count": payload["stats"]["warning_count"]},
        )
        print(payload["message"])
        return 0
    except Exception as exc:
        payload = build_failed_payload(args.server, exc)
        write_latest(payload)
        record_task_event(
            TASK_ID,
            "failed",
            message=payload["message"],
            step="cloud-summary",
            log_path=LATEST_PATH,
            failure_type=payload["failure_type"],
        )
        print(payload["message"], file=sys.stderr)
        return 1 if args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
