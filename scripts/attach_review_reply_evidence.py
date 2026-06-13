from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RECORDS_PATH = Path(os.environ.get("REVIEW_REPLY_RECORDS_PATH", ROOT / "data" / "review_reply_records.json"))
EVIDENCE_DIR = Path(os.environ.get("REVIEW_REPLY_EVIDENCE_DIR", ROOT / "outputs" / "review_reply_evidence"))


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"records": []}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


def safe_name(text: str) -> str:
    value = re.sub(r"[^0-9A-Za-z._-]+", "_", text.strip())
    value = re.sub(r"_+", "_", value).strip("._-")
    return value or "review"


def relative_to_root(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="给已回复评价补充平台截图、评价链接或工单链接证据。")
    parser.add_argument("--store", required=True, help="门店名称，需和评价回复记录一致。")
    parser.add_argument("--date", required=True, help="评价归属日期，例如 2026-06-10。")
    parser.add_argument("--platform", default="", help="平台名称；留空匹配该门店当天未区分平台的记录。")
    parser.add_argument("--file", default="", help="本地平台截图文件路径；会复制到 outputs/review_reply_evidence。")
    parser.add_argument("--evidence-url", default="", help="平台评价链接、回复截图链接或工单链接。")
    parser.add_argument("--note", default="", help="补证据备注，可选。")
    return parser.parse_args()


def find_record(records: list[dict[str, Any]], store: str, date: str, platform: str) -> dict[str, Any] | None:
    for record in reversed(records):
        if str(record.get("status") or "") not in {"replied", "done", "closed"}:
            continue
        if str(record.get("store") or "").strip() != store:
            continue
        if str(record.get("date") or "").strip() != date:
            continue
        if platform and str(record.get("platform") or "").strip() != platform:
            continue
        if not platform and str(record.get("platform") or "").strip():
            continue
        return record
    return None


def copy_evidence_file(source_text: str, store: str, date: str, platform: str) -> str:
    source = Path(source_text).expanduser()
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"证据文件不存在：{source}")
    target_dir = EVIDENCE_DIR / date
    target_dir.mkdir(parents=True, exist_ok=True)
    suffix = source.suffix.lower() or ".png"
    stamp = datetime.now().strftime("%H%M%S")
    target_name = f"{safe_name(store)}_{safe_name(platform or 'all')}_{stamp}{suffix}"
    target = target_dir / target_name
    shutil.copy2(source, target)
    target.chmod(0o644)
    return relative_to_root(target)


def main() -> int:
    args = parse_args()
    if not args.file and not args.evidence_url:
        print("需要提供 --file 或 --evidence-url。")
        return 2

    store = args.store.strip()
    date = args.date.strip()
    platform = args.platform.strip()
    payload = read_json(RECORDS_PATH)
    records = payload.setdefault("records", [])
    record = find_record(records, store, date, platform)
    if record is None:
        print("没有找到匹配的已回复评价记录。请先运行 scripts/record_review_reply.py 记录回复。")
        return 2

    if args.file:
        record["evidence_path"] = copy_evidence_file(args.file, store, date, platform)
        record["evidence_original_path"] = str(Path(args.file).expanduser())
    if args.evidence_url:
        record["evidence_url"] = args.evidence_url.strip()
    if args.note:
        record["evidence_note"] = args.note.strip()
    record["evidence_attached_at"] = now_text()
    payload["updated_at"] = record["evidence_attached_at"]
    write_json(RECORDS_PATH, payload)

    platform_text = f"{platform} " if platform else ""
    print(f"已补充证据：{date} {platform_text}{store}。")
    print("下一步运行：python3 scripts/build_review_action_status.py && python3 scripts/build_workbench_data.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
