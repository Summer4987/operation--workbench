from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ADVICE_PATH = ROOT / "outputs" / "promo_bid_advice" / "latest.json"
DAILY_PATH = ROOT / "business-report-dashboard" / "data" / "latest.json"
SIGNAL_DIR = ROOT / "data" / "promo-bid-signals"
TEMPLATE_PATH = SIGNAL_DIR / "templates" / "promo_bid_signal_template.csv"
OUTPUT_DIR = ROOT / "outputs" / "promo_bid_signal_status"
LATEST_PATH = OUTPUT_DIR / "latest.json"


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_latest(payload: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LATEST_PATH.chmod(0o644)


def signal_file_count() -> int:
    if not SIGNAL_DIR.exists():
        return 0
    return sum(1 for path in SIGNAL_DIR.glob("*") if path.suffix.lower() in {".csv", ".json", ".xlsx", ".xls"})


def daily_store_rows(daily: dict[str, Any]) -> list[dict[str, Any]]:
    rows = daily.get("store_summary") or daily.get("stores") or []
    return rows if isinstance(rows, list) else []


def build_payload() -> dict[str, Any]:
    advice = read_json(ADVICE_PATH)
    daily = read_json(DAILY_PATH)
    advice_summary = advice.get("summary") or {}
    daily_stores = daily_store_rows(daily)
    signal_files = signal_file_count()
    has_daily_impressions = any(float(item.get("total_impressions") or item.get("impressions") or 0) > 0 for item in daily_stores)
    has_daily_conversion = any(
        item.get("visit_conversion") not in (None, "")
        or item.get("order_conversion") not in (None, "")
        for item in daily_stores
    )
    checks = [
        {
            "id": "spend_vs_expected",
            "label": "预算消耗/预期消耗",
            "status": "ready" if int(advice_summary.get("advice_count") or 0) else "missing",
            "detail": f"出价建议中已有 {int(advice_summary.get('advice_count') or 0)} 条消耗对比。",
        },
        {
            "id": "order_trend",
            "label": "门店订单趋势",
            "status": "ready" if daily_stores else "missing",
            "detail": f"日报 latest.json 覆盖 {len(daily_stores)} 家门店，可辅助判断订单涨跌；暂未和出价建议逐项归因。",
        },
        {
            "id": "exposure",
            "label": "曝光",
            "status": "ready" if signal_files else "partial" if has_daily_impressions else "missing",
            "detail": "日报已有门店曝光汇总；仍等待平台推广明细或手工导出文件。",
        },
        {
            "id": "visit",
            "label": "进店",
            "status": "ready" if signal_files else "partial" if has_daily_conversion else "missing",
            "detail": "日报已有转化率，可间接判断进店质量；仍等待平台进店明细。",
        },
        {
            "id": "conversion",
            "label": "下单转化",
            "status": "ready" if signal_files else "partial" if has_daily_conversion else "missing",
            "detail": "日报已有转化率汇总；仍等待推广明细与出价建议逐项归因。",
        },
    ]
    missing = [item for item in checks if item["status"] == "missing"]
    partial = [item for item in checks if item["status"] == "partial"]
    status = "ready" if not missing and not partial else "partial" if missing and len(missing) < len(checks) else "missing"
    return {
        "generated_at": now_text(),
        "status": status,
        "source": {
            "advice": "outputs/promo_bid_advice/latest.json",
            "daily": "business-report-dashboard/data/latest.json",
            "signal_dir": "data/promo-bid-signals",
        },
        "summary": {
            "check_count": len(checks),
            "ready_count": sum(1 for item in checks if item["status"] == "ready"),
            "partial_count": len(partial),
            "missing_count": len(missing),
            "signal_file_count": signal_files,
            "signal_dir_ready": SIGNAL_DIR.exists(),
            "template_ready": TEMPLATE_PATH.exists(),
        },
        "setup": {
            "init_command": "python3 scripts/init_promo_bid_signals.py",
            "signal_dir": "data/promo-bid-signals",
            "template_path": "data/promo-bid-signals/templates/promo_bid_signal_template.csv",
            "signal_dir_ready": SIGNAL_DIR.exists(),
            "template_ready": TEMPLATE_PATH.exists(),
            "required_fields": ["date", "platform", "store", "period", "impressions", "visits", "orders", "spend", "current_bid", "current_budget"],
        },
        "checks": checks,
        "message": (
            f"推广出价信号输入部分就绪：{len(missing)} 项缺口，{len(partial)} 项半接入。"
            if status != "ready"
            else "推广出价信号输入已就绪。"
        ),
        "human_action": "后续把平台推广明细导出到 data/promo-bid-signals/，可参考 data/promo-bid-signals/templates/promo_bid_signal_template.csv，至少包含门店、日期、曝光、进店、订单或转化字段。",
    }


def main() -> int:
    payload = build_payload()
    write_latest(payload)
    print(payload["message"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
