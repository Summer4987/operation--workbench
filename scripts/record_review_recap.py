from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RECORDS_PATH = Path(os.environ.get("REVIEW_RECAP_RECORDS_PATH", ROOT / "data" / "review_recap_records.json"))


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
    parser = argparse.ArgumentParser(description="记录评价差评门店复盘结果，用于追踪建议是否执行和是否复发。")
    parser.add_argument("--store", required=True, help="门店名称，需和评价复盘建议一致。")
    parser.add_argument("--date", required=True, help="评价归属日期，例如 2026-06-10。")
    parser.add_argument("--issue-type", default="", help="问题类型，例如 出品火候、打包漏放。")
    parser.add_argument("--operator", default="", help="复盘人，可选。")
    parser.add_argument("--result", required=True, help="复盘结论或已执行动作。")
    parser.add_argument("--follow-up", default="", help="后续观察安排，可选。")
    parser.add_argument("--metric-note", default="", help="7 天观察指标备注，可选。")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = read_json(RECORDS_PATH)
    records = payload.setdefault("records", [])
    record = {
        "recorded_at": now_text(),
        "status": "recorded",
        "store": args.store.strip(),
        "date": args.date.strip(),
        "issue_type": args.issue_type.strip(),
        "operator": args.operator.strip(),
        "result": args.result.strip(),
        "follow_up": args.follow_up.strip(),
        "metric_note": args.metric_note.strip(),
    }
    records.append(record)
    payload["updated_at"] = record["recorded_at"]
    payload["records"] = records
    write_json(RECORDS_PATH, payload)
    issue_text = f" {record['issue_type']}" if record["issue_type"] else ""
    print(f"已记录：{record['date']} {record['store']}{issue_text} 评价复盘。")
    print("下一步运行：python3 scripts/build_review_action_status.py && python3 scripts/build_workbench_data.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
