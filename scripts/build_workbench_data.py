from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from urllib.request import urlopen

from build_task_health import build_task_health, write_task_health


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "workbench-data.js"
DATA_DIR = ROOT / "data"
REALTIME_HISTORY_PATH = DATA_DIR / "realtime-history.json"
CLOUD_INVENTORY_URL = "http://139.155.148.169/api/summary"
CLOUD_REALTIME_HISTORY_URL = "http://139.155.148.169/operation-workbench/data/realtime-history.json"


def read_json(path: Path, fallback: dict) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def inventory_snapshot() -> dict:
    try:
        with urlopen(CLOUD_INVENTORY_URL, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        items = payload.get("items", [])
        stats = payload.get("stats", {})
        return {
            "status": "ok",
            "source": "cloud",
            "product_count": int(stats.get("product_count") or len(items)),
            "warning_count": int(stats.get("warning_count") or 0),
            "inventory_value": float(stats.get("inventory_value") or 0),
            "items": items[:12],
        }
    except Exception as exc:
        cloud_error = str(exc)

    db_path = ROOT / "inventory-board" / "data" / "inventory.sqlite3"
    if not db_path.exists():
        return {"status": "missing", "source": "none", "error": cloud_error, "product_count": 0, "warning_count": 0, "inventory_value": 0, "items": []}
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT sku, name, spec, unit, warning_threshold, unit_cost,
                   COALESCE((SELECT SUM(signed_quantity) FROM movements WHERE movements.sku = products.sku), 0) AS balance
            FROM products
            ORDER BY name
            """
        ).fetchall()
    items = []
    warning_count = 0
    inventory_value = 0.0
    for row in rows:
        balance = float(row["balance"] or 0)
        threshold = float(row["warning_threshold"] or 0)
        unit_cost = float(row["unit_cost"] or 0)
        if balance <= threshold:
            warning_count += 1
        inventory_value += balance * unit_cost
        items.append(
            {
                "sku": row["sku"],
                "name": row["name"],
                "spec": row["spec"],
                "unit": row["unit"],
                "balance": balance,
                "warning_threshold": threshold,
                "inventory_value": balance * unit_cost,
            }
        )
    return {
        "status": "ok",
        "source": "local_fallback",
        "error": cloud_error,
        "product_count": len(items),
        "warning_count": warning_count,
        "inventory_value": inventory_value,
        "items": items[:12],
    }


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value[:19], fmt)
        except ValueError:
            continue
    return None


def read_cloud_realtime_history() -> list[dict]:
    try:
        with urlopen(CLOUD_REALTIME_HISTORY_URL, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if isinstance(payload, dict):
            payload = payload.get("snapshots", [])
        return payload if isinstance(payload, list) else []
    except Exception:
        return []


def realtime_snapshot(realtime: dict) -> dict | None:
    generated_at = realtime.get("generated_at")
    if not generated_at:
        return None
    return {
        "generated_at": generated_at,
        "status": realtime.get("status"),
        "summary": realtime.get("summary") or {},
        "stores": realtime.get("stores") or [],
    }


def merge_realtime_history(realtime: dict) -> list[dict]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    snapshots = []
    local_payload = read_json(REALTIME_HISTORY_PATH, {"snapshots": []})
    if isinstance(local_payload, dict):
        snapshots.extend(local_payload.get("snapshots") or [])
    elif isinstance(local_payload, list):
        snapshots.extend(local_payload)
    snapshots.extend(read_cloud_realtime_history())
    current = realtime_snapshot(realtime)
    if current:
        snapshots.append(current)

    by_time: dict[str, dict] = {}
    cutoff = datetime.now() - timedelta(days=10)
    for item in snapshots:
        if not isinstance(item, dict):
            continue
        generated_at = str(item.get("generated_at") or "")
        parsed = parse_time(generated_at)
        if not generated_at or (parsed and parsed < cutoff):
            continue
        by_time[generated_at] = item

    merged = sorted(by_time.values(), key=lambda item: item.get("generated_at", ""))
    REALTIME_HISTORY_PATH.write_text(
        json.dumps({"snapshots": merged}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    REALTIME_HISTORY_PATH.chmod(0o644)
    return merged


def pct_change(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return (current - previous) / previous


def build_realtime_comparison(realtime: dict, history: list[dict]) -> dict:
    current_time = parse_time(realtime.get("generated_at"))
    if not current_time:
        return {"status": "missing", "message": "实时数据暂无生成时间"}
    target_time = current_time - timedelta(days=1)
    candidates = []
    for item in history:
        item_time = parse_time(item.get("generated_at"))
        if not item_time or item.get("generated_at") == realtime.get("generated_at"):
            continue
        delta = abs((item_time - target_time).total_seconds())
        if delta <= 30 * 60:
            candidates.append((delta, item_time, item))
    if not candidates:
        return {
            "status": "pending",
            "message": "昨日同时段暂无历史数据，明天开始生成",
            "target_time": target_time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    _, previous_time, previous = sorted(candidates, key=lambda item: item[0])[0]
    current_summary = realtime.get("summary") or {}
    previous_summary = previous.get("summary") or {}
    previous_stores = {item.get("store"): item for item in previous.get("stores") or []}
    stores = []
    for current_store in realtime.get("stores") or []:
        store_name = current_store.get("store")
        previous_store = previous_stores.get(store_name) or {}
        current_orders = float(current_store.get("orders") or 0)
        previous_orders = float(previous_store.get("orders") or 0)
        current_income = float(current_store.get("income") or 0)
        previous_income = float(previous_store.get("income") or 0)
        stores.append(
            {
                "store": store_name,
                "orders": {
                    "current": current_orders,
                    "previous": previous_orders,
                    "delta": current_orders - previous_orders,
                    "change": pct_change(current_orders, previous_orders),
                },
                "income": {
                    "current": current_income,
                    "previous": previous_income,
                    "delta": current_income - previous_income,
                    "change": pct_change(current_income, previous_income),
                },
            }
        )

    return {
        "status": "ready",
        "message": f"已对比昨日同时段 {previous_time.strftime('%H:%M')}",
        "target_time": target_time.strftime("%Y-%m-%d %H:%M:%S"),
        "matched_time": previous_time.strftime("%Y-%m-%d %H:%M:%S"),
        "summary": {
            "orders": {
                "current": float(current_summary.get("total_orders") or 0),
                "previous": float(previous_summary.get("total_orders") or 0),
                "delta": float(current_summary.get("total_orders") or 0) - float(previous_summary.get("total_orders") or 0),
                "change": pct_change(float(current_summary.get("total_orders") or 0), float(previous_summary.get("total_orders") or 0)),
            },
            "income": {
                "current": float(current_summary.get("total_income") or 0),
                "previous": float(previous_summary.get("total_income") or 0),
                "delta": float(current_summary.get("total_income") or 0) - float(previous_summary.get("total_income") or 0),
                "change": pct_change(float(current_summary.get("total_income") or 0), float(previous_summary.get("total_income") or 0)),
            },
        },
        "stores": stores,
    }


def task_by_id(task_health: dict) -> dict[str, dict]:
    return {item.get("id"): item for item in task_health.get("tasks", []) if isinstance(item, dict)}


def advice_level(task: dict) -> str:
    if task.get("status") == "danger":
        return "需人工处理"
    if task.get("status") == "warn":
        return "建议"
    return "提醒"


def build_ai_advice(daily: dict, balances: dict, inventory: dict, realtime_comparison: dict, task_health: dict) -> dict:
    rows: list[dict] = []
    tasks = task_by_id(task_health)

    for task_id in ("ops.daily_report", "ops.review_dashboard", "growth.promo_budget"):
        task = tasks.get(task_id) or {}
        if task.get("status") in {"danger", "warn"}:
            rows.append(
                {
                    "level": advice_level(task),
                    "center": task.get("center", ""),
                    "title": task.get("name", task_id),
                    "reason": task.get("reason") or task.get("next_step") or "任务需要关注。",
                    "action": task.get("human_action") or task.get("next_step") or "先查看任务健康报告和日志，再决定是否人工处理。",
                    "source": task_id,
                }
            )

    balance_summary = balances.get("summary") or {}
    warning_count = int(balance_summary.get("warning_count") or 0)
    if warning_count:
        rows.append(
            {
                "level": "需人工处理",
                "center": "商业化推广中心",
                "title": "推广余额不足",
                "reason": f"余额巡检发现 {warning_count} 条低余额。",
                "action": "先充值低余额门店，再执行预算或出价自动化。",
                "source": "growth.promo_balance",
            }
        )

    inventory_warning_count = int(inventory.get("warning_count") or 0)
    if inventory_warning_count:
        rows.append(
            {
                "level": "建议",
                "center": "货流中心",
                "title": "库存预警",
                "reason": f"库存服务发现 {inventory_warning_count} 项低库存。",
                "action": "先核对实物库存，再把缺货商品进入补货建议。",
                "source": "flow.inventory",
            }
        )

    trend = "待积累"
    summary = "AI建议会优先处理自动化异常，再结合实时单量、评价、余额和库存解释经营波动。"
    comparison = realtime_comparison.get("summary") or {}
    order_compare = comparison.get("orders") or {}
    if realtime_comparison.get("status") == "ready" and order_compare:
        delta = float(order_compare.get("delta") or 0)
        trend = f"{'上涨' if delta >= 0 else '下跌'} {delta:+.0f} 单"
        direction = "上涨" if delta >= 0 else "下跌"
        summary = f"按昨日同时段对比，整体单量{direction} {delta:+.0f} 单；建议优先结合异常任务、评价、余额和库存判断原因。"
        stores = sorted(
            realtime_comparison.get("stores") or [],
            key=lambda item: abs(float(((item.get("orders") or {}).get("delta")) or 0)),
            reverse=True,
        )
        for item in stores[:3]:
            orders = item.get("orders") or {}
            delta_store = float(orders.get("delta") or 0)
            if not delta_store:
                continue
            rows.append(
                {
                    "level": "建议" if delta_store < 0 else "提醒",
                    "center": "运营数据中心",
                    "title": f"{item.get('store') or '未命名门店'}单量{'下跌' if delta_store < 0 else '上涨'}",
                    "reason": f"较昨日同时段 {delta_store:+.0f} 单。",
                    "action": "下跌时检查曝光、差评、库存和推广余额；上涨时复盘高峰品类和推广设置。",
                    "source": "ops.realtime_order_income",
                }
            )

    review = daily.get("review_summary") or {}
    negative_count = int((review.get("summary") or {}).get("negative_count") or review.get("negative_count") or 0)
    if negative_count:
        rows.append(
            {
                "level": "建议",
                "center": "运营数据中心",
                "title": "差评需要处理",
                "reason": f"评价汇总发现 {negative_count} 条疑似问题评价。",
                "action": "优先处理差评门店，回复后再观察单量和复购。",
                "source": "ops.review_dashboard",
            }
        )

    level_order = {"需人工处理": 0, "建议": 1, "提醒": 2}
    rows = sorted(rows, key=lambda item: level_order.get(item["level"], 3))[:8]
    if not rows:
        rows.append(
            {
                "level": "提醒",
                "center": "运营数据中心",
                "title": "等待更多历史数据",
                "reason": "当前没有需要优先处理的自动化异常。",
                "action": "继续积累实时同环比、评价和推广数据，用于生成更具体的门店建议。",
                "source": "system",
            }
        )

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "trend": trend,
        "summary": summary,
        "rows": rows,
    }


def main() -> None:
    daily = read_json(ROOT / "business-report-dashboard" / "data" / "latest.json", {})
    balances = read_json(ROOT / "store-inspection" / "latest.json", {})
    budget = read_json(ROOT / "outputs" / "promo_budget_preview" / "latest.json", {})
    realtime = read_json(ROOT / "outputs" / "realtime_order_income" / "latest.json", {})
    inventory = inventory_snapshot()
    realtime_history = merge_realtime_history(realtime)
    realtime_comparison = build_realtime_comparison(realtime, realtime_history)
    task_health = build_task_health(runtime={"inventory": inventory})
    write_task_health(task_health)
    ai_advice = build_ai_advice(daily, balances, inventory, realtime_comparison, task_health)
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "realtime": realtime,
        "realtime_history": realtime_history,
        "realtime_comparison": realtime_comparison,
        "daily": daily,
        "balances": balances,
        "budget": budget,
        "inventory": inventory,
        "task_health": task_health,
        "ai_advice": ai_advice,
    }
    OUTPUT_PATH.write_text(
        "window.WORKBENCH_DATA = " + json.dumps(payload, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8",
    )
    OUTPUT_PATH.chmod(0o644)
    print(f"运营总看板数据已更新：{OUTPUT_PATH}")


if __name__ == "__main__":
    main()
