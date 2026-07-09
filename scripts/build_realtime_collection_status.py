from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from task_run_state import classify_failure_text


ROOT = Path(__file__).resolve().parents[1]
REALTIME_DIR = ROOT / "outputs" / "realtime_order_income"
LATEST_PATH = REALTIME_DIR / "latest.json"
FAILED_PATH = REALTIME_DIR / "last_failed.json"
TASK_RUNS_PATH = ROOT / "outputs" / "task_runs" / "latest.json"
OUTPUT_DIR = ROOT / "outputs" / "realtime_order_income_status"
OUTPUT_PATH = OUTPUT_DIR / "latest.json"
TASK_ID = "ops.realtime_order_income"
ACTIVE_STALE_AFTER = timedelta(minutes=95)

REPAIR_GUIDES = {
    "auth_block": {
        "title": "实时采集登录恢复向导",
        "checklist": [
            "在 Mac mini 的 Chrome 打开对应平台后台。",
            "完成登录、验证码或安全验证。",
            "运行 python3 scripts/realtime_order_income.py 做只读复查。",
        ],
    },
    "browser_closed": {
        "title": "Chrome/CDP 恢复向导",
        "checklist": [
            "确认 Mac mini 的 Chrome 和 CDP 调试窗口保持打开。",
            "如页面反复关闭，重启 Chrome 后重新进入平台后台。",
            "先运行实时采集只读命令确认连接恢复。",
        ],
    },
    "timeout": {
        "title": "实时采集超时恢复向导",
        "checklist": [
            "确认 Mac mini 网络和平台后台页面访问正常。",
            "关闭卡住的后台页面，必要时重启 Chrome/CDP。",
            "连续两次超时后只复查失败平台，不扩大到其他高风险动作。",
        ],
    },
    "page_structure": {
        "title": "实时数据页面改版排查向导",
        "checklist": [
            "人工打开失败平台后台，确认实时单量、营业额位置是否变化。",
            "保存页面提示或截图，定位实时采集识别规则。",
            "在 MacBook 修复脚本并推送后，再同步到 Mac mini。",
        ],
    },
    "missing_platform_store": {
        "title": "实时采集门店映射向导",
        "checklist": [
            "核对缺失门店是否仍在营业、是否改名或平台门店 ID 变化。",
            "更新对应平台门店映射。",
            "运行实时采集只读命令确认 18 个平台门店覆盖恢复。",
        ],
    },
}


def normalize_failure_type(message: str, fallback: str = "") -> str:
    body = str(message or "")
    if "Target page, context or browser has been closed" in body or "browser has been closed" in body:
        return "browser_closed"
    return fallback or classify_failure_text(body)


def human_action_for(failure_type: str, platform: str) -> str:
    if failure_type == "auth_block":
        return f"在 Mac mini 的 Chrome 恢复{platform}登录或验证码后，重跑实时单量采集。"
    if failure_type == "browser_closed":
        return f"确认 Mac mini 的 Chrome/CDP 窗口保持打开并已登录{platform}；如反复关闭，重启 Chrome 后重跑实时采集。"
    if failure_type == "timeout":
        return f"先确认{platform}后台页面能打开，再重跑实时采集；连续超时再重启 Chrome/CDP。"
    if failure_type == "page_structure":
        return f"{platform}页面结构可能变化，先人工核对后台页面，再调整实时采集识别规则。"
    if failure_type == "missing_platform_store":
        return f"检查{platform}门店映射和接口返回，确认缺失门店是否仍在营业或是否改名。"
    return f"先查看{platform}实时采集日志，确认登录、页面、接口和门店映射是否正常。"


def store_recovery_action(platform: str, store: str, failure_type: str) -> dict[str, Any]:
    if failure_type == "browser_closed":
        action = f"先恢复 Mac mini Chrome/CDP，再确认{platform}后台能看到{store}实时数据。"
    elif failure_type == "auth_block":
        action = f"先恢复{platform}登录或验证码，再检查{store}是否回到实时采集结果。"
    elif failure_type == "missing_platform_store":
        action = f"核对{platform}门店映射、门店是否营业、名称是否改动：{store}。"
    elif failure_type == "page_structure":
        action = f"人工打开{platform}{store}后台，确认实时单量位置是否变化。"
    else:
        action = f"查看{platform}{store}实时采集日志，确认登录、页面、接口和门店映射。"
    return {
        "platform": platform,
        "store": store,
        "failure_type": failure_type,
        "human_action": action,
        "verify_command": "python3 scripts/realtime_order_income.py",
    }


