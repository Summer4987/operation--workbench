from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "outputs" / "store_inspection"
OUTPUT_DIR = ROOT / "outputs" / "store_inspection_evidence_manifest"
LATEST_PATH = OUTPUT_DIR / "latest.json"
EVIDENCE_SUFFIXES = {".png", ".jpg", ".jpeg", ".json"}
PLATFORM_TOKENS = {
    "饿了么": ("eleme", "饿了么"),
    "美团": ("meituan", "美团"),
}


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def evidence_kind(path: Path) -> str:
    name = path.name.lower()
    if name.endswith(".ocr.json"):
        return "ocr"
    if path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
        return "screenshot"
    return "data"


def platform_for(path: Path) -> str:
    name = path.name.lower()
    for platform, tokens in PLATFORM_TOKENS.items():
        if any(str(token).lower() in name for token in tokens):
            return platform
    return "未知平台"


def file_item(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path.relative_to(ROOT)),
        "platform": platform_for(path),
        "kind": evidence_kind(path),
        "updated_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        "size": stat.st_size,
    }


def collect_items(date_text: str, days: int, limit: int) -> list[dict[str, Any]]:
    if not SOURCE_DIR.exists():
        return []
    end_date = datetime.strptime(date_text, "%Y-%m-%d").date()
    start_date = end_date - timedelta(days=max(days - 1, 0))
    items = []
    for path in SOURCE_DIR.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in EVIDENCE_SUFFIXES:
            continue
        if " 2." in path.name:
            continue
        updated_date = datetime.fromtimestamp(path.stat().st_mtime).date()
        if start_date <= updated_date <= end_date:
            items.append(file_item(path))
    return sorted(items, key=lambda item: item["updated_at"], reverse=True)[:limit]


def build_manifest(date_text: str, days: int, limit: int) -> dict[str, Any]:
    items = collect_items(date_text, days, limit)
    total_bytes = sum(int(item.get("size") or 0) for item in items)
    platforms = sorted({item.get("platform", "") for item in items if item.get("platform")})
    return {
        "generated_at": now_text(),
        "status": "ready" if items else "missing",
        "source_dir": "outputs/store_inspection",
        "date": date_text,
        "days": days,
        "summary": {
            "file_count": len(items),
            "total_size": total_bytes,
            "platforms": platforms,
            "screenshot_count": sum(1 for item in items if item.get("kind") == "screenshot"),
            "ocr_count": sum(1 for item in items if item.get("kind") == "ocr"),
            "data_count": sum(1 for item in items if item.get("kind") == "data"),
        },
        "retention": {
            "local_days": int(os.environ.get("OPERATION_CLEAN_EVIDENCE_DAYS", "3")),
            "local_max_mb": int(os.environ.get("OPERATION_CLEAN_EVIDENCE_MAX_MB", "800")),
            "cloud_days": int(os.environ.get("OPERATION_CLOUD_EVIDENCE_RETAIN_DAYS", "14")),
        },
        "items": items,
        "message": f"已索引 {len(items)} 个巡检截图/OCR证据。"
        if items
        else f"未找到 {date_text} 往前 {days} 天内的巡检截图或 OCR 证据。",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="生成巡检截图和 OCR 证据清单")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"), help="证据日期，默认今天")
    parser.add_argument("--days", type=int, default=1, help="向前包含天数，默认 1")
    parser.add_argument("--limit", type=int, default=500, help="最多写入的证据文件数")
    args = parser.parse_args()

    manifest = build_manifest(args.date, max(args.days, 1), max(args.limit, 1))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LATEST_PATH.chmod(0o644)
    print(manifest["message"])
    print(f"证据清单已生成：{LATEST_PATH}")


if __name__ == "__main__":
    main()
