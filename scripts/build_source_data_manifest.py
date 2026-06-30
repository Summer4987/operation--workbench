from __future__ import annotations

import json
import os
import socket
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "data" / "source-sync-manifest.json"

LIGHT_SOURCE_PATHS = [
    "business-report-dashboard/data/latest.json",
    "business-report-dashboard/data/unified_daily.csv",
    "business-report-dashboard/data/unified_reviews.csv",
    "business-report-dashboard/data/raw",
    "business-report-dashboard/data/reviews/raw",
    "data/realtime-history.json",
    "outputs/current_budget",
    "outputs/dianjin_automation",
    "outputs/meituan_budget_automation",
    "outputs/promo_budget_preview",
    "outputs/realtime_order_income",
    "store-inspection/latest.json",
    "store-inspection/latest-data.js",
]

HEAVY_SOURCE_PATHS = [
    "outputs/store_inspection",
]

EXCLUDE_DIRS = {".git", ".venv", "__pycache__", "chrome-profile", "node_modules"}
EXCLUDE_FILES = {".DS_Store"}


def is_included_file(path: Path) -> bool:
    if any(part in EXCLUDE_DIRS for part in path.parts):
        return False
    if path.name in EXCLUDE_FILES:
        return False
    return path.is_file()


def file_entry(path: Path) -> dict:
    stat = path.stat()
    return {
        "path": str(path.relative_to(ROOT)),
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
    }


def collect_path(relative_path: str) -> dict:
    path = ROOT / relative_path
    if not path.exists():
        return {
            "path": relative_path,
            "exists": False,
            "file_count": 0,
            "total_bytes": 0,
            "latest_files": [],
        }

    files = [path] if path.is_file() else [item for item in path.rglob("*") if is_included_file(item)]
    files = [item for item in files if is_included_file(item)]
    latest = sorted(files, key=lambda item: item.stat().st_mtime, reverse=True)[:10]
    return {
        "path": relative_path,
        "exists": True,
        "file_count": len(files),
        "total_bytes": sum(item.stat().st_size for item in files),
        "latest_files": [file_entry(item) for item in latest],
    }


def summarize(items: list[dict]) -> dict:
    return {
        "existing_sources": sum(1 for item in items if item["exists"]),
        "missing_sources": [item["path"] for item in items if not item["exists"]],
        "file_count": sum(item["file_count"] for item in items),
        "total_bytes": sum(item["total_bytes"] for item in items),
    }


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    light_sources = [collect_path(path) for path in LIGHT_SOURCE_PATHS]
    heavy_sources = [collect_path(path) for path in HEAVY_SOURCE_PATHS]
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "host": socket.gethostname(),
        "cwd": str(ROOT),
        "mode": "light_default",
        "sync_root_hint": "/var/www/html/operation-source-data/macmini",
        "light_sources": light_sources,
        "heavy_sources_not_synced_by_default": heavy_sources,
        "summary": {
            "light": summarize(light_sources),
            "heavy_not_synced_by_default": summarize(heavy_sources),
        },
    }
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"源数据轻量同步清单已生成：{OUTPUT_PATH}")


if __name__ == "__main__":
    os.chdir(ROOT)
    main()
