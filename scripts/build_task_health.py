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
INVENTORY_HEALTH_PATH = ROOT / "outputs" / "inventory_health" / "latest.json"
CLOUD_INVENTORY_URL = "http://139.155.148.169/api/summary"


STATUS_LABELS = {
    "ok": "正常",
    "warn": "注意",
    "danger": "需处理",
    "planned": "规划中",
    "unknown": "待接入",
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
            row["reason"] = f"{row['reason']}（{failure_type}）"
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
    if task_id == "ops.realtime_order_income":
        payload = read_json(ROOT / "outputs" / "realtime_order_income" / "latest.json", {})
        generated_at = parse_time(payload.get("generated_at"))
        source_status = classify_from_json_status(payload.get("status"))
        summary = payload.get("summary") or {}
        missing = int(summary.get("missing_count") or 0)
        if source_status == "danger":
            row.update(status="danger", reason=payload.get("message") or "实时采集失败。")
        elif generated_at and active_realtime_window(now) and now - generated_at > timedelta(minutes=95):
            row.update(status="warn", reason=f"实时采集已超过计划窗口：{age_text(generated_at, now)}。")
        elif missing:
            row.update(status="warn", reason=f"实时采集缺失 {missing} 个平台门店。")
        elif generated_at:
            row.update(status="ok", reason=f"实时采集覆盖 {summary.get('platform_store_count') or '-'} 个平台门店。")
        row["last_seen_at"] = generated_at.strftime("%Y-%m-%d %H:%M:%S") if generated_at else row["last_seen_at"]
        row["evidence"] = "outputs/realtime_order_income/latest.json"

    elif task_id == "ops.daily_report":
        payload = read_json(ROOT / "business-report-dashboard" / "data" / "latest.json", {})
        generated_at = parse_time(payload.get("generated_at"))
        records = payload.get("records") or []
        source_dates = payload.get("source_dates") or []
        if not records:
            row.update(status="danger", reason="日报 latest.json 没有可用记录。")
        elif generated_at and not within_today(generated_at, now):
            row.update(status="warn", reason=f"日报看板不是今天生成：{age_text(generated_at, now)}。")
        else:
            row.update(status="ok", reason=f"日报已生成，最新数据日期 {source_dates[-1] if source_dates else '-'}。")
        row["last_seen_at"] = generated_at.strftime("%Y-%m-%d %H:%M:%S") if generated_at else row["last_seen_at"]
        row["evidence"] = "business-report-dashboard/data/latest.json"

    elif task_id == "ops.review_dashboard":
        payload = read_json(ROOT / "business-report-dashboard" / "data" / "latest.json", {})
        review = payload.get("review_summary") or {}
        review_status = review.get("status")
        if review_status == "ready":
            row.update(status="ok", reason=review.get("message") or "评价数据已同步。")
        elif review_status in {"stale", "missing"}:
            row.update(status="warn", reason=review.get("message") or "评价数据未同步到最新日期。")
        row["evidence"] = "business-report-dashboard/data/latest.json"

    elif task_id == "growth.promo_budget":
        payload = read_json(ROOT / "outputs" / "promo_budget_preview" / "latest.json", {})
        generated_at = parse_time(payload.get("generated_at"))
        summary = payload.get("summary") or {}
        if not generated_at:
            row.update(status="warn", reason="推广预算预览尚未生成。")
        elif now - generated_at > timedelta(days=2):
            row.update(status="warn", reason=f"推广预算预览偏旧：{age_text(generated_at, now)}。")
        else:
            row.update(status="ok", reason=f"预算预览可用，午餐 {summary.get('total_initial_budget_items') or 0} 项，晚餐 {summary.get('total_dinner_budget_items') or 0} 项。")
        row["last_seen_at"] = generated_at.strftime("%Y-%m-%d %H:%M:%S") if generated_at else row["last_seen_at"]
        row["evidence"] = "outputs/promo_budget_preview/latest.json"

    elif task_id == "growth.promo_balance":
        payload = read_json(ROOT / "store-inspection" / "latest.json", {})
        generated_at = parse_time(payload.get("generated_at"))
        summary = payload.get("summary") or {}
        source_status = classify_from_json_status(payload.get("status"))
        if source_status == "danger":
            row.update(status="danger", reason=payload.get("message") or "推广余额巡检失败。")
        elif not generated_at:
            row.update(status="warn", reason="推广余额巡检尚未生成。")
        elif now - generated_at > timedelta(days=2):
            row.update(status="warn", reason=f"推广余额巡检偏旧：{age_text(generated_at, now)}。")
        else:
            warning_count = int(summary.get("warning_count") or 0)
            status = "warn" if warning_count else "ok"
            row.update(status=status, reason=f"余额巡检可用，{summary.get('store_count') or 0} 条结果，低余额 {warning_count} 条。")
        row["last_seen_at"] = generated_at.strftime("%Y-%m-%d %H:%M:%S") if generated_at else row["last_seen_at"]
        row["evidence"] = "store-inspection/latest.json"

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

    elif task_id == "tools.sales_receipt":
        page = ROOT / "sales-receipt-generator" / "index.html"
        if page.exists():
            row.update(status="ok", reason="销售单生成器页面存在，可从工具仓库打开。", evidence="sales-receipt-generator/index.html")

    return row


def attach_human_action(row: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    if row["status"] in {"danger", "warn"} and task.get("human_needed_when"):
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