def repair_guide_for(failure: dict[str, Any]) -> dict[str, Any]:
    failure_type = failure.get("failure_type") or "unknown"
    platform = failure.get("platform") or "未知平台"
    guide = REPAIR_GUIDES.get(failure_type) or {
        "title": "实时采集通用排查向导",
        "checklist": [
            "查看实时采集日志和平台后台页面提示。",
            "确认登录、Chrome/CDP、页面结构、接口返回和门店映射。",
            "先运行只读实时采集复查，再恢复定时任务。",
        ],
    }
    checklist = list(guide["checklist"])
    if failure.get("human_action") and failure["human_action"] not in checklist:
        checklist.append(failure["human_action"])
    store_actions = [
        action.get("human_action", "")
        for action in failure.get("store_recovery_actions") or []
        if action.get("human_action")
    ]
    checklist.extend(action for action in store_actions[:2] if action not in checklist)
    return {
        "id": f"{failure_type}.{platform}",
        "title": guide["title"],
        "priority": "high" if failure_type in {"auth_block", "browser_closed", "page_structure"} else "medium",
        "target": platform,
        "platform": platform,
        "failure_type": failure_type,
        "missing_count": int(failure.get("missing_count") or 0),
        "stores": failure.get("stores") or [],
        "checklist": checklist,
        "verify_command": "python3 scripts/realtime_order_income.py",
        "evidence": "outputs/realtime_order_income/last_failed.json",
    }


def build_repair_guides(platform_failures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    guides = [repair_guide_for(failure) for failure in platform_failures]
    return sorted(guides, key=lambda item: (0 if item["priority"] == "high" else 1, item["target"]))


def repair_templates() -> list[dict[str, Any]]:
    labels = {
        "auth_block": "平台登录/验证码",
        "browser_closed": "Chrome/CDP 关闭",
        "timeout": "网络或页面超时",
        "page_structure": "实时数据页面改版",
        "missing_platform_store": "平台门店缺失",
    }
    return [
        {
            "failure_type": failure_type,
            "title": guide["title"],
            "trigger": labels.get(failure_type, failure_type),
            "checklist": guide["checklist"],
        }
        for failure_type, guide in sorted(REPAIR_GUIDES.items())
    ]


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:26] if "." in text else text[:19], fmt)
        except ValueError:
            continue
    return None


def active_realtime_window(now: datetime) -> bool:
    return 10 <= now.hour < 20


