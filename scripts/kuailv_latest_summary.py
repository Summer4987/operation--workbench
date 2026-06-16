from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LATEST_PATH = ROOT / "outputs" / "kuailv_order_dry_run" / "latest.json"


def compact_score(score: dict[str, Any] | None) -> dict[str, Any] | None:
    if not score:
        return None
    return {
        "line_name": score.get("line_name"),
        "pack_label": score.get("pack_label"),
        "allowed": score.get("allowed"),
        "score": score.get("score"),
        "reasons": score.get("reasons"),
        "excluded_hits": score.get("excluded_hits"),
        "row_text": score.get("row_text"),
        "context_text": score.get("context_text"),
        "center": score.get("center"),
    }


def main() -> int:
    path = LATEST_PATH
    if not path.exists():
        print(json.dumps({"status": "missing", "path": str(path)}, ensure_ascii=False, indent=2))
        return 1
    data = json.loads(path.read_text(encoding="utf-8"))
    plan = data.get("plan") or {}
    adb = data.get("adb") or {}
    snapshot = adb.get("snapshot") or {}
    analysis = snapshot.get("ui_analysis") or {}
    candidates = analysis.get("orange_add_candidates") or []
    tofu_recs = [
        {
            "pack_label": row.get("pack_label"),
            "allowed": row.get("allowed"),
            "selected": compact_score(row.get("selected")),
        }
        for row in analysis.get("safe_add_recommendations") or []
        if row.get("line_name") == "豆腐"
    ]
    orange_rows = []
    for candidate in candidates[:10]:
        orange_rows.append(
            {
                "center": candidate.get("center"),
                "best_allowed_match": compact_score(candidate.get("best_allowed_match")),
                "top_scores": [compact_score(score) for score in (candidate.get("line_scores") or [])[:3]],
            }
        )
    summary = {
        "generated_at": data.get("generated_at"),
        "status": data.get("status"),
        "mode": data.get("mode"),
        "order_id": plan.get("order_id"),
        "store_name": plan.get("store_name"),
        "adb_status": adb.get("status"),
        "adb_message": adb.get("message"),
        "session_dir": adb.get("session_dir"),
        "selected": compact_score(adb.get("selected")),
        "tap": adb.get("tap"),
        "before_files": (adb.get("before") or {}).get("files"),
        "after_files": (adb.get("after") or {}).get("files"),
        "after_detected_relevant": [
            text
            for text in ((adb.get("after") or {}).get("detected_text") or [])
            if any(keyword in text for keyword in ["数量", "购物车", "去结算", "提交订单", "付款"])
        ],
        "after_plan_match": (adb.get("after") or {}).get("plan_match"),
        "delivery_store_match": analysis.get("delivery_store_match"),
        "delivery_candidates": analysis.get("delivery_candidates"),
        "orange_add_candidates_count": len(candidates),
        "tofu_safe_add_recommendations": tofu_recs,
        "orange_candidates": orange_rows,
        "blocked_orange_candidates": (analysis.get("blocked_orange_candidates") or [])[:6],
        "target_hits": (snapshot.get("plan_match") or {}).get("target_hits"),
        "risk_hits": (snapshot.get("plan_match") or {}).get("risk_hits"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
