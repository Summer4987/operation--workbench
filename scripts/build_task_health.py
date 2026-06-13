from __future__ import annotations

import json
import os
import socket
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
TASKS_PATH = ROOT / "config" / "ai_business_center_tasks.json"
OUTPUT_DIR = ROOT / "outputs" / "task_health"
LATEST_PATH = OUTPUT_DIR / "latest.json"
TASK_RUNS_PATH = ROOT / "outputs" / "task_runs" / "latest.json"
MORNING_COLLECTION_STATUS_PATH = ROOT / "outputs" / "morning_collection_status" / "latest.json"
REALTIME_COLLECTION_STATUS_PATH = ROOT / "outputs" / "realtime_order_income_status" / "latest.json"
REVIEW_ACTION_STATUS_PATH = ROOT / "outputs" / "review_action_status" / "latest.json"
DAILY_FOCUS_STATUS_PATH = ROOT / "outputs" / "daily_focus_status" / "latest.json"
INVENTORY_HEALTH_PATH = ROOT / "outputs" / "inventory_health" / "latest.json"
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


STATUS_LABELS = {
    "ok": "正常",
    "warn": "注意",
    "danger": "需处理",
    "planned": "规划中",
    "unknown": "待接入",
}

FAILURE_TYPE_LABELS = {
    "auth_block": "登录/验证码/权限阻塞",
    "outside_allowed_window": "不在允许执行窗口",
    "permission": "系统权限不足",
    "timeout": "执行超时",
    "budget_guardrail": "预算安全校验拦截",
    "page_structure": "平台页面结构变化",
    "store_mapping": "门店映射缺失",
    "manual_browser_setup": "需要先人工打开平台页面",
    "execution_failed": "执行失败",
}


def read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:26] if "." in text else text[:19], fmt)
        except ValueError:
            continue
    return None


def path_mtime(path: Path) -> datetime | None:
    if not path.exists():
        return None
    if path.is_file():
        return datetime.fromtimestamp(path.stat().st_mtime)
    latest: datetime | None = None
    for child in path.rglob("*"):
        if child.is_file():
            mtime = datetime.fromtimestamp(child.stat().st_mtime)
            if latest is None or mtime > latest:
                latest = mtime
    return latest or datetime.fromtimestamp(path.stat().st_mtime)


def relative_path(value: str) -> Path | None:
    text = str(value or "").strip()
    if not text or text.startswith("云端 ") or text.startswith("浏览器") or text.startswith("http"):
        return None
    if " " in text and not text.startswith("~/"):
        return None
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path


def newest_output(task: dict[str, Any]) -> tuple[datetime | None, str]:
    newest: datetime | None = None
    newest_label = ""
    for output in task.get("outputs", []):
        path = relative_path(output)
        if path is None:
            continue
        mtime = path_mtime(path)
        if mtime and (newest is None or mtime > newest):
            newest = mtime
            newest_label = str(output)
    return newest, newest_label


def age_text(value: datetime | None, now: datetime) -> str:
    if not value:
        return "没有找到产物"
    delta = now - value
    if delta < timedelta(minutes=2):
        return "刚刚更新"
    if delta < timedelta(hours=1):
        return f"{int(delta.total_seconds() // 60)} 分钟前"
    if delta < timedelta(days=1):
        return f"{int(delta.total_seconds() // 3600)} 小时前"
    return f"{delta.days} 天前"


def within_today(value: datetime | None, now: datetime) -> bool:
    return bool(value and value.date() == now.date())


def active_realtime_window(now: datetime) -> bool:
    return 10 <= now.hour < 20


def runtime_environment() -> dict[str, str]:
    hostname = socket.gethostname()
    normalized = hostname.lower()
    role = os.environ.get("AI_BUSINESS_CENTER_ENV", "").strip().lower()
    if not role:
        if "macbook" in normalized:
            role = "development"
        elif "mini" in normalized:
            role = "production"
        else:
            role = "development"
    return {
        "role": role,
        "hostname": hostname,
        "label": "Mac mini 生产环境" if role == "production" else "MacBook 开发环境",
    }


def base_task_state(task: dict[str, Any], now: datetime) -> dict[str, Any]:
    newest, evidence = newest_output(task)
    status = "planned" if task.get("status") == "planned" else "unknown"
    reason = task.get("next_integration_step") or "等待接入统一健康监控。"
    if task.get("status") != "planned" and newest:
        status = "ok" if within_today(newest, now) else "warn"
        reason = f"最近产物：{age_text(newest, now)}。"
    elif task.get("status") != "planned":
        status = "warn"
        reason = "没有找到可验证产物。"
    return {
        "id": task["id"],
        "name": task["name"],
        "center": task["center"],
        "module": task["module"],
        "registry_status": task["status"],
        "risk": task["risk"],
        "schedule": task["schedule"],
        "status": status,
        "status_text": STATUS_LABELS[status],
        "reason": reason,
        "last_seen_at": newest.strftime("%Y-%m-%d %H:%M:%S") if newest else "",
        "evidence": evidence,
        "human_action": "",
        "next_step": task.get("next_integration_step", ""),
    }


