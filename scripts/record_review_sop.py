from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RECORDS_PATH = Path(os.environ.get("REVIEW_SOP_RECORDS_PATH", ROOT / "data" / "review_sop_records.json"))


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
    parser = argparse.ArgumentParser(description="记录评价复发后的门店 SOP 整改，用于从复发待办进入整改闭环。")
    parser.add_argument("--store", required=True, help="门店名称。")
    parser.add_argument("--date", required=True, help="原复盘归属日期，例如 2026-06-10。")
    parser.add_argument("--issue-type", required=True, help="问题类型，例如 出品火候、打包漏放。")
    parser.add_argument("--owner", default="", help="整改负责人，可选。")
    parser.add_argument("--action", required=True, help="整改动作，例如重训、抽查、SOP 调整。")
    parser.add_argument("--due-date", default="", help="整改复查日期，可选。")
    parser.add_argument("--status", default="open", choices=["open", "checking", "closed"], help="整改状态。")
    parser.add_argument("--result", default="", help="复查结果或关闭说明，可选。")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = read_json(RECORDS_PATH)
    records = payload.setdefault("records", [])
    record = {
        "recorded_at": now_text(),
        "status": args.status.strip(),
        "store": args.store.strip(),
        "date": args.date.strip(),
        "issue_type": args.issue_type.strip(),
        "owner": args.owner.strip(),
        "action": args.action.strip(),
        "due_date": args.due_date.strip(),
        "result": args.result.strip(),
    }
    records.append(record)
    payload["updated_at"] = record["recorded_at"]
    payload["records"] = records
    write_json(RECORDS_PATH, payload)
    print(f"已记录：{record['date']} {record['store']} {record['issue_type']} SOP 整改（{record['status']}）。")
    print("下一步运行：python3 scripts/build_review_action_status.py && python3 scripts/build_workbench_data.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
