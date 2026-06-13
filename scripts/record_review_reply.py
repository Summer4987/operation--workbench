from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RECORDS_PATH = Path(os.environ.get("REVIEW_REPLY_RECORDS_PATH", ROOT / "data" / "review_reply_records.json"))


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="记录评价已人工回复，用于从评价待处理队列中扣除。")
    parser.add_argument("--store", required=True, help="门店名称，需和评价看板中的门店名一致。")
    parser.add_argument("--date", required=True, help="评价归属日期，例如 2026-06-10。")
    parser.add_argument("--platform", default="", help="平台名称；留空表示该门店当天差评已全部处理。")
    parser.add_argument("--negative-count", type=int, default=0, help="本次处理的差评数量，可选。")
    parser.add_argument("--operator", default="", help="处理人，可选。")
    parser.add_argument("--note", default="", help="处理备注，可选。")
    parser.add_argument("--evidence-url", default="", help="平台回复截图、评价链接或工单链接，可选。")
    parser.add_argument("--evidence-path", default="", help="本地截图路径，可选。")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = read_json(RECORDS_PATH)
    records = payload.setdefault("records", [])
    record = {
        "recorded_at": now_text(),
        "status": "replied",
        "store": args.store.strip(),
        "date": args.date.strip(),
        "platform": args.platform.strip(),
        "negative_count": max(0, int(args.negative_count or 0)),
        "operator": args.operator.strip(),
        "note": args.note.strip(),
        "evidence_url": args.evidence_url.strip(),
        "evidence_path": args.evidence_path.strip(),
    }
    records.append(record)
    payload["updated_at"] = record["recorded_at"]
    payload["records"] = records
    write_json(RECORDS_PATH, payload)
    platform_text = f"{record['platform']} " if record["platform"] else ""
    print(f"已记录：{record['date']} {platform_text}{record['store']} 评价已人工回复。")
    print("下一步运行：python3 scripts/build_review_action_status.py && python3 scripts/build_workbench_data.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
