from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DAILY_PATH = ROOT / "business-report-dashboard" / "data" / "latest.json"
REPLY_RECORDS_PATH = Path(os.environ.get("REVIEW_REPLY_RECORDS_PATH", ROOT / "data" / "review_reply_records.json"))
OUTPUT_DIR = ROOT / "outputs" / "review_action_status"
LATEST_PATH = OUTPUT_DIR / "latest.json"


def read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def reply_suggestion(store: str, keywords: list[str], examples: list[str]) -> str:
    joined = "、".join(keywords)
    if any(keyword in joined for keyword in ("漏放", "少送", "缺")):
        return f"{store}先核对出餐打包清单和监控；回复时先致歉，说明会复核漏放环节，并按平台规则补偿或联系顾客。"
    if any(keyword in joined for keyword in ("糊", "口感", "口味", "老", "硬", "苦")):
        return f"{store}先复盘对应时段出品和牛排熟度；回复时先致歉，说明已反馈后厨调整火候和品控。"
    if examples:
        return f"{store}先查看差评原文和订单详情；回复时承认体验问题，说明已复核出餐、配送和售后处理。"
    return f"{store}先查看平台评价详情；回复前确认订单、出餐、配送和售后记录。"


def completed_records(records: dict[str, Any], target_date: str) -> list[dict[str, Any]]:
    completed = []
    for record in records.get("records") or []:
        if record.get("status") not in {"replied", "done", "closed"}:
            continue
        if target_date and record.get("date") and record.get("date") != target_date:
            continue
        completed.append(record)
    return completed


def completion_index(records: list[dict[str, Any]]) -> dict[str, Any]:
    index: dict[str, Any] = {}
    for record in records:
        store = str(record.get("store") or "").strip()
        if not store:
            continue
        entry = index.setdefault(store, {"store_done": False, "platforms": set(), "records": []})
        platform = str(record.get("platform") or "").strip()
        if platform:
            entry["platforms"].add(platform)
        else:
            entry["store_done"] = True
        entry["records"].append(record)
    return index


def evidence_for(record: dict[str, Any]) -> dict[str, Any]:
    url = str(record.get("evidence_url") or record.get("reply_url") or "").strip()
    path = str(record.get("evidence_path") or record.get("screenshot") or "").strip()
    return {
        "status": "ready" if url or path else "missing",
        "url": url,
        "path": path,
        "message": "已记录回复证据。" if url or path else "已回复但缺平台截图或链接证据。",
    }


def enrich_completed_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched = []
    for record in records:
        row = dict(record)
        row["evidence"] = evidence_for(record)
        enriched.append(row)
    return enriched


def build_action_items(review: dict[str, Any], completed: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    items: list[dict[str, Any]] = []
    completed_index = completion_index(completed)
    completed_negative_count = 0
    for store, payload in (review.get("stores") or {}).items():
        negative_count = int(payload.get("negative_count") or 0)
        if negative_count <= 0:
            continue
        completion = completed_index.get(store) or {}
        if completion.get("store_done"):
            completed_negative_count += negative_count
            continue
        platforms = []
        for platform, detail in (payload.get("platforms") or {}).items():
            platform_negative = int(detail.get("negative_count") or 0)
            if platform in (completion.get("platforms") or set()):
                completed_negative_count += platform_negative
                continue
            if platform_negative:
                platforms.append(
                    {
                        "platform": platform,
                        "negative_count": platform_negative,
                        "review_count": int(detail.get("review_count") or 0),
                        "avg_rating": float(detail.get("review_avg_rating") or detail.get("avg_rating") or 0),
                    }
                )
        if platforms:
            negative_count = sum(int(item["negative_count"]) for item in platforms)
        elif completion.get("platforms"):
            continue
        keywords = [str(item) for item in payload.get("top_keywords") or [] if item]
        examples = [str(item) for item in payload.get("bad_review_examples") or payload.get("examples") or [] if item]
        items.append(
            {
                "store": store,
                "date": payload.get("date") or review.get("used_date") or "",
                "status": "waiting_reply",
                "negative_count": negative_count,
                "review_count": int(payload.get("review_count") or 0),
                "avg_rating": float(payload.get("review_avg_rating") or payload.get("avg_rating") or 0),
                "platforms": platforms,
                "keywords": keywords,
                "examples": examples[:2],
                "reply_suggestion": reply_suggestion(store, keywords, examples),
                "human_action": "先在对应平台查看评价和订单，再回复顾客；涉及漏放、糊焦、口味问题时同步门店复盘。",
            }
        )
    return sorted(items, key=lambda item: (-int(item["negative_count"]), item["store"])), completed_negative_count


def build_status(daily: dict[str, Any]) -> dict[str, Any]:
    review = daily.get("review_summary") or {}
    target_date = review.get("used_date") or review.get("target_date") or ""
    records_payload = read_json(REPLY_RECORDS_PATH, {"records": []})
    completed = completed_records(records_payload, target_date)
    completed_with_evidence = enrich_completed_records(completed)
    missing_evidence = [record for record in completed_with_evidence if (record.get("evidence") or {}).get("status") == "missing"]
    items, completed_negative_count = build_action_items(review, completed)
    total_negative = sum(int(item["negative_count"]) for item in items)
    if not review:
        status = "missing"
        message = "评价汇总尚未生成。"
    elif review.get("status") in {"missing", "stale"}:
        status = "stale" if review.get("status") == "stale" else "missing"
        message = review.get("message") or "评价数据未同步到最新日期。"
    elif total_negative:
        status = "waiting_reply"
        message = f"发现 {total_negative} 条疑似问题评价，涉及 {len(items)} 家门店，需人工回复和复盘。"
    else:
        status = "ok"
        message = "当前评价汇总未发现待处理差评。"
    return {
        "generated_at": now_text(),
        "status": status,
        "message": message,
        "source": "business-report-dashboard/data/latest.json",
        "reply_records_source": "data/review_reply_records.json",
        "review_status": review.get("status", ""),
        "target_date": review.get("target_date", ""),
        "used_date": review.get("used_date", ""),
        "summary": {
            "store_action_count": len(items),
            "negative_count": total_negative,
            "completed_record_count": len(completed),
            "completed_negative_count": completed_negative_count,
            "completed_with_evidence_count": len(completed_with_evidence) - len(missing_evidence),
            "missing_evidence_count": len(missing_evidence),
            "review_store_count": len(review.get("stores") or {}),
        },
        "items": items,
        "completed_items": completed_with_evidence[:20],
        "missing_evidence_items": missing_evidence[:20],
        "human_action": items[0]["reply_suggestion"] if items else (missing_evidence[0]["evidence"]["message"] if missing_evidence else ""),
    }


def main() -> int:
    daily = read_json(DAILY_PATH, {})
    status = build_status(daily)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LATEST_PATH.chmod(0o644)
    print(status["message"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
