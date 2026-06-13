from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PREVIEW_PATH = ROOT / "outputs" / "promo_budget_preview" / "latest.json"
OVERRIDES_PATH = ROOT / "config" / "promo_budget_overrides.json"
OUTPUT_DIR = ROOT / "outputs" / "promo_budget_retry_plan"
LATEST_PATH = OUTPUT_DIR / "latest.json"

SAFE_RETRY_FAILURE_TYPES = {
    "timeout",
    "execution_failed",
}

MANUAL_FAILURE_TYPES = {
    "auth_block",
    "permission",
    "budget_guardrail",
    "page_structure",
    "store_mapping",
    "manual_browser_setup",
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


def retry_policy_for(item: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
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
        "next_action": "仅限超时或普通执行失败时重试；登录、权限、页面结构、预算安全和门店映射问题必须人工处理。"
        if safe_to_retry and not manual_reasons
        else "进入人工处理，不自动重试。",
    }


def build_payload() -> dict[str, Any]:
    preview = read_json(PREVIEW_PATH, {})
    overrides = read_json(OVERRIDES_PATH, {"stores": {}})
    items = normalized_items(preview)
    retry_rows = [retry_policy_for(item, overrides) for item in items]
    safe_count = sum(1 for item in retry_rows if item["safe_to_retry"])
    manual_count = len(retry_rows) - safe_count
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
            "platforms": sorted({item["platform"] for item in retry_rows if item.get("platform")}),
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
