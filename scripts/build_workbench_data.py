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
MORNING_COLLECTION_STATUS_PATH = ROOT / "outputs" / "morning_collection_status" / "latest.json"
REALTIME_COLLECTION_STATUS_PATH = ROOT / "outputs" / "realtime_order_income_status" / "latest.json"
REVIEW_ACTION_STATUS_PATH = ROOT / "outputs" / "review_action_status" / "latest.json"
DAILY_FOCUS_STATUS_PATH = ROOT / "outputs" / "daily_focus_status" / "latest.json"
ORDER_SUGGESTIONS_PATH = ROOT / "outputs" / "inventory_order_suggestions" / "latest.json"
ORDER_LISTS_PATH = ROOT / "outputs" / "inventory_order_lists" / "latest.json"
ORDER_EXECUTION_PREVIEW_PATH = ROOT / "outputs" / "inventory_order_execution_preview" / "latest.json"
ANDROID_EXECUTION_PLAN_PATH = ROOT / "outputs" / "inventory_android_execution_plan" / "latest.json"
ANDROID_CONFIG_HEALTH_PATH = ROOT / "outputs" / "android_execution_config" / "latest.json"
PROMO_BUDGET_RETRY_PATH = ROOT / "outputs" / "promo_budget_retry_plan" / "latest.json"
PROMO_BID_ADVICE_PATH = ROOT / "outputs" / "promo_bid_advice" / "latest.json"
PROMO_BID_APPROVAL_QUEUE_PATH = ROOT / "outputs" / "promo_bid_approval_queue" / "latest.json"
PROMO_BALANCE_STATUS_PATH = ROOT / "outputs" / "promo_balance_status" / "latest.json"
TOOL_WAREHOUSE_STATUS_PATH = ROOT / "outputs" / "tool_warehouse_status" / "latest.json"
FINANCE_CENTER_STATUS_PATH = ROOT / "outputs" / "finance_center_status" / "latest.json"
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


def normalize_store_name(value: str | None) -> str:
    return (
        str(value or "")
        .replace("熊小小牛排饭", "")
        .replace("POKEBEAR", "")
        .replace("（", "")
        .replace("）", "")
        .replace("(", "")
        .replace(")", "")
        .replace("·", "")
        .strip()
    )


def store_key(value: str | None) -> str:
    return normalize_store_name(value).lower().replace(" ", "")


def build_store_signal_maps(daily: dict, balances: dict) -> dict[str, dict[str, list]]:
    signals: dict[str, dict[str, list]] = {}

    def bucket(store: str | None) -> dict[str, list]:
        key = store_key(store)
        if not key:
            key = "unknown"
        return signals.setdefault(key, {"focus": [], "reviews": [], "balances": []})

    for item in daily.get("focus_items") or []:
        bucket(item.get("store"))["focus"].append(item)

    review_stores = (daily.get("review_summary") or {}).get("stores") or {}
    for store, item in review_stores.items():
        if int(item.get("negative_count") or 0) > 0:
            bucket(store)["reviews"].append(item)

    for item in balances.get("items") or []:
        if item.get("status") == "warning":
            bucket(item.get("store_name") or item.get("store"))["balances"].append(item)

    return signals


def store_signals_for(signals: dict[str, dict[str, list]], store: str | None) -> dict[str, list]:
    key = store_key(store)
    if key in signals:
        return signals[key]
    for candidate_key, value in signals.items():
        if key and (key in candidate_key or candidate_key in key):
            return value
    return {"focus": [], "reviews": [], "balances": []}


