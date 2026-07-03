from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PREVIEW_PATH = ROOT / "outputs" / "promo_budget_preview" / "latest.json"
OVERRIDES_PATH = ROOT / "config" / "promo_budget_overrides.json"
TASK_RUNS_PATH = ROOT / "outputs" / "task_runs" / "latest.json"
OUTPUT_DIR = ROOT / "outputs" / "promo_budget_retry_plan"
LATEST_PATH = OUTPUT_DIR / "latest.json"
MEITUAN_BUDGET_DIR = ROOT / "outputs" / "meituan_budget_automation"

SAFE_RETRY_FAILURE_TYPES = {
    "timeout",
    "execution_failed",
    "input_sync_failed",
    "confirm_disabled",
    "dianjin_entry_missing",
    "direct_promo_url_missing",
}

MANUAL_FAILURE_TYPES = {
    "auth_block",
    "permission",
    "budget_guardrail",
    "page_structure",
    "page_structure_changed",
    "store_mapping",
    "manual_browser_setup",
}

REPAIR_GUIDES = {
    "auth_block": {
        "title": "推广预算登录恢复向导",
        "checklist": [
            "在 Mac mini 的 Chrome 打开对应平台推广后台。",
            "完成登录、验证码或安全验证。",
            "先重新生成预算预览，再决定是否重跑对应平台时段。",
        ],
    },
    "permission": {
        "title": "推广预算权限恢复向导",
        "checklist": [
            "检查 Mac mini 终端、Chrome、Python 的屏幕录制和文件访问权限。",
            "补齐权限后重启 Chrome/CDP。",
            "先做预算预览和只读检查，不直接提交预算。",
        ],
    },
    "budget_guardrail": {
        "title": "预算安全上限复核向导",
        "checklist": [
            "核对门店目标预算、配置上限和当日经营状态。",
            "确认是否需要临时提高门店安全上限。",
            "修改配置后重新生成预算预览，确认无异常再提交。",
        ],
    },
    "page_structure": {
        "title": "推广预算页面改版排查向导",
        "checklist": [
            "人工打开失败平台预算页，确认预算按钮、输入框或弹窗名称是否变化。",
            "保存页面提示或截图，定位对应平台预算脚本选择器。",
            "在 MacBook 修复脚本并推送后，再同步到 Mac mini 重跑。",
        ],
    },
    "input_sync_failed": {
        "title": "预算输入框同步恢复向导",
        "checklist": [
            "优先只重试失败门店，脚本会重新打开预算弹窗并重新填入目标预算。",
            "若连续两次仍失败，人工打开该门店预算弹窗，确认输入框是否被平台限制或页面结构变化。",
            "保存失败截图和输入框文本，作为脚本选择器修复依据。",
        ],
    },
    "confirm_disabled": {
        "title": "预算确定按钮禁用恢复向导",
        "checklist": [
            "只重试失败门店，脚本会重新触发表单 change/blur 并再次检查按钮状态。",
            "若按钮仍禁用，人工确认当前页面预算是否已经等于目标值。",
            "若页面预算不等于目标值且按钮禁用，按页面改版或平台限制处理。",
        ],
    },
    "direct_promo_url_missing": {
        "title": "直营美团点金入口恢复向导",
        "checklist": [
            "检查对应直营 Chrome profile 是否仍保持登录。",
            "优先打开配置里的点金推广直达页，确认能进入内层 ad/v1/rpc 页面。",
            "若入口变化，更新直营账号 promo_balance 配置后再重跑。",
        ],
    },
    "dianjin_entry_missing": {
        "title": "美团点金入口加载恢复向导",
        "checklist": [
            "刷新美团门店推广页面，确认点金推广入口可见。",
            "入口加载慢时只重试失败门店，不重跑全平台。",
            "若入口名称变化，保存截图后修复入口识别逻辑。",
        ],
    },
    "store_mapping": {
        "title": "推广预算门店映射修复向导",
        "checklist": [
            "核对平台后台门店名称是否改名、停业或新增。",
            "更新门店映射或预算覆盖配置。",
            "重新生成预算预览，确认门店进入正确平台和时段。",
        ],
    },
    "manual_browser_setup": {
        "title": "推广预算浏览器准备向导",
        "checklist": [
            "在 Mac mini 的 Chrome 手动打开对应平台推广预算页。",
            "确认当前账号、门店和预算弹窗可见。",
            "保持浏览器打开，再重跑对应平台和时段。",
        ],
    },
    "timeout": {
        "title": "推广预算超时重试向导",
        "checklist": [
            "确认平台预算页可打开且网络正常。",
            "关闭卡住的弹窗或重启 Chrome/CDP。",
            "仅重跑失败的平台和时段，并在保存后复核目标预算。",
        ],
    },
    "execution_failed": {
        "title": "推广预算普通执行失败重试向导",
        "checklist": [
            "查看最近执行日志，确认不是登录、权限、页面改版或预算安全问题。",
            "只重跑失败的平台和时段。",
            "保存后复核平台后台预算是否等于目标值。",
        ],
    },
}


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def write_latest(payload: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LATEST_PATH.chmod(0o644)


def normalized_items(preview: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in ("eleme_lunch", "eleme_dinner", "meituan_lunch", "meituan_dinner"):
        for item in preview.get(key) or []:
            mapped_store = item.get("store") or ""
            rows.append(
                {
                    "source": key,
                    "platform": item.get("platform") or ("饿了么" if key.startswith("eleme") else "美团"),
                    "store": mapped_store or item.get("sourceStore") or "",
                    "mapped_store": mapped_store,
                    "source_store": item.get("sourceStore") or item.get("store") or "",
                    "period": item.get("period") or ("午餐" if key.endswith("lunch") else "晚餐"),
                    "time": item.get("time") or "",
                    "target_budget": float(item.get("targetBudget") or item.get("budget") or 0),
                    "status": item.get("status") or "",
                }
            )
    return rows


def override_for(overrides: dict[str, Any], store: str, platform: str) -> dict[str, Any]:
    store_config = (overrides.get("stores") or {}).get(store) or {}
    return store_config.get(platform) or store_config.get("all") or {}


def latest_budget_run(run_state: dict[str, Any]) -> dict[str, Any]:
    task = (run_state.get("tasks") or {}).get("growth.promo_budget")
    return task if isinstance(task, dict) else {}


def latest_meituan_results(period: str) -> list[dict[str, Any]]:
    if not period:
        return []
    paths = sorted(
        MEITUAN_BUDGET_DIR.glob(f"meituan_cdp_{period}_*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in paths:
        payload = read_json(path, {})
        results = payload.get("results")
        if isinstance(results, list):
            return [item for item in results if isinstance(item, dict)]
    return []


def run_affects_item(item: dict[str, Any], run: dict[str, Any]) -> bool:
    if not run:
        return False
    step = str(run.get("step") or "")
    platform = str(item.get("platform") or "")
    period = str(item.get("period") or "")
    if platform and platform not in step:
        return False
    if period and period not in step:
        return False
    return True


def store_result_for(item: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    extra = run.get("extra") or {}
    results = extra.get("store_results") or extra.get("stores") or []
    if not isinstance(results, list):
        return {}
    names = {str(name) for name in (item.get("store"), item.get("source_store")) if name}
    for result in results:
        if not isinstance(result, dict):
            continue
        if str(result.get("store") or result.get("source_store") or "") in names:
            return result
    return {}


def platform_result_for(item: dict[str, Any]) -> dict[str, Any]:
    if item.get("platform") != "美团":
        return {}
    names = {str(name) for name in (item.get("store"), item.get("source_store")) if name}
    for result in latest_meituan_results(str(item.get("period") or "")):
        candidates = {
            str(result.get("store") or ""),
            str(result.get("source_store") or ""),
            str(result.get("keyword") or ""),
        }
        if any(name and any(name in candidate or candidate in name for candidate in candidates if candidate) for name in names):
            return result
    return {}


def runtime_feedback_for(item: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    result = store_result_for(item, run)
    if not result:
        result = platform_result_for(item)
    if result:
        status = str(result.get("status") or "")
        if not status:
            status = "success" if result.get("ok") else "failed"
        failure_type = str(result.get("failure_type") or "")
        message = str(result.get("message") or result.get("error") or "")
        return {
            "scope": "store",
            "status": status,
            "failure_type": failure_type,
            "message": message,
            "updated_at": run.get("updated_at", ""),
        }
    if run_affects_item(item, run):
        return {
            "scope": "platform_period",
            "status": run.get("status", ""),
            "failure_type": run.get("failure_type", ""),
            "message": run.get("message", ""),
            "updated_at": run.get("updated_at", ""),
        }
    return {
        "scope": "",
        "status": "",
        "failure_type": "",
        "message": "",
        "updated_at": "",
    }


def retry_policy_for(item: dict[str, Any], overrides: dict[str, Any], latest_run: dict[str, Any] | None = None) -> dict[str, Any]:
    platform = item["platform"]
    target_budget = float(item.get("target_budget") or 0)
    store_override = override_for(overrides, item.get("source_store") or item.get("store"), platform)
    max_retry = int(store_override.get("maxRetry") or 1)
    budget_cap = float(store_override.get("maxBudget") or 300)
    safe_to_retry = target_budget > 0 and target_budget <= budget_cap and max_retry > 0
    manual_reasons: list[str] = []
    if not item.get("mapped_store") or item.get("status") == "unmatched":
        manual_reasons.append("门店映射缺失")
    if target_budget <= 0:
        manual_reasons.append("目标预算为空")
    if target_budget > budget_cap:
        manual_reasons.append(f"目标预算 {target_budget:g} 超过安全上限 {budget_cap:g}")
    runtime_feedback = runtime_feedback_for(item, latest_run or {})
    failure_type = runtime_feedback.get("failure_type") or ""
    if runtime_feedback.get("status") == "failed" and failure_type in MANUAL_FAILURE_TYPES:
        manual_reasons.append(f"最近执行失败需人工处理：{failure_type}")
    if runtime_feedback.get("status") == "failed" and failure_type == "confirm_disabled":
        message = runtime_feedback.get("message") or ""
        if "0-0" in message or "页面预算" in message:
            manual_reasons.append(f"平台拒绝确认预算：{message}")

    return {
        "platform": platform,
        "store": item.get("store") or "未匹配门店",
        "source_store": item.get("source_store") or "",
        "period": item.get("period") or "",
        "time": item.get("time") or "",
        "target_budget": target_budget,
        "safe_to_retry": safe_to_retry and not manual_reasons,
        "max_retry": max_retry if safe_to_retry and not manual_reasons else 0,
        "retry_delay_seconds": int(store_override.get("retryDelaySeconds") or 90),
        "safe_failure_types": sorted(SAFE_RETRY_FAILURE_TYPES),
        "manual_failure_types": sorted(MANUAL_FAILURE_TYPES),
        "manual_reasons": manual_reasons,
        "last_run": runtime_feedback,
        "next_action": "仅限超时或普通执行失败时重试；登录、权限、页面结构、预算安全和门店映射问题必须人工处理。"
        if safe_to_retry and not manual_reasons
        else "进入人工处理，不自动重试。",
    }


def repair_guide_for(row: dict[str, Any]) -> dict[str, Any]:
    last_run = row.get("last_run") or {}
    failure_type = last_run.get("failure_type") or ""
    manual_reasons = row.get("manual_reasons") or []
    if not failure_type:
        if any("门店映射" in reason for reason in manual_reasons):
            failure_type = "store_mapping"
        elif any("安全上限" in reason or "预算" in reason for reason in manual_reasons):
            failure_type = "budget_guardrail"
        else:
            failure_type = "manual_review"
    guide = REPAIR_GUIDES.get(failure_type) or {
        "title": "推广预算人工复核向导",
        "checklist": [
            "核对门店、平台、时段、目标预算和最近执行日志。",
            "确认不是登录、权限、页面结构、门店映射或预算安全问题。",
            "需要真实提交前先生成预算预览并保留执行日志。",
        ],
    }
    checklist = list(guide["checklist"])
    if row.get("next_action") and row["next_action"] not in checklist:
        checklist.append(row["next_action"])
    return {
        "id": f"{failure_type}.{row.get('platform')}.{row.get('period')}.{row.get('store')}",
        "title": guide["title"],
        "priority": "high" if failure_type in MANUAL_FAILURE_TYPES or manual_reasons else "medium",
        "platform": row.get("platform", ""),
        "store": row.get("store", ""),
        "period": row.get("period", ""),
        "target_budget": row.get("target_budget", 0),
        "failure_type": failure_type,
        "manual_reasons": manual_reasons,
        "checklist": checklist,
        "rerun_scope": "仅对应平台和时段",
        "evidence": "outputs/promo_budget_retry_plan/latest.json",
    }


def build_repair_guides(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = [
        row
        for row in rows
        if row.get("manual_reasons") or (row.get("last_run") or {}).get("status") == "failed"
    ]
    guides = [repair_guide_for(row) for row in candidates[:12]]
    return sorted(guides, key=lambda item: (0 if item["priority"] == "high" else 1, item["platform"], item["period"], item["store"]))


def repair_templates() -> list[dict[str, Any]]:
    labels = {
        "auth_block": "平台登录/验证码",
        "permission": "Mac mini 系统权限",
        "budget_guardrail": "预算安全上限",
        "page_structure": "平台预算页改版",
        "store_mapping": "门店映射异常",
        "manual_browser_setup": "浏览器后台准备",
        "timeout": "网络或页面超时",
        "execution_failed": "普通执行失败",
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


def build_payload() -> dict[str, Any]:
    preview = read_json(PREVIEW_PATH, {})
    overrides = read_json(OVERRIDES_PATH, {"stores": {}})
    run_state = read_json(TASK_RUNS_PATH, {"tasks": {}})
    latest_run = latest_budget_run(run_state)
    items = normalized_items(preview)
    retry_rows = [retry_policy_for(item, overrides, latest_run) for item in items]
    repair_guides = build_repair_guides(retry_rows)
    safe_count = sum(1 for item in retry_rows if item["safe_to_retry"])
    manual_count = len(retry_rows) - safe_count
    affected_count = sum(1 for item in retry_rows if item.get("last_run", {}).get("scope"))
    return {
        "generated_at": now_text(),
        "status": "ready" if preview else "missing_preview",
        "source": {
            "preview": "outputs/promo_budget_preview/latest.json",
            "overrides": "config/promo_budget_overrides.json",
        },
        "summary": {
            "item_count": len(retry_rows),
            "safe_retry_count": safe_count,
            "manual_count": manual_count,
            "affected_by_latest_run_count": affected_count,
            "repair_guide_count": len(repair_guides),
            "platforms": sorted({item["platform"] for item in retry_rows if item.get("platform")}),
        },
        "repair_guides": repair_guides,
        "repair_templates": repair_templates(),
        "latest_run": {
            "status": latest_run.get("status", ""),
            "step": latest_run.get("step", ""),
            "failure_type": latest_run.get("failure_type", ""),
            "message": latest_run.get("message", ""),
            "updated_at": latest_run.get("updated_at", ""),
        },
        "global_policy": {
            "auto_retry_allowed_failure_types": sorted(SAFE_RETRY_FAILURE_TYPES),
            "manual_failure_types": sorted(MANUAL_FAILURE_TYPES),
            "stop_after_first_save_attempt": True,
            "require_post_save_verification": True,
            "never_retry_when": [
                "登录/验证码/权限问题",
                "预算超过门店安全上限",
                "页面结构或门店映射不确定",
                "平台提示风险设置或自动提预算",
            ],
        },
        "items": retry_rows,
        "message": f"推广预算门店级安全重试策略已生成：{safe_count} 项可安全重试，{manual_count} 项需人工处理。"
        if preview
        else "推广预算预览尚未生成，无法生成门店级重试策略。",
    }


def main() -> int:
    payload = build_payload()
    write_latest(payload)
    print(payload["message"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