def classify_from_json_status(value: str | None) -> str:
    if value in {"ok", "ready", "success", "normal"}:
        return "ok"
    if value in {"partial", "stale", "warning"}:
        return "warn"
    if value in {"failed", "error"}:
        return "danger"
    return "unknown"


def apply_run_state(row: dict[str, Any], run_state: dict[str, Any], now: datetime) -> dict[str, Any]:
    task_run = (run_state.get("tasks") or {}).get(row["id"])
    if not isinstance(task_run, dict):
        return row
    updated_at = parse_time(task_run.get("updated_at"))
    row_last_seen = parse_time(row.get("last_seen_at"))
    if updated_at and row_last_seen and updated_at < row_last_seen:
        return row

    run_status = task_run.get("status")
    if run_status == "success":
        row["status"] = "ok"
        row["reason"] = task_run.get("message") or "最近一次运行成功。"
    elif run_status == "running":
        row["status"] = "warn"
        row["reason"] = task_run.get("message") or "任务正在运行。"
    elif run_status == "failed":
        row["status"] = "danger"
        failure_type = task_run.get("failure_type")
        row["reason"] = task_run.get("message") or "最近一次运行失败。"
        if failure_type:
            row["failure_type"] = failure_type
            row["failure_type_text"] = FAILURE_TYPE_LABELS.get(failure_type, failure_type)
            row["reason"] = f"{row['reason']}（{row['failure_type_text']}）"
    elif run_status == "skipped":
        row["status"] = "warn"
        row["reason"] = task_run.get("message") or "最近一次运行跳过。"

    row["last_run_at"] = task_run.get("updated_at", "")
    row["last_run_step"] = task_run.get("step", "")
    row["last_run_status"] = run_status or ""
    if task_run.get("log_path"):
        row["evidence"] = task_run["log_path"]
    if updated_at:
        row["last_seen_at"] = updated_at.strftime("%Y-%m-%d %H:%M:%S")
    if row["id"] == "ops.review_dashboard":
        extra = task_run.get("extra") or {}
        platform_parts = []
        for key, label in (("eleme", "饿了么"), ("meituan", "美团")):
            status = extra.get(f"{key}_status")
            message = extra.get(f"{key}_message")
            if status and message:
                platform_parts.append(f"{label}：{message}")
        if platform_parts:
            row["reason"] = f"{row['reason']}｜" + "；".join(platform_parts)
    if row["id"] == "ops.daily_report":
        extra = task_run.get("extra") or {}
        platform_parts = []
        for key, label in (("eleme", "饿了么"), ("meituan", "美团")):
            for phase, phase_label in (("submit", "提交"), ("download", "下载")):
                message = extra.get(f"{key}_{phase}_message")
                if message:
                    platform_parts.append(f"{label}{phase_label}：{message}")
        if platform_parts:
            row["reason"] = f"{row['reason']}｜" + "；".join(platform_parts)
    if row["id"] == "growth.promo_budget":
        extra = task_run.get("extra") or {}
        platform_parts = []
        recoveries = []
        for key, label in (("eleme", "饿了么"), ("meituan", "美团")):
            message = extra.get(f"{key}_message")
            recovery = extra.get(f"{key}_recovery")
            if message:
                platform_parts.append(f"{label}：{message}")
            if recovery and extra.get(f"{key}_status") == "failed":
                recoveries.append(f"{label}：{recovery}")
        if platform_parts:
            row["reason"] = f"{row['reason']}｜" + "；".join(platform_parts)
        if recoveries:
            row["human_action"] = "；".join(recoveries)
    if row["id"] == "growth.promo_bid":
        queue_payload = read_json(PROMO_BID_APPROVAL_QUEUE_PATH, {})
        queue_summary = queue_payload.get("summary") or {}
        if queue_payload.get("status") == "waiting_approval":
            row["status"] = "warn"
            row["reason"] = (
                f"出价审批队列待确认，"
                f"{int(queue_summary.get('queue_count') or queue_summary.get('approval_required_count') or 0)} 项，"
                f"风险 {int(queue_summary.get('risk_count') or 0)} 项，"
                f"旧预览 {int(queue_summary.get('stale_preview_count') or 0)} 个。"
            )
            row["human_action"] = queue_payload.get("human_action") or "逐项确认出价建议；确认前不自动提交到平台。"
            row["evidence"] = "outputs/promo_bid_approval_queue/latest.json"
            return row
        extra = task_run.get("extra") or {}
        stale_count = int(extra.get("stale_preview_count") or 0)
        approval_count = int(extra.get("approval_required_count") or 0)
        if stale_count:
            row["status"] = "warn"
            row["reason"] = f"出价建议已生成，但 {stale_count} 个输入预览偏旧。"
        elif approval_count:
            row["reason"] = f"出价只读建议已生成，{approval_count} 项需审批。"
            row["human_action"] = "逐项确认出价建议；确认前不自动提交到平台。"
    if row["id"] == "ops.morning_collection":
        payload = read_json(MORNING_COLLECTION_STATUS_PATH, {})
        summary = payload.get("summary") or {}
        if payload.get("status") in {"failed", "partial", "running", "success"}:
            step_text = (
                f"子步骤：完成 {summary.get('completed_count', 0)}，"
                f"失败 {summary.get('failed_count', 0)}，运行中 {summary.get('running_count', 0)}"
            )
            row["reason"] = f"{row['reason']}｜{step_text}"
            row["evidence"] = "outputs/morning_collection_status/latest.json"
            recovery_actions = payload.get("recovery_actions") or []
            failed_steps = payload.get("failed_steps") or []
            if recovery_actions:
                row["human_action"] = "；".join(
                    f"{item.get('step')}：{item.get('human_action') or item.get('message') or '查看日志'}"
                    for item in recovery_actions[:2]
                )
            elif failed_steps and not row.get("human_action"):
                row["human_action"] = "；".join(
                    f"{item.get('name')}：{item.get('message') or item.get('failure_type') or '查看日志'}"
                    for item in failed_steps[:2]
                )
    return row


