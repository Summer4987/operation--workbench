from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RECORDS_PATH = Path(os.environ.get("PROMO_BID_DECISIONS_PATH", ROOT / "data" / "promo_bid_decisions.json"))
QUEUE_PATH = ROOT / "outputs" / "promo_bid_approval_queue" / "latest.json"
VALID_DECISIONS = {"approve", "skip", "manual_review"}


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
    parser = argparse.ArgumentParser(description="记录推广出价建议的人工审批结果；本脚本只写本地记录，不提交平台。")
    parser.add_argument("--approval-id", required=True, help="审批队列中的 approval_id。")
    parser.add_argument("--decision", required=True, choices=sorted(VALID_DECISIONS), help="approve / skip / manual_review。")
    parser.add_argument("--operator", default="", help="审批人，可选。")
    parser.add_argument("--note", default="", help="审批备注，可选。")
    parser.add_argument("--allow-unknown", action="store_true", help="允许记录当前审批队列里不存在的 approval_id，默认不允许。")
    return parser.parse_args()


def validate_approval_id(approval_id: str, allow_unknown: bool) -> None:
    queue = read_json(QUEUE_PATH)
    if not queue or allow_unknown:
        return
    valid_ids = {str(item.get("approval_id") or "") for item in queue.get("items") or []}
    if approval_id not in valid_ids:
        examples = "、".join(sorted(item for item in valid_ids if item)[:3])
        raise SystemExit(
            f"审批 ID 不在当前队列中：{approval_id}。\n"
            f"请先运行 python3 scripts/build_promo_bid_approval_queue.py 查看最新 approval_id。"
            + (f"\n示例：{examples}" if examples else "")
        )


def main() -> int:
    args = parse_args()
    approval_id = args.approval_id.strip()
    validate_approval_id(approval_id, args.allow_unknown)
    payload = read_json(RECORDS_PATH)
    records = payload.setdefault("records", [])
    record = {
        "recorded_at": now_text(),
        "approval_id": approval_id,
        "decision": args.decision.strip(),
        "operator": args.operator.strip(),
        "note": args.note.strip(),
    }
    records.append(record)
    payload["updated_at"] = record["recorded_at"]
    payload["records"] = records
    write_json(RECORDS_PATH, payload)
    print(f"已记录推广出价审批：{record['approval_id']} -> {record['decision']}。")
    print("下一步运行：python3 scripts/build_promo_bid_approval_queue.py && python3 scripts/build_user_action_queue.py && python3 scripts/build_workbench_data.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