def explain_store_change(store: str, delta: float, signals: dict[str, list], inventory_warning_count: int) -> tuple[str, str]:
    reasons: list[str] = [f"较昨日同时段 {delta:+.0f} 单"]
    actions: list[str] = []

    focus_items = signals.get("focus") or []
    if focus_items:
        reasons.append("日报异常：" + "；".join(str(item.get("title") or "") for item in focus_items[:2] if item.get("title")))
        actions.append("先核对日报异常门店的平台活动、营业状态和客单价变化")

    reviews = signals.get("reviews") or []
    review_negative = sum(int(item.get("negative_count") or 0) for item in reviews)
    if review_negative:
        reasons.append(f"疑似问题评价 {review_negative} 条")
        actions.append("优先处理差评和关键词问题")

    low_balances = signals.get("balances") or []
    if low_balances:
        lowest = min(low_balances, key=lambda item: float(item.get("balance") or 0))
        reasons.append(f"推广余额偏低：{lowest.get('platform', '')} {float(lowest.get('balance') or 0):.0f} 元")
        actions.append("先充值低余额平台，再恢复推广动作")

    if inventory_warning_count:
        reasons.append(f"库存有 {inventory_warning_count} 项预警")
        actions.append("同步核对是否有畅销品缺货")

    if not actions:
        actions.append("先检查曝光、进店、差评、库存和推广余额，再决定是否调整预算或活动")
    if delta > 0:
        actions = ["复盘上涨时段的品类、活动和推广设置，沉淀可复制动作", *actions[1:]]

    return "；".join(part for part in reasons if part), "；".join(actions[:3])