def inventory_probe() -> dict[str, Any]:
    health = read_json(INVENTORY_HEALTH_PATH, {})
    if health:
        stats = health.get("stats") or {}
        return {
            "status": health.get("status"),
            "generated_at": health.get("generated_at", ""),
            "warning_count": int(stats.get("warning_count") or 0),
            "product_count": int(stats.get("product_count") or 0),
            "message": health.get("message", ""),
            "evidence": "outputs/inventory_health/latest.json",
        }
    try:
        with urlopen(CLOUD_INVENTORY_URL, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
        stats = payload.get("stats") or {}
        return {
            "status": "ok",
            "warning_count": int(stats.get("warning_count") or 0),
            "product_count": int(stats.get("product_count") or 0),
            "evidence": "云端 /api/summary",
        }
    except Exception as exc:
        return {"status": "missing", "error": str(exc)}


def enrich_known_task(row: dict[str, Any], now: datetime, runtime: dict[str, Any]) -> dict[str, Any]:
    task_id = row["id"]
    if task_id == "ops.morning_collection":
        payload = read_json(MORNING_COLLECTION_STATUS_PATH, {})
        generated_at = parse_time(payload.get("generated_at"))
        summary = payload.get("summary") or {}
        repair_guides = payload.get("repair_guides") or []
        repair_suffix = f"，修复向导 {len(repair_guides)} 个" if repair_guides else ""
        if payload.get("status") == "missing_run":
            row.update(status="warn", reason=payload.get("message") or "上午运营一键采集尚未写入运行记录。")
        elif payload.get("status") == "failed":
            row.update(status="danger", reason=f"{payload.get('message')} 完成 {summary.get('completed_count', 0)} 个，失败 {summary.get('failed_count', 0)} 个{repair_suffix}。")
        elif payload.get("status") in {"success", "partial", "running"}:
            status = "ok" if payload.get("status") == "success" else "warn"
            row.update(status=status, reason=f"{payload.get('message')} 完成 {summary.get('completed_count', 0)} 个，失败 {summary.get('failed_count', 0)} 个{repair_suffix}。")
        if payload.get("human_action"):
            row["human_action"] = payload.get("human_action", "")
        if repair_guides:
            first_guide = repair_guides[0]
            first_step = (first_guide.get("checklist") or [""])[0]
            row["repair_guide"] = f"{first_guide.get('title', '修复向导')}：{first_step}"
        if payload:
            row["evidence"] = "outputs/morning_collection_status/latest.json"
        if generated_at:
            row["last_seen_at"] = generated_at.strftime("%Y-%m-%d %H:%M:%S")

    elif task_id == "ops.realtime_order_income":
        payload = read_json(ROOT / "outputs" / "realtime_order_income" / "latest.json", {})
        status_payload = read_json(REALTIME_COLLECTION_STATUS_PATH, {})
        generated_at = parse_time(payload.get("generated_at"))
        source_status = classify_from_json_status(payload.get("status"))
        summary = payload.get("summary") or {}
        missing = int(summary.get("missing_count") or 0)
        status_summary = status_payload.get("summary") or {}
        platform_failures = status_payload.get("platform_failures") or []
        repair_guides = status_payload.get("repair_guides") or []
        platform_failure_count = int(status_summary.get("platform_failure_count") or 0)
        failed_platform_store_count = int(status_summary.get("failed_platform_store_count") or 0)
        realtime_failure_type = (platform_failures[0] or {}).get("failure_type") if platform_failures else status_payload.get("failure_type", "")
        store_recovery_actions = [
            action.get("human_action", "")
            for item in platform_failures
            for action in (item.get("store_recovery_actions") or [])
            if action.get("human_action")
        ]
        realtime_human_action = "；".join(store_recovery_actions[:3]) or status_payload.get("human_action", "")
        if repair_guides:
            first_guide = repair_guides[0]
            first_step = (first_guide.get("checklist") or [""])[0]
            row["repair_guide"] = f"{first_guide.get('title', '修复向导')}：{first_step}"
        if status_payload.get("status") == "failed_after_success":
            detail = f"，{platform_failure_count} 个平台失败，缺失 {failed_platform_store_count} 个平台门店" if platform_failure_count else ""
            detail += f"，修复向导 {len(repair_guides)} 个" if repair_guides else ""
            row.update(status="warn", reason=(status_payload.get("message") or "最近一次实时采集失败，但保留上一份成功数据。") + detail + "。")
            row["failure_type"] = realtime_failure_type
            row["human_action"] = realtime_human_action
        elif status_payload.get("status") == "stale":
            detail = f" 最近失败记录显示 {platform_failure_count} 个平台失败，缺失 {failed_platform_store_count} 个平台门店。" if platform_failure_count else ""
            detail += f" 修复向导 {len(repair_guides)} 个。" if repair_guides else ""
            row.update(status="warn", reason=(status_payload.get("message") or "实时采集最近成功时间偏旧。") + detail)
            row["failure_type"] = realtime_failure_type
            row["human_action"] = realtime_human_action
        elif status_payload.get("status") == "missing_latest":
            row.update(status="warn", reason=status_payload.get("message") or "实时采集尚未生成成功数据。")
            row["human_action"] = realtime_human_action
        elif source_status == "danger":
            row.update(status="danger", reason=payload.get("message") or "实时采集失败。")
        elif generated_at and active_realtime_window(now) and now - generated_at > timedelta(minutes=95):
            row.update(status="warn", reason=f"实时采集已超过计划窗口：{age_text(generated_at, now)}。")
        elif missing:
            row.update(status="warn", reason=f"实时采集缺失 {missing} 个平台门店。")
        elif generated_at:
            last_success = status_payload.get("last_success_at") or payload.get("generated_at", "")
            row.update(status="ok", reason=f"实时采集覆盖 {summary.get('platform_store_count') or '-'} 个平台门店，最近成功 {last_success or '-'}。")
        row["last_seen_at"] = generated_at.strftime("%Y-%m-%d %H:%M:%S") if generated_at else row["last_seen_at"]
        row["evidence"] = "outputs/realtime_order_income_status/latest.json" if status_payload else "outputs/realtime_order_income/latest.json"

    elif task_id == "ops.daily_report":
        payload = read_json(ROOT / "business-report-dashboard" / "data" / "latest.json", {})
        focus_status = read_json(DAILY_FOCUS_STATUS_PATH, {})
        generated_at = parse_time(payload.get("generated_at"))
        records = payload.get("records") or []
        source_dates = payload.get("source_dates") or []
        focus_suffix = ""
        if focus_status.get("status") == "waiting_review":
            focus_summary = focus_status.get("summary") or {}
            focus_suffix = f"，异常门店 {focus_summary.get('store_action_count', 0)} 家，高优先级 {focus_summary.get('high_count', 0)} 项"
            row["human_action"] = focus_status.get("human_action", "")
        if not records:
            row.update(status="danger", reason="日报 latest.json 没有可用记录。")
        elif generated_at and not within_today(generated_at, now):
            row.update(status="warn", reason=f"日报看板不是今天生成：{age_text(generated_at, now)}{focus_suffix}。")
        else:
            row.update(status="ok", reason=f"日报已生成，最新数据日期 {source_dates[-1] if source_dates else '-'}{focus_suffix}。")
        row["last_seen_at"] = generated_at.strftime("%Y-%m-%d %H:%M:%S") if generated_at else row["last_seen_at"]
        row["evidence"] = "outputs/daily_focus_status/latest.json" if focus_status else "business-report-dashboard/data/latest.json"

    elif task_id == "ops.review_dashboard":
        payload = read_json(ROOT / "business-report-dashboard" / "data" / "latest.json", {})
        review_actions = read_json(REVIEW_ACTION_STATUS_PATH, {})
        review = payload.get("review_summary") or {}
        review_status = review.get("status")
        action_summary = review_actions.get("summary") or {}
        negative_count = int(action_summary.get("negative_count") or 0)
        completed_negative_count = int(action_summary.get("completed_negative_count") or 0)
        missing_evidence_count = int(action_summary.get("missing_evidence_count") or 0)
        if review_actions.get("status") == "waiting_reply":
            row.update(
                status="warn",
                reason=review_actions.get("message") or f"评价有 {negative_count} 条待处理差评。",
                human_action=review_actions.get("human_action") or "先处理差评门店，再观察单量和复购。",
            )
        elif missing_evidence_count:
            row.update(
                status="warn",
                reason=f"评价已回复记录中有 {missing_evidence_count} 条缺平台截图或链接证据。",
                human_action=review_actions.get("human_action") or "补录平台回复截图、评价链接或工单链接，便于后续复盘。",
            )
        elif review_actions.get("status") == "ok":
            suffix = f"，已记录回复 {completed_negative_count} 条" if completed_negative_count else ""
            base_message = (review_actions.get("message") or "当前评价汇总未发现待处理差评。").rstrip("。")
            row.update(status="ok", reason=base_message + suffix + "。")
        elif review_status == "ready":
            row.update(status="ok", reason=review.get("message") or "评价数据已同步。")
        elif review_status in {"stale", "missing"}:
            row.update(status="warn", reason=review.get("message") or "评价数据未同步到最新日期。")
        row["evidence"] = "outputs/review_action_status/latest.json" if review_actions else "business-report-dashboard/data/latest.json"

    elif task_id == "growth.promo_budget":
        payload = read_json(ROOT / "outputs" / "promo_budget_preview" / "latest.json", {})
        retry_plan = read_json(PROMO_BUDGET_RETRY_PATH, {})
        generated_at = parse_time(payload.get("generated_at"))
        summary = payload.get("summary") or {}
        retry_summary = retry_plan.get("summary") or {}
        repair_guides = retry_plan.get("repair_guides") or []
        if not generated_at:
            row.update(status="warn", reason="推广预算预览尚未生成。")
        elif now - generated_at > timedelta(days=2):
            row.update(status="warn", reason=f"推广预算预览偏旧：{age_text(generated_at, now)}。")
        else:
            retry_text = ""
            if retry_plan.get("status") == "ready":
                affected = int(retry_summary.get("affected_by_latest_run_count") or 0)
                retry_text = f"，可安全重试 {retry_summary.get('safe_retry_count', 0)} 项，需人工处理 {retry_summary.get('manual_count', 0)} 项"
                if affected:
                    retry_text = f"{retry_text}，最近执行影响 {affected} 项"
                if repair_guides:
                    retry_text = f"{retry_text}，修复向导 {len(repair_guides)} 个"
            row.update(status="ok", reason=f"预算预览可用，午餐 {summary.get('total_initial_budget_items') or 0} 项，晚餐 {summary.get('total_dinner_budget_items') or 0} 项{retry_text}。")
        if repair_guides:
            first_guide = repair_guides[0]
            first_step = (first_guide.get("checklist") or [""])[0]
            row["repair_guide"] = f"{first_guide.get('title', '修复向导')}：{first_step}"
        row["last_seen_at"] = generated_at.strftime("%Y-%m-%d %H:%M:%S") if generated_at else row["last_seen_at"]
        row["evidence"] = "outputs/promo_budget_retry_plan/latest.json" if retry_plan else "outputs/promo_budget_preview/latest.json"

    elif task_id == "growth.promo_balance":
        payload = read_json(ROOT / "store-inspection" / "latest.json", {})
        status_payload = read_json(PROMO_BALANCE_STATUS_PATH, {})
        generated_at = parse_time(payload.get("generated_at"))
        summary = status_payload.get("summary") or payload.get("summary") or {}
        evidence_index = status_payload.get("evidence_index") or {}
        evidence_sync = status_payload.get("evidence_sync") or {}
        evidence_count = int(summary.get("evidence_count") or len(evidence_index.get("items") or []))
        sync_file_count = int(evidence_sync.get("file_count") or 0)
        source_status = classify_from_json_status(payload.get("status"))
        platform_failure_count = int(summary.get("platform_failure_count") or 0)
        low_balance_count = int(summary.get("low_balance_count") or summary.get("warning_count") or 0)
        platform_recoveries = [
            (item.get("recovery") or {}).get("summary") or item.get("human_action", "")
            for item in status_payload.get("platforms") or []
            if item.get("status") == "failed"
        ]
        platform_recovery_text = "；".join(item for item in platform_recoveries[:2] if item)
        if status_payload.get("status") == "failed":
            row.update(status="danger", reason=status_payload.get("message") or "推广余额巡检失败。")
            row["human_action"] = platform_recovery_text or status_payload.get("human_action") or "先恢复平台权限、登录或页面状态，再重跑推广余额巡检。"
            if evidence_count:
                row["human_action"] = f"{row['human_action']} 已索引 {evidence_count} 个截图/OCR证据。"
        elif platform_failure_count:
            row.update(status="warn", reason=status_payload.get("message") or f"{platform_failure_count} 个平台余额巡检失败。")
            row["human_action"] = platform_recovery_text or status_payload.get("human_action") or "先处理失败平台，再确认低余额预警是否完整。"
            if evidence_count:
                row["human_action"] = f"{row['human_action']} 已索引 {evidence_count} 个截图/OCR证据。"
        elif source_status == "danger":
            row.update(status="danger", reason=payload.get("message") or "推广余额巡检失败。")
        elif not generated_at:
            row.update(status="warn", reason="推广余额巡检尚未生成。")
        elif now - generated_at > timedelta(days=2):
            row.update(status="warn", reason=f"推广余额巡检偏旧：{age_text(generated_at, now)}。")
        else:
            status = "warn" if low_balance_count else "ok"
            row.update(status=status, reason=f"余额巡检可用，{summary.get('store_count') or 0} 条结果，低余额 {low_balance_count} 条。")
            if low_balance_count:
                action = status_payload.get("human_action") or "先充值低余额门店，再执行预算或出价自动化。"
                if sync_file_count:
                    action = f"{action} 证据上传 dry-run 可检查 {sync_file_count} 个文件。"
                row["human_action"] = action
        row["last_seen_at"] = generated_at.strftime("%Y-%m-%d %H:%M:%S") if generated_at else row["last_seen_at"]
        row["evidence"] = "outputs/promo_balance_status/latest.json" if status_payload else "store-inspection/latest.json"

    elif task_id == "growth.promo_bid":
        payload = read_json(PROMO_BID_ADVICE_PATH, {})
        queue_payload = read_json(PROMO_BID_APPROVAL_QUEUE_PATH, {})
        generated_at = parse_time(payload.get("generated_at"))
        summary = payload.get("summary") or {}
        queue_summary = queue_payload.get("summary") or {}
        queue_generated_at = parse_time(queue_payload.get("generated_at"))
        queue_count = int(queue_summary.get("queue_count") or queue_summary.get("approval_required_count") or 0)
        queue_risk_count = int(queue_summary.get("risk_count") or 0)
        queue_stale_count = int(queue_summary.get("stale_preview_count") or 0)
        source_status = classify_from_json_status(payload.get("status"))
        if queue_payload.get("status") == "waiting_approval":
            row.update(
                status="warn",
                reason=f"出价审批队列待确认，{queue_count} 项，风险 {queue_risk_count} 项，旧预览 {queue_stale_count} 个。",
            )
            row["human_action"] = queue_payload.get("human_action") or "逐项确认出价建议；确认前不自动提交到平台。"
            row["evidence"] = "outputs/promo_bid_approval_queue/latest.json"
            if queue_generated_at:
                row["last_seen_at"] = queue_generated_at.strftime("%Y-%m-%d %H:%M:%S")
        elif queue_payload.get("status") == "no_action":
            row.update(status="ok", reason=queue_payload.get("message") or "当前没有需要审批的推广出价调整。")
            row["human_action"] = queue_payload.get("human_action", "")
            row["evidence"] = "outputs/promo_bid_approval_queue/latest.json"
            if queue_generated_at:
                row["last_seen_at"] = queue_generated_at.strftime("%Y-%m-%d %H:%M:%S")
        elif payload.get("status") == "missing_preview":
            row.update(status="warn", reason=payload.get("message") or "推广出价建议尚未生成。")
        elif not generated_at:
            row.update(status="warn", reason="推广出价建议没有生成时间。")
        elif source_status == "warn":
            row.update(status="warn", reason=f"出价建议可读，但有 {summary.get('stale_preview_count', 0)} 个输入预览偏旧。")
        elif source_status == "ok":
            row.update(status="ok", reason=f"出价只读建议已生成，{summary.get('approval_required_count', 0)} 项需审批，风险 {summary.get('risk_count', 0)} 项。")
        else:
            row.update(status="warn", reason=payload.get("message") or "推广出价建议待检查。")
        if row.get("evidence") != "outputs/promo_bid_approval_queue/latest.json":
            row["evidence"] = "outputs/promo_bid_advice/latest.json"
            row["last_seen_at"] = generated_at.strftime("%Y-%m-%d %H:%M:%S") if generated_at else row["last_seen_at"]
        if int(summary.get("approval_required_count") or 0) and not row.get("human_action"):
            row["human_action"] = "逐项确认出价建议；确认前不自动提交到平台。"

    elif task_id == "flow.inventory":
        payload = runtime.get("inventory") or {}
        health_payload = inventory_probe()
        if health_payload.get("generated_at"):
            payload = health_payload
        if payload.get("status") == "ok":
            row.update(status="ok", reason=payload.get("message") or f"云端库存可访问，预警 {payload.get('warning_count', 0)} 项。")
            generated_at = parse_time(payload.get("generated_at"))
            if generated_at:
                row["last_seen_at"] = generated_at.strftime("%Y-%m-%d %H:%M:%S")
            if payload.get("evidence"):
                row["evidence"] = payload["evidence"]
        elif payload.get("status") == "failed":
            row.update(status="danger", reason=payload.get("message") or "库存云端健康检查失败。")
            generated_at = parse_time(payload.get("generated_at"))
            if generated_at:
                row["last_seen_at"] = generated_at.strftime("%Y-%m-%d %H:%M:%S")
            if payload.get("evidence"):
                row["evidence"] = payload["evidence"]
        elif row["status"] == "unknown":
            row.update(status="warn", reason="库存服务待通过 workbench 数据生成脚本确认。")

    elif task_id == "flow.auto_ordering":
        payload = read_json(ORDER_SUGGESTIONS_PATH, {})
        order_lists = read_json(ORDER_LISTS_PATH, {})
        execution_preview = read_json(ORDER_EXECUTION_PREVIEW_PATH, {})
        android_plan = read_json(ANDROID_EXECUTION_PLAN_PATH, {})
        android_config = read_json(ANDROID_CONFIG_HEALTH_PATH, {})
        generated_at = parse_time(payload.get("generated_at"))
        summary = payload.get("summary") or {}
        confirmation = payload.get("confirmation") or {}
        order_list_summary = order_lists.get("summary") or {}
        execution_summary = execution_preview.get("summary") or {}
        android_summary = android_plan.get("summary") or {}
        android_config_summary = android_config.get("summary") or {}
        if payload.get("status") == "ready":
            channel_count = int(summary.get("channel_count") or 0)
            suggestion_count = int(summary.get("suggestion_count") or 0)
            if suggestion_count == 0 or order_lists.get("status") == "not_required":
                row.update(
                    status="ok",
                    reason="订货建议已生成，当前没有低库存商品需要订货。",
                    human_action="",
                    evidence="outputs/inventory_order_lists/latest.json" if order_lists else "outputs/inventory_order_suggestions/latest.json",
                )
            elif android_plan.get("status") == "ready":
                if android_config.get("status") == "missing_config":
                    row.update(
                        status="warn",
                        reason=f"远控安卓执行计划已生成，但设备连接配置缺少 {android_config_summary.get('missing_count', 0)} 项。",
                        human_action="；".join(android_config.get("missing") or []) or "填写 config/android_execution.json。",
                        evidence="outputs/android_execution_config/latest.json",
                    )
                else:
                    row.update(
                        status="warn",
                        reason=f"远控安卓执行适配计划已生成，{android_summary.get('channel_count', 0)} 个供应渠道，只读预览。",
                        human_action=android_plan.get("operator", {}).get("message") or "人工操作员接管远控安卓，系统不自动提交订单或付款。",
                        evidence="outputs/inventory_android_execution_plan/latest.json",
                    )
            elif android_plan.get("status") == "waiting_payment_confirmation":
                row.update(
                    status="warn",
                    reason="远控安卓执行计划等待付款确认。",
                    human_action=android_plan.get("message") or "付款确认前不会生成可执行步骤。",
                    evidence="outputs/inventory_android_execution_plan/latest.json",
                )
            elif execution_preview.get("status") == "payment_confirmed":
                row.update(
                    status="warn",
                    reason=f"订货付款已确认，{execution_summary.get('channel_count', 0)} 个供应渠道可进入远控安卓执行。",
                    human_action=execution_preview.get("payment_confirmation", {}).get("message") or "执行前再次确认安卓远控目标平台和门店。",
                    evidence="outputs/inventory_order_execution_preview/latest.json",
                )
            elif execution_preview.get("status") == "waiting_payment_confirmation":
                row.update(
                    status="warn",
                    reason=f"下单执行预览已生成，{execution_summary.get('channel_count', 0)} 个供应渠道，等待付款确认。",
                    human_action=execution_preview.get("payment_confirmation", {}).get("message") or "付款前核对金额和渠道，不要自动付款。",
                    evidence="outputs/inventory_order_execution_preview/latest.json",
                )
            elif order_lists.get("status") == "ready":
                row.update(
                    status="warn",
                    reason=f"渠道下单清单已生成，{order_list_summary.get('order_list_count', 0)} 个供应渠道，付款前仍需人工核对。",
                    human_action=order_lists.get("confirmation", {}).get("message") or "按渠道清单下单前再次核对数量和金额。",
                    evidence="outputs/inventory_order_lists/latest.json",
                )
            else:
                confirm_text = "需人工确认后再下单" if confirmation.get("status") == "pending" else "当前无需订货"
                row.update(
                    status="warn",
                    reason=f"订货建议已生成，{summary.get('suggestion_count', 0)} 项，{channel_count} 个供应渠道，{confirm_text}。",
                    human_action=confirmation.get("message") or "先人工确认订货建议，不要自动下单或付款。",
                    evidence="outputs/inventory_order_suggestions/latest.json",
                )
            if order_lists.get("status") == "waiting_confirmation":
                row["human_action"] = order_lists.get("confirmation", {}).get("message") or row["human_action"]
                row["evidence"] = "outputs/inventory_order_lists/latest.json"
            if order_lists.get("status") == "failed":
                row.update(status="danger", reason=order_lists.get("message") or "渠道下单清单生成失败。", evidence="outputs/inventory_order_lists/latest.json")
            if execution_preview.get("status") == "failed":
                row.update(status="danger", reason=execution_preview.get("message") or "下单执行预览生成失败。", evidence="outputs/inventory_order_execution_preview/latest.json")
            if android_plan.get("status") == "failed":
                row.update(status="danger", reason=android_plan.get("message") or "远控安卓执行适配计划生成失败。", evidence="outputs/inventory_android_execution_plan/latest.json")
        elif payload.get("status") == "failed":
            row.update(status="danger", reason=payload.get("message") or "订货建议生成失败。", evidence="outputs/inventory_order_suggestions/latest.json")
        if generated_at:
            row["last_seen_at"] = generated_at.strftime("%Y-%m-%d %H:%M:%S")

    elif task_id == "tools.sales_receipt":
        payload = read_json(TOOL_WAREHOUSE_STATUS_PATH, {})
        sales = payload.get("sales_receipt") or {}
        generated_at = parse_time(payload.get("generated_at"))
        if sales.get("status") == "ready":
            row.update(status="ok", reason=sales.get("message") or "销售单生成器资源完整。", evidence="outputs/tool_warehouse_status/latest.json")
        elif sales.get("status") == "needs_print_check":
            row.update(status="warn", reason=sales.get("message") or "销售单生成器等待打印版式校验。", evidence="outputs/tool_warehouse_status/latest.json")
            row["human_action"] = "运行 node scripts/check_sales_receipt_print_layout.mjs 生成截图校验。"
        elif sales.get("status") == "print_check_failed":
            row.update(status="danger", reason=sales.get("message") or "销售单打印版式校验失败。", evidence="outputs/sales_receipt_print_check/latest.json")
            row["human_action"] = "检查销售单样式和打印缩放，确保样例单据可压入一页。"
        elif sales:
            row.update(status="danger", reason=sales.get("message") or "销售单生成器资源缺失。", evidence="outputs/tool_warehouse_status/latest.json")
        else:
            page = ROOT / "sales-receipt-generator" / "index.html"
            if page.exists():
                row.update(status="ok", reason="销售单生成器页面存在，可从工具仓库打开。", evidence="sales-receipt-generator/index.html")
        if generated_at:
            row["last_seen_at"] = generated_at.strftime("%Y-%m-%d %H:%M:%S")

    elif task_id == "finance.bill_analysis":
        payload = read_json(FINANCE_CENTER_STATUS_PATH, {})
        generated_at = parse_time(payload.get("generated_at"))
        summary = payload.get("summary") or {}
        if payload.get("status") == "ready_for_mapping":
            row.update(
                status="warn",
                reason=f"账单样例和字段字典已就绪，{summary.get('sample_file_count', 0)} 个样例可进入字段映射。",
                evidence="outputs/finance_center_status/latest.json",
                human_action="确认科目口径后再生成财务报表。",
            )
        elif payload.get("status") == "waiting_samples":
            row.update(
                status="warn",
                reason=payload.get("message") or "财务中心等待账单样例。",
                evidence="outputs/finance_center_status/latest.json",
                human_action="提供银行账单和美团/饿了么平台账单样例。",
            )
        if generated_at:
            row["last_seen_at"] = generated_at.strftime("%Y-%m-%d %H:%M:%S")

    return row


def attach_human_action(row: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    if row["status"] in {"danger", "warn"} and task.get("human_needed_when") and not row.get("human_action"):
        row["human_action"] = "；".join(task["human_needed_when"][:2])
    return row


def build_task_health(now: datetime | None = None, runtime: dict[str, Any] | None = None) -> dict[str, Any]:
    now = now or datetime.now()
    runtime = runtime or {}
    if "inventory" not in runtime:
        runtime["inventory"] = inventory_probe()
    registry = read_json(TASKS_PATH, {"tasks": []})
    run_state = read_json(TASK_RUNS_PATH, {"tasks": {}})
    rows = []
    for task in registry.get("tasks", []):
        row = base_task_state(task, now)
        row = enrich_known_task(row, now, runtime)
        row = apply_run_state(row, run_state, now)
        row["status_text"] = STATUS_LABELS.get(row["status"], row["status"])
        rows.append(attach_human_action(row, task))

    summary = {
        "total": len(rows),
        "ok": sum(1 for item in rows if item["status"] == "ok"),
        "warn": sum(1 for item in rows if item["status"] == "warn"),
        "danger": sum(1 for item in rows if item["status"] == "danger"),
        "planned": sum(1 for item in rows if item["status"] == "planned"),
        "unknown": sum(1 for item in rows if item["status"] == "unknown"),
    }
    return {
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "registry_updated_at": registry.get("updated_at", ""),
        "environment": runtime_environment(),
        "summary": summary,
        "tasks": rows,
    }


def write_task_health(payload: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LATEST_PATH.chmod(0o644)


def main() -> int:
    payload = build_task_health()
    write_task_health(payload)
    summary = payload["summary"]
    print(
        "任务健康状态已生成："
        f"{LATEST_PATH}，正常 {summary['ok']}，注意 {summary['warn']}，需处理 {summary['danger']}，规划中 {summary['planned']}。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
