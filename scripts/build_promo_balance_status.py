from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from task_run_state import classify_failure_text


ROOT = Path(__file__).resolve().parents[1]
BALANCE_PATH = ROOT / "store-inspection" / "latest.json"
OUTPUT_DIR = ROOT / "outputs" / "promo_balance_status"
LATEST_PATH = OUTPUT_DIR / "latest.json"

PLATFORMS = ("饿了么", "美团")


def read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def normalize_failure_type(message: str) -> str:
    if "屏幕录制" in message or "could not create image from display" in message:
        return "permission"
    return classify_failure_text(message)


def human_action_for(failure_type: str, message: str) -> str:
    if failure_type == "permission":
        return "在 Mac mini 系统设置里给 Terminal/Codex 开启屏幕录制权限，然后重跑推广余额巡检。"
    if failure_type == "auth_block":
        return "先人工恢复平台登录或验证码，再重跑推广余额巡检。"
    if failure_type == "manual_browser_setup":
        return "先在本机浏览器打开对应平台推广页面，再重跑推广余额巡检。"
    if failure_type == "page_structure":
        return "平台页面结构疑似变化，先人工核对页面，再调整余额识别脚本。"
    if "余额识别失败" in message:
        return "先打开余额巡检截图和 OCR 结果，确认余额区域是否发生变化。"
    return "先查看推广余额巡检日志，确认平台登录、权限、页面结构和截图是否正常。"


def split_platform_failures(message: str) -> list[dict]:
    failures: list[dict] = []
    for raw_part in str(message or "").split("；"):
        part = raw_part.strip()
        if not part:
            continue
        platform = ""
        detail = part
        if "：" in part:
            platform, detail = part.split("：", 1)
            platform = platform.strip()
            detail = detail.strip()
        if platform not in PLATFORMS:
            platform = platform or "未知平台"
        failure_type = normalize_failure_type(detail)
        failures.append(
            {
                "platform": platform,
                "status": "failed",
                "message": detail,
                "failure_type": failure_type,
                "human_action": human_action_for(failure_type, detail),
            }
        )
    return failures


def low_balance_items(payload: dict) -> list[dict]:
    threshold = float(payload.get("threshold") or 100)
    warnings: list[dict] = []
    for item in payload.get("items") or []:
        balance = float(item.get("balance") or 0)
        if item.get("status") == "warning" or balance <= threshold:
            warnings.append(
                {
                    "platform": item.get("platform", ""),
                    "store_name": item.get("store_name") or item.get("store") or "",
                    "balance": balance,
                    "threshold": threshold,
                    "status": "warning",
                    "message": item.get("message") or "推广余额低于预警阈值。",
                    "human_action": "先充值低余额门店，再执行预算或出价自动化。",
                }
            )
    return warnings


def platform_rows(payload: dict, failures: list[dict]) -> list[dict]:
    by_platform = {item["platform"]: item for item in failures}
    rows = []
    for platform in PLATFORMS:
        rows.append(
            by_platform.get(
                platform,
                {
                    "platform": platform,
                    "status": "ok",
                    "message": "余额巡检未报告平台级失败。",
                    "failure_type": "",
                    "human_action": "",
                },
            )
        )
    extra = [item for item in failures if item["platform"] not in PLATFORMS]
    return rows + extra


def build_status(payload: dict) -> dict:
    generated_at = payload.get("generated_at") or ""
    summary = payload.get("summary") or {}
    failures = split_platform_failures(payload.get("message") or "") if payload.get("status") == "failed" else []
    warnings = low_balance_items(payload)
    platform_failure_count = len(failures)
    low_balance_count = len(warnings)
    store_count = int(summary.get("store_count") or len(payload.get("items") or []))
    threshold = float(payload.get("threshold") or 100)

    if not payload:
        status = "missing"
        message = "推广余额巡检尚未生成。"
    elif platform_failure_count and not store_count:
        status = "failed"
        message = f"推广余额巡检失败：{platform_failure_count} 个平台需要人工处理。"
    elif platform_failure_count or low_balance_count:
        status = "warning"
        parts = []
        if platform_failure_count:
            parts.append(f"{platform_failure_count} 个平台巡检失败")
        if low_balance_count:
            parts.append(f"{low_balance_count} 个低余额预警")
        message = "，".join(parts) + "。"
    else:
        status = "ok"
        message = f"推广余额巡检正常，{store_count} 条余额结果。"

    human_action = ""
    if failures:
        human_action = failures[0].get("human_action", "")
    elif warnings:
        human_action = "先充值低余额门店，再执行预算或出价自动化。"

    return {
        "generated_at": now_text(),
        "source_generated_at": generated_at,
        "source": "store-inspection/latest.json",
        "status": status,
        "message": message,
        "human_action": human_action,
        "summary": {
            "platform_failure_count": platform_failure_count,
            "low_balance_count": low_balance_count,
            "store_count": store_count,
            "platform_count": int(summary.get("platform_count") or 0),
            "warning_threshold": threshold,
            "lowest_balance": float(summary.get("lowest_balance") or 0),
        },
        "platforms": platform_rows(payload, failures),
        "low_balance_items": warnings,
    }


def main() -> None:
    payload = read_json(BALANCE_PATH, {})
    status = build_status(payload)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LATEST_PATH.chmod(0o644)
    print(f"推广余额状态已更新：{LATEST_PATH}")


if __name__ == "__main__":
    main()