def write_latest(payload: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUTPUT_PATH.chmod(0o644)


def classify_payload_failure(payload: dict[str, Any], task_run: dict[str, Any]) -> str:
    task_failure_type = str(task_run.get("failure_type") or "")
    if task_failure_type and task_failure_type != "execution_failed":
        return task_failure_type
    errors = payload.get("errors") or []
    if errors:
        return classify_failure_text("；".join(str(item) for item in errors))
    if task_failure_type:
        return task_failure_type
    missing = payload.get("missing") or []
    if missing:
        return "missing_platform_store"
    if payload.get("status") in {"failed", "error"}:
        return classify_failure_text(payload.get("message") or "")
    return ""


def build_platform_failures(payload: dict[str, Any], fallback_failure_type: str) -> list[dict[str, Any]]:
    errors = [str(item) for item in payload.get("errors") or [] if item]
    missing = payload.get("missing") or []
    by_platform: dict[str, dict[str, Any]] = {}
    for item in missing:
        if not isinstance(item, dict):
            continue
        platform = str(item.get("platform") or "未知平台")
        row = by_platform.setdefault(
            platform,
            {
                "platform": platform,
                "status": "failed",
                "missing_count": 0,
                "stores": [],
                "message": "",
                "failure_type": fallback_failure_type or "missing_platform_store",
                "human_action": "",
            },
        )
        row["missing_count"] += 1
        if item.get("store"):
            row["stores"].append(str(item["store"]))

    for error in errors:
        platform = "未知平台"
        detail = error
        if "采集失败：" in error:
            platform, detail = error.split("采集失败：", 1)
            platform = platform.strip()
            detail = detail.strip()
        failure_type = normalize_failure_type(detail, fallback_failure_type)
        row = by_platform.setdefault(
            platform,
            {
                "platform": platform,
                "status": "failed",
                "missing_count": 0,
                "stores": [],
                "message": "",
                "failure_type": failure_type,
                "human_action": "",
            },
        )
        row["message"] = detail
        row["failure_type"] = failure_type

    failures = []
    for row in by_platform.values():
        unique_stores = []
        for store in row["stores"]:
            if store not in unique_stores:
                unique_stores.append(store)
        row["stores"] = unique_stores
        row["store_recovery_actions"] = [
            store_recovery_action(row["platform"], store, row["failure_type"])
            for store in unique_stores
        ]
        if not row["message"]:
            store_text = "、".join(row["stores"][:4])
            if len(row["stores"]) > 4:
                store_text += f"等 {len(row['stores'])} 家"
            row["message"] = f"缺失 {row['missing_count']} 个平台门店：{store_text or '待确认'}。"
        row["human_action"] = human_action_for(row["failure_type"], row["platform"])
        if row["store_recovery_actions"]:
            first_store_action = row["store_recovery_actions"][0]["human_action"]
            row["recovery_summary"] = f"{row['human_action']} 门店级先处理：{first_store_action}"
        else:
            row["recovery_summary"] = row["human_action"]
        failures.append(row)
    return sorted(failures, key=lambda item: (item.get("platform") or "", item.get("missing_count") or 0), reverse=True)


def build_payload(now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now()
    latest = read_json(LATEST_PATH, {})
    failed = read_json(FAILED_PATH, {})
    run_state = read_json(TASK_RUNS_PATH, {"tasks": {}})
    task_run = (run_state.get("tasks") or {}).get(TASK_ID) or {}
    latest_time = parse_time(latest.get("generated_at"))
    failed_time = parse_time(failed.get("generated_at"))
    latest_summary = latest.get("summary") or {}
    failed_summary = failed.get("summary") or {}
    latest_success = latest.get("status") in {"ok", "ready", "success"} and int(latest_summary.get("missing_count") or 0) == 0
    failure_type = classify_payload_failure(failed, task_run)
    raw_platform_failures = build_platform_failures(failed, failure_type)
    stale = bool(latest_time and active_realtime_window(now) and now - latest_time > ACTIVE_STALE_AFTER)
    if not latest:
        status = "missing_latest"
        message = "尚未找到实时单量收入最新成功采集。"
    elif stale:
        status = "stale"
        message = f"实时采集最近成功时间偏旧：{latest.get('generated_at')}。"
    elif failed_time and latest_time and failed_time > latest_time:
        status = "failed_after_success"
        message = "最近一次实时采集失败，但仍保留上一份成功数据。"
    elif latest_success:
        status = "ok"
        message = "实时单量收入最近成功采集可用。"
    else:
        status = "partial"
        message = "实时单量收入采集不完整。"
    platform_failures = [] if status == "ok" else raw_platform_failures
    repair_guides = build_repair_guides(platform_failures)
    platform_failure_count = len(platform_failures)
    failed_store_count = sum(int(item.get("missing_count") or 0) for item in platform_failures)
    return {
        "generated_at": now_text(),
        "status": status,
        "message": message,
        "last_success_at": latest.get("generated_at", "") if latest_success else "",
        "last_failure_at": failed.get("generated_at", "") if failed else "",
        "failure_type": failure_type,
        "platform_failures": platform_failures,
        "repair_guides": repair_guides,
        "repair_templates": repair_templates(),
        "human_action": platform_failures[0]["human_action"] if platform_failures else "",
        "latest": {
            "status": latest.get("status", ""),
            "summary": latest_summary,
        },
        "last_failed": {
            "status": failed.get("status", ""),
            "summary": failed_summary,
            "errors": failed.get("errors") or [],
            "missing": failed.get("missing") or [],
        },
        "task_run": {
            "status": task_run.get("status", ""),
            "message": task_run.get("message", ""),
            "step": task_run.get("step", ""),
            "updated_at": task_run.get("updated_at", ""),
            "failure_type": task_run.get("failure_type", ""),
        },
        "summary": {
            "platform_store_count": int(latest_summary.get("platform_store_count") or 0),
            "missing_count": int(latest_summary.get("missing_count") or 0),
            "failed_missing_count": int(failed_summary.get("missing_count") or 0),
            "platform_failure_count": platform_failure_count,
            "failed_platform_store_count": failed_store_count,
            "repair_guide_count": len(repair_guides),
            "total_orders": int(latest_summary.get("total_orders") or 0),
            "total_income": float(latest_summary.get("total_income") or 0),
        },
    }


def main() -> int:
    payload = build_payload()
    write_latest(payload)
    print(payload["message"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
