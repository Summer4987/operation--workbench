from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DAILY_PATH = ROOT / "business-report-dashboard" / "data" / "latest.json"
OUTPUT_DIR = ROOT / "outputs" / "daily_focus_status"
LATEST_PATH = OUTPUT_DIR / "latest.json"


def read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def action_for(title: str, body: str) -> str:
    text = f"{title} {body}"
    if "收入" in text or "单量" in text:
        return "先核对平台营业状态、活动资源和曝光变化，再看客单价、转化和差评是否同步恶化。"
    if "下单转化" in text:
        return "先检查菜品排序、主图、优惠力度、配送费和起送价，再对照差评关键词。"
    if "进店转化" in text:
        return "先检查门店封面、招牌品、活动标签、平台搜索推荐位置和曝光来源。"
    if "曝光" in text:
        return "先检查平台入口、活动资源、营业时段、门店排名和是否被限流。"
    if "无订单" in text:
        return "立刻确认门店营业状态、平台在线状态、配送范围和是否被平台下线。"
    return body or "先打开日报看板查看异常详情，再按门店核对平台后台。"


def build_items(daily: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    priority = {"high": 0, "medium": 1, "good": 2}
    for item in daily.get("focus_items") or []:
        store = str(item.get("store") or "未命名门店")
        entry = grouped.setdefault(
            store,
            {
                "store": store,
                "status": "waiting_review",
                "level": "good",
                "high_count": 0,
                "medium_count": 0,
                "issues": [],
                "action": "",
            },
        )
        level = str(item.get("level") or "medium")
        if level == "high":
            entry["high_count"] += 1
        elif level == "medium":
            entry["medium_count"] += 1
        if priority.get(level, 9) < priority.get(entry["level"], 9):
            entry["level"] = level
        issue = {
            "level": level,
            "title": item.get("title", ""),
            "body": item.get("body", ""),
            "action": action_for(str(item.get("title") or ""), str(item.get("body") or "")),
        }
        entry["issues"].append(issue)
    rows = []
    for entry in grouped.values():
        first_issue = entry["issues"][0] if entry["issues"] else {}
        entry["action"] = first_issue.get("action", "先打开日报看板查看异常详情。")
        rows.append(entry)
    return sorted(rows, key=lambda item: (-int(item["high_count"]), -int(item["medium_count"]), item["store"]))


def build_status(daily: dict[str, Any]) -> dict[str, Any]:
    generated_at = daily.get("generated_at", "")
    source_dates = daily.get("source_dates") or []
    latest_date = source_dates[-1] if source_dates else ""
    items = build_items(daily)
    high_count = sum(int(item["high_count"]) for item in items)
    medium_count = sum(int(item["medium_count"]) for item in items)
    if not daily:
        status = "missing"
        message = "日报数据尚未生成。"
    elif items:
        status = "waiting_review"
        message = f"{latest_date or '最新日报'} 发现 {len(items)} 家异常门店，{high_count} 项高优先级异常。"
    else:
        status = "ok"
        message = f"{latest_date or '最新日报'} 暂无需要重点处理的日报异常。"
    return {
        "generated_at": now_text(),
        "source_generated_at": generated_at,
        "source": "business-report-dashboard/data/latest.json",
        "status": status,
        "message": message,
        "latest_date": latest_date,
        "summary": {
            "store_action_count": len(items),
            "high_count": high_count,
            "medium_count": medium_count,
        },
        "items": items,
        "human_action": items[0]["action"] if items else "",
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
