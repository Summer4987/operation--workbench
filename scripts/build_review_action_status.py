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
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


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
    path_obj = Path(path).expanduser() if path else None
    if path_obj and not path_obj.is_absolute():
        path_obj = ROOT / path_obj
    path_exists = bool(path_obj and path_obj.exists())
    web_path = ""
    if path_exists and path_obj:
        try:
            web_path = path_obj.resolve().relative_to(ROOT).as_posix()
        except ValueError:
            web_path = ""
    platform_arg = f" --platform {record.get('platform')}" if record.get("platform") else ""
    attach_command = (
        f"python3 scripts/attach_review_reply_evidence.py --store {record.get('store')} --date {record.get('date')}"
        f"{platform_arg} --file '<平台截图路径>'"
    )
    evidence_type = "image" if path_obj and path_obj.suffix.lower() in IMAGE_SUFFIXES else ("link" if url else "")
    return {
        "status": "ready" if url or path_exists else "missing",
        "url": url,
        "path": path,
        "path_exists": path_exists,
        "web_path": web_path,
        "type": evidence_type,
        "attach_command": attach_command,
        "message": "已记录回复证据。" if url or path_exists else "已回复但缺平台截图或链接证据。",
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


def reply_plan(items: list[dict[str, Any]]) -> dict[str, Any]:
    top_items = []
    for item in items[:5]:
        platforms = "、".join(
            f"{platform.get('platform')} {platform.get('negative_count')} 条"
            for platform in item.get("platforms") or []
            if platform.get("platform")
        )
        keywords = "、".join(item.get("keywords") or [])
        detail_parts = [
            f"{item.get('store')} {item.get('date')}",
            platforms or f"{item.get('negative_count', 0)} 条",
            f"关键词：{keywords}" if keywords else "",
            item.get("reply_suggestion") or item.get("human_action") or "",
        ]
        top_items.append("，".join(part for part in detail_parts if part))
    record_commands = []
    for item in items[:3]:
        platforms = [platform.get("platform") for platform in item.get("platforms") or [] if platform.get("platform")]
        platform_arg = f" --platform {platforms[0]}" if platforms else ""
        record_commands.append(
            f"python3 scripts/record_review_reply.py --store {item.get('store')} --date {item.get('date')}{platform_arg} --note '<回复摘要>' --evidence-url '<平台截图或评价链接>'"
        )
    next_action = "；".join(top_items)
    if record_commands:
        next_action = f"{next_action}；回复后记录：{record_commands[0]}" if next_action else f"回复后记录：{record_commands[0]}"
    return {
        "status": "waiting_reply" if items else "clear",
        "item_count": len(items),
        "top_items": top_items,
        "record_commands": record_commands,
        "next_action": next_action or "当前没有待回复评价。",
        "message": f"当前 {len(items)} 家门店有疑似问题评价待回复。"
        if items
        else "当前没有待回复评价。",
    }


def review_issue_type(keywords: list[str], examples: list[str]) -> str:
    joined = "、".join([*keywords, *examples])
    if any(keyword in joined for keyword in ("漏放", "少送", "缺")):
        return "打包漏放"
    if any(keyword in joined for keyword in ("糊", "苦", "火候")):
        return "出品火候"
    if any(keyword in joined for keyword in ("口感", "口味", "老", "硬")):
        return "口味口感"
    if any(keyword in joined for keyword in ("配送", "骑手", "撒", "慢")):
        return "配送体验"
    return "顾客体验"


def review_recap_action(store: str, issue_type: str) -> str:
    if issue_type == "打包漏放":
        return f"{store}复查出餐打包清单、监控和交接口令；晚高峰安排二次核单，次日抽查 5 单。"
    if issue_type == "出品火候":
        return f"{store}复盘对应时段牛排火候、报废标准和出餐质检；班前重新确认糊焦拦截规则。"
    if issue_type == "口味口感":
        return f"{store}抽查牛排熟度、保温时间和酱汁稳定性；把差评原文同步后厨做当日复盘。"
    if issue_type == "配送体验":
        return f"{store}核对打包密封、出餐等待和平台配送异常；必要时调整备餐节奏。"
    return f"{store}查看差评订单、出餐和售后记录；把共性问题写入门店班后复盘。"


def build_recap_plan(items: list[dict[str, Any]], completed_with_evidence: list[dict[str, Any]]) -> dict[str, Any]:
    recaps = []
    for item in items[:5]:
        issue_type = review_issue_type(item.get("keywords") or [], item.get("examples") or [])
        platforms = "、".join(
            f"{platform.get('platform')} {platform.get('negative_count')} 条"
            for platform in item.get("platforms") or []
            if platform.get("platform")
        )
        recaps.append(
            {
                "store": item.get("store", ""),
                "date": item.get("date", ""),
                "status": "waiting_reply",
                "issue_type": issue_type,
                "negative_count": int(item.get("negative_count") or 0),
                "platforms": platforms or f"{int(item.get('negative_count') or 0)} 条",
                "keywords": item.get("keywords") or [],
                "evidence": "；".join(item.get("examples") or []) or platforms,
                "root_cause": f"疑似{issue_type}影响评价体验。",
                "action": review_recap_action(str(item.get("store") or ""), issue_type),
                "follow_up_metric": "连续 7 天观察差评数、评价均分、下单转化和同品类退款/售后反馈。",
            }
        )
    for record in completed_with_evidence[:3]:
        evidence = record.get("evidence") or {}
        issue_type = "已回复复盘"
        recaps.append(
            {
                "store": record.get("store", ""),
                "date": record.get("date", ""),
                "status": "replied_with_evidence" if evidence.get("status") == "ready" else "replied_waiting_evidence",
                "issue_type": issue_type,
                "negative_count": int(record.get("negative_count") or 0),
                "platforms": record.get("platform", "") or "平台未区分",
                "keywords": [],
                "evidence": evidence.get("url") or evidence.get("web_path") or evidence.get("path") or record.get("note", ""),
                "root_cause": record.get("note") or "已记录人工回复，等待沉淀门店复盘结果。",
                "action": f"{record.get('store', '对应门店')}把回复结果同步到班后复盘；有证据后复看 7 天评价变化。",
                "follow_up_metric": "连续 7 天观察同类差评是否复发，若复发则升级为门店 SOP 检查。",
            }
        )
    return {
        "status": "ready" if recaps else "empty",
        "item_count": len(recaps),
        "items": recaps[:8],
        "message": f"已生成 {len(recaps)} 条评价复盘建议。" if recaps else "当前没有可生成的评价复盘建议。",
    }


def evidence_plan(missing_evidence: list[dict[str, Any]], completed_with_evidence: list[dict[str, Any]]) -> dict[str, Any]:
    missing_items = []
    attach_commands = []
    for record in missing_evidence[:5]:
        evidence = record.get("evidence") or {}
        platform = f" {record.get('platform')}" if record.get("platform") else ""
        missing_items.append(f"{record.get('store')} {record.get('date')}{platform} 已回复但缺平台截图或链接证据")
        if evidence.get("attach_command"):
            attach_commands.append(evidence["attach_command"])
    ready_count = sum(1 for record in completed_with_evidence if (record.get("evidence") or {}).get("status") == "ready")
    if missing_items:
        next_action = f"{'；'.join(missing_items)}；补证据：{attach_commands[0]}" if attach_commands else "；".join(missing_items)
    else:
        next_action = "已回复评价均有平台截图或链接证据。" if completed_with_evidence else "当前没有已回复评价记录。"
    return {
        "status": "waiting_evidence" if missing_items else ("closed" if completed_with_evidence else "empty"),
        "missing_count": len(missing_evidence),
        "ready_count": ready_count,
        "completed_count": len(completed_with_evidence),
        "missing_items": missing_items,
        "attach_commands": attach_commands,
        "next_action": next_action,
        "message": f"已回复评价中有 {len(missing_evidence)} 条缺平台截图或链接证据。"
        if missing_items
        else ("已回复评价证据均已闭环。" if completed_with_evidence else "当前没有已回复评价记录。"),
    }


def build_status(daily: dict[str, Any]) -> dict[str, Any]:
    review = daily.get("review_summary") or {}
    target_date = review.get("used_date") or review.get("target_date") or ""
    records_payload = read_json(REPLY_RECORDS_PATH, {"records": []})
    completed = completed_records(records_payload, target_date)
    completed_with_evidence = enrich_completed_records(completed)
    missing_evidence = [record for record in completed_with_evidence if (record.get("evidence") or {}).get("status") == "missing"]
    items, completed_negative_count = build_action_items(review, completed)
    plan = reply_plan(items)
    evidence = evidence_plan(missing_evidence, completed_with_evidence)
    recap = build_recap_plan(items, completed_with_evidence)
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
    elif missing_evidence:
        status = "waiting_evidence"
        message = f"评价已回复，但还有 {len(missing_evidence)} 条缺平台截图或链接证据。"
    else:
        status = "ok"
        message = "当前评价汇总未发现待处理差评。"
    workflow = {
        "reply_status": "waiting_reply" if items else "clear",
        "evidence_status": evidence["status"],
        "overall_status": status,
        "next_action": plan["next_action"] if items else evidence["next_action"],
        "closed": not items and not missing_evidence and bool(review),
    }
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
        "reply_plan": plan,
        "evidence_plan": evidence,
        "recap_plan": recap,
        "workflow": workflow,
        "completed_items": completed_with_evidence[:20],
        "missing_evidence_items": missing_evidence[:20],
        "human_action": items[0]["reply_suggestion"] if items else (evidence["next_action"] if missing_evidence else ""),
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