def build_ai_advice(daily: dict, balances: dict, inventory: dict, order_suggestions: dict, order_lists: dict, order_execution_preview: dict, android_execution_plan: dict, android_config: dict, promo_retry: dict, promo_bid_advice: dict, promo_bid_approval_queue: dict, promo_balance_status: dict, review_actions: dict, daily_focus: dict, tool_warehouse: dict, finance_center: dict, morning_collection: dict, realtime_collection: dict, realtime_comparison: dict, task_health: dict) -> dict:
    rows: list[dict] = []
    tasks = task_by_id(task_health)
    store_signals = build_store_signal_maps(daily, balances)

    for task_id in ("ops.daily_report", "ops.review_dashboard", "growth.promo_budget"):
        task = tasks.get(task_id) or {}
        if task.get("status") in {"danger", "warn"}:
            title = task.get("name", task_id)
            reason = task.get("reason") or task.get("next_step") or "任务需要关注。"
            action = task.get("human_action") or task.get("next_step") or "先查看任务健康报告和日志，再决定是否人工处理。"
            if task_id == "ops.review_dashboard" and review_actions.get("status") == "waiting_reply":
                first_action = (review_actions.get("items") or [{}])[0]
                title = "差评需要处理"
                reason = review_actions.get("message") or reason
                action = first_action.get("reply_suggestion") or action
            rows.append(
                {
                    "level": advice_level(task),
                    "center": task.get("center", ""),
                    "title": title,
                    "reason": reason,
                    "action": action,
                    "source": task_id,
                }
            )

    morning_failed = morning_collection.get("failed_steps") or []
    if morning_failed:
        recovery_actions = morning_collection.get("recovery_actions") or []
        rows.append(
            {
                "level": "需人工处理",
                "center": "运营数据中心",
                "title": "上午运营采集子步骤失败",
                "reason": "；".join(f"{item.get('name')}：{item.get('failure_type') or item.get('message')}" for item in morning_failed[:2]),
                "action": "；".join(item.get("human_action", "") for item in recovery_actions[:2] if item.get("human_action")) or "先处理失败子步骤对应的平台登录、页面结构或脚本日志，再重跑一键采集。",
                "source": "ops.morning_collection",
            }
        )

    realtime_failures = realtime_collection.get("platform_failures") or []
    if realtime_failures:
        summary_realtime = realtime_collection.get("summary") or {}
        recovery_actions = []
        for item in realtime_failures[:2]:
            store_actions = item.get("store_recovery_actions") or []
            if store_actions:
                recovery_actions.append("；".join(action.get("human_action", "") for action in store_actions[:2] if action.get("human_action")))
            else:
                recovery_actions.append(item.get("recovery_summary") or item.get("human_action", ""))
        rows.append(
            {
                "level": "需人工处理" if realtime_collection.get("status") == "missing_latest" else "建议",
                "center": "运营数据中心",
                "title": "实时采集平台失败",
                "reason": f"最近失败记录显示 {summary_realtime.get('platform_failure_count', len(realtime_failures))} 个平台失败，缺失 {summary_realtime.get('failed_platform_store_count', 0)} 个平台门店。",
                "action": "；".join(item for item in recovery_actions if item) or realtime_collection.get("human_action") or "先恢复平台登录、Chrome/CDP 状态或门店映射，再重跑实时采集。",
                "source": "ops.realtime_order_income",
            }
        )

    if daily_focus.get("status") == "waiting_review":
        for item in (daily_focus.get("items") or [])[:2]:
            issue_titles = "；".join(issue.get("title", "") for issue in (item.get("issues") or [])[:2] if issue.get("title"))
            rows.append(
                {
                    "level": "建议",
                    "center": "运营数据中心",
                    "title": f"{item.get('store')}日报异常",
                    "reason": issue_titles or daily_focus.get("message") or "日报异常需要处理。",
                    "action": item.get("action") or "先打开日报看板查看异常详情。",
                    "source": "ops.daily_report",
                    "store": item.get("store", ""),
                }
            )

    balance_status_summary = promo_balance_status.get("summary") or {}
    platform_failure_count = int(balance_status_summary.get("platform_failure_count") or 0)
    if platform_failure_count:
        platform_failures = [
            item
            for item in promo_balance_status.get("platforms") or []
            if item.get("status") == "failed"
        ]
        recovery_actions = []
        for item in platform_failures[:2]:
            recovery = item.get("recovery") or {}
            evidence = item.get("evidence") or []
            evidence_text = f"证据：{evidence[0].get('path')}" if evidence else ""
            recovery_text = (
                recovery.get("summary")
                or item.get("human_action")
                or f"{item.get('platform', '平台')}：先恢复登录、权限或页面状态。"
            )
            recovery_actions.append("；".join(part for part in (recovery_text, evidence_text) if part))
        rows.append(
            {
                "level": "需人工处理",
                "center": "商业化推广中心",
                "title": "推广余额巡检失败",
                "reason": promo_balance_status.get("message") or f"{platform_failure_count} 个平台巡检失败。",
                "action": "；".join(recovery_actions) or promo_balance_status.get("human_action") or "先恢复平台权限、登录或页面状态，再重跑推广余额巡检。",
                "source": "growth.promo_balance",
            }
        )

    balance_summary = balances.get("summary") or {}
    warning_count = int(balance_status_summary.get("low_balance_count") or balance_summary.get("warning_count") or 0)
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

    suggestion_summary = order_suggestions.get("summary") or {}
    suggestion_count = int(suggestion_summary.get("suggestion_count") or 0)
    if order_suggestions.get("status") == "ready" and suggestion_count:
        channel_count = int(suggestion_summary.get("channel_count") or 0)
        rows.append(
            {
                "level": "需人工处理",
                "center": "货流中心",
                "title": "订货建议待确认",
                "reason": f"库存预警已生成 {suggestion_count} 项订货建议，{channel_count} 个供应渠道，预估 {float(suggestion_summary.get('estimated_cost') or 0):.0f} 元。",
                "action": "先人工确认品项、数量和供应渠道；确认前不自动下单、不付款。",
                "source": "flow.auto_ordering",
            }
        )

    order_list_summary = order_lists.get("summary") or {}
    if order_lists.get("status") == "ready" and int(order_list_summary.get("order_list_count") or 0):
        rows.append(
            {
                "level": "需人工处理",
                "center": "货流中心",
                "title": "渠道下单清单待执行",
                "reason": f"已生成 {order_list_summary.get('order_list_count')} 个供应渠道下单清单，预估 {float(order_list_summary.get('estimated_cost') or 0):.0f} 元。",
                "action": "按渠道下单前再次核对数量和付款金额，付款仍需人工确认。",
                "source": "flow.auto_ordering",
            }
        )

    execution_summary = order_execution_preview.get("summary") or {}
    if order_execution_preview.get("status") == "waiting_payment_confirmation":
        rows.append(
            {
                "level": "需人工处理",
                "center": "货流中心",
                "title": "订货付款待确认",
                "reason": f"下单执行预览已生成，{execution_summary.get('channel_count', 0)} 个供应渠道，预估 {float(execution_summary.get('estimated_cost') or 0):.0f} 元。",
                "action": "付款前核对供应渠道、商品、数量和平台最终金额；未确认前不要远控安卓提交订单。",
                "source": "flow.auto_ordering",
            }
        )

    android_summary = android_execution_plan.get("summary") or {}
    if android_execution_plan.get("status") == "ready":
        rows.append(
            {
                "level": "需人工处理",
                "center": "货流中心",
                "title": "远控安卓执行计划待接管",
                "reason": f"只读执行计划已生成，{android_summary.get('channel_count', 0)} 个供应渠道，预估 {float(android_summary.get('estimated_cost') or 0):.0f} 元。",
                "action": "人工操作员接管远控安卓；系统仍禁止自动提交订单和自动付款。",
                "source": "flow.auto_ordering",
            }
        )

    android_config_summary = android_config.get("summary") or {}
    if android_config.get("status") == "missing_config":
        rows.append(
            {
                "level": "需人工处理",
                "center": "货流中心",
                "title": "远控安卓配置待补齐",
                "reason": f"真实设备连接配置缺少 {android_config_summary.get('missing_count', 0)} 项。",
                "action": "按 config/android_execution.example.json 创建 config/android_execution.json，填写设备、操作员、付款确认和供应渠道信息。",
                "source": "flow.auto_ordering",
            }
        )

    promo_retry_summary = promo_retry.get("summary") or {}
    manual_budget_count = int(promo_retry_summary.get("manual_count") or 0)
    if promo_retry.get("status") == "ready" and manual_budget_count:
        affected_budget_count = int(promo_retry_summary.get("affected_by_latest_run_count") or 0)
        affected_text = f"最近执行影响 {affected_budget_count} 项；" if affected_budget_count else ""
        rows.append(
            {
                "level": "建议",
                "center": "商业化推广中心",
                "title": "推广预算重试需分级",
                "reason": f"{affected_text}门店级重试策略中 {promo_retry_summary.get('safe_retry_count', 0)} 项可安全重试，{manual_budget_count} 项需人工处理。",
                "action": "只允许超时或普通执行失败重试；登录、权限、页面结构、预算安全和门店映射问题必须人工处理。",
                "source": "growth.promo_budget",
            }
        )

    promo_bid_queue_summary = promo_bid_approval_queue.get("summary") or {}
    promo_bid_summary = promo_bid_queue_summary or promo_bid_advice.get("summary") or {}
    bid_approval_count = int(promo_bid_summary.get("queue_count") or promo_bid_summary.get("approval_required_count") or 0)
    if promo_bid_approval_queue.get("status") == "waiting_approval" and bid_approval_count:
        rows.append(
            {
                "level": "建议",
                "center": "商业化推广中心",
                "title": "推广出价审批队列待确认",
                "reason": f"审批队列中 {bid_approval_count} 项需要确认，风险或不可执行 {promo_bid_summary.get('risk_count', 0)} 项。",
                "action": promo_bid_approval_queue.get("human_action") or "先核对预算消耗、预期消耗和门店状态；确认前不自动提交出价。",
                "source": "growth.promo_bid",
            }
        )
    elif promo_bid_advice.get("status") in {"ready", "partial", "stale"} and bid_approval_count:
        rows.append(
            {
                "level": "建议",
                "center": "商业化推广中心",
                "title": "推广出价建议待审批",
                "reason": f"只读出价建议中 {bid_approval_count} 项需要确认，风险或不可执行 {promo_bid_summary.get('risk_count', 0)} 项。",
                "action": "先生成审批队列，再核对预算消耗、预期消耗和门店状态；确认前不自动提交出价。",
                "source": "growth.promo_bid",
            }
        )

    contract = tool_warehouse.get("franchise_contract") or {}
    if contract.get("status") == "waiting_template":
        rows.append(
            {
                "level": "提醒",
                "center": "小工具仓库",
                "title": "加盟合同模板待提供",
                "reason": contract.get("message") or "合同生成器等待模板和字段。",
                "action": "提供现用加盟合同模板，并确认加盟费、保证金、期限和授权范围等字段。",
                "source": "tools.franchise_contract",
            }
        )

    if finance_center.get("status") == "waiting_samples":
        missing = "、".join(finance_center.get("missing") or [])
        rows.append(
            {
                "level": "提醒",
                "center": "财务中心",
                "title": "财务账单样例待提供",
                "reason": f"财务字段字典已建立，当前缺少：{missing or '账单样例'}。",
                "action": "提供银行账单和美团/饿了么平台账单样例后，再进入字段映射和利润表生成。",
                "source": "finance.bill_analysis",
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
            store_name = item.get("store") or "未命名门店"
            reason, action = explain_store_change(store_name, delta_store, store_signals_for(store_signals, store_name), inventory_warning_count)
            rows.append(
                {
                    "level": "建议" if delta_store < 0 else "提醒",
                    "center": "运营数据中心",
                    "title": f"{store_name}单量{'下跌' if delta_store < 0 else '上涨'}",
                    "reason": reason,
                    "action": action,
                    "source": "ops.realtime_order_income",
                    "store": store_name,
                }
            )

    review_action_summary = review_actions.get("summary") or {}
    negative_count = int(review_action_summary.get("negative_count") or 0)
    if negative_count and not any(item.get("source") == "ops.review_dashboard" for item in rows):
        first_action = (review_actions.get("items") or [{}])[0]
        rows.append(
            {
                "level": "建议",
                "center": "运营数据中心",
                "title": "差评需要处理",
                "reason": review_actions.get("message") or f"评价汇总发现 {negative_count} 条疑似问题评价。",
                "action": first_action.get("reply_suggestion") or "优先处理差评门店，回复后再观察单量和复购。",
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
    morning_collection = read_json(MORNING_COLLECTION_STATUS_PATH, {})
    realtime_collection = read_json(REALTIME_COLLECTION_STATUS_PATH, {})
    review_actions = read_json(REVIEW_ACTION_STATUS_PATH, {})
    daily_focus = read_json(DAILY_FOCUS_STATUS_PATH, {})
    promo_retry = read_json(PROMO_BUDGET_RETRY_PATH, {})
    promo_bid_advice = read_json(PROMO_BID_ADVICE_PATH, {})
    promo_bid_approval_queue = read_json(PROMO_BID_APPROVAL_QUEUE_PATH, {})
    promo_balance_status = read_json(PROMO_BALANCE_STATUS_PATH, {})
    tool_warehouse = read_json(TOOL_WAREHOUSE_STATUS_PATH, {})
    finance_center = read_json(FINANCE_CENTER_STATUS_PATH, {})
    order_suggestions = read_json(ORDER_SUGGESTIONS_PATH, {})
    order_lists = read_json(ORDER_LISTS_PATH, {})
    order_execution_preview = read_json(ORDER_EXECUTION_PREVIEW_PATH, {})
    android_execution_plan = read_json(ANDROID_EXECUTION_PLAN_PATH, {})
    android_config = read_json(ANDROID_CONFIG_HEALTH_PATH, {})
    realtime = read_json(ROOT / "outputs" / "realtime_order_income" / "latest.json", {})
    inventory = inventory_snapshot()
    realtime_history = merge_realtime_history(realtime)
    realtime_comparison = build_realtime_comparison(realtime, realtime_history)
    task_health = build_task_health(runtime={"inventory": inventory})
    write_task_health(task_health)
    ai_advice = build_ai_advice(daily, balances, inventory, order_suggestions, order_lists, order_execution_preview, android_execution_plan, android_config, promo_retry, promo_bid_advice, promo_bid_approval_queue, promo_balance_status, review_actions, daily_focus, tool_warehouse, finance_center, morning_collection, realtime_collection, realtime_comparison, task_health)
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "realtime": realtime,
        "realtime_history": realtime_history,
        "realtime_comparison": realtime_comparison,
        "morning_collection": morning_collection,
        "realtime_collection": realtime_collection,
        "daily": daily,
        "daily_focus": daily_focus,
        "review_actions": review_actions,
        "balances": balances,
        "budget": budget,
        "promo_budget_retry": promo_retry,
        "promo_bid_advice": promo_bid_advice,
        "promo_bid_approval_queue": promo_bid_approval_queue,
        "promo_balance_status": promo_balance_status,
        "tool_warehouse": tool_warehouse,
        "finance_center": finance_center,
        "inventory": inventory,
        "order_suggestions": order_suggestions,
        "order_lists": order_lists,
        "order_execution_preview": order_execution_preview,
        "android_execution_plan": android_execution_plan,
        "android_config": android_config,
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
