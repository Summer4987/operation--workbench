from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from task_run_state import classify_failure_text


ROOT = Path(__file__).resolve().parents[1]
STORE_INSPECTION_DIR = ROOT / "store-inspection"
if str(STORE_INSPECTION_DIR) not in sys.path:
    sys.path.insert(0, str(STORE_INSPECTION_DIR))

from balance_coverage import DIRECT_ELEME_STORES, aliases_for_direct_store, build_direct_coverage, item_matches_store  # noqa: E402

BALANCE_PATH = ROOT / "store-inspection" / "latest.json"
OUTPUT_DIR = ROOT / "outputs" / "promo_balance_status"
LATEST_PATH = OUTPUT_DIR / "latest.json"
EVIDENCE_DIR = ROOT / "outputs" / "store_inspection"
EVIDENCE_MANIFEST_PATH = ROOT / "outputs" / "store_inspection_evidence_manifest" / "latest.json"

PLATFORMS = ("饿了么", "美团")
FRESHNESS_WINDOW = timedelta(minutes=90)
PLATFORM_TOKENS = {
    "饿了么": ("eleme", "饿了么"),
    "美团": ("meituan", "美团"),
}
EVIDENCE_SUFFIXES = {".png", ".jpg", ".jpeg", ".json"}

RECOVERY_GUIDES = {
    "permission": {
        "title": "系统权限未开启",
        "severity": "blocked",
        "owner_environment": "Mac mini 生产环境",
        "steps": [
            "在 Mac mini 打开系统设置 > 隐私与安全性 > 屏幕录制。",
            "给 Terminal、Codex 或实际运行巡检脚本的终端应用开启屏幕录制权限。",
            "完全退出并重新打开终端应用后，重跑推广余额巡检。",
        ],
        "verify_command": "python3 store-inspection/run_all_balances.py",
        "evidence": "store-inspection/latest.json",
    },
    "auth_block": {
        "title": "平台登录或验证码阻塞",
        "severity": "blocked",
        "owner_environment": "Mac mini 生产环境",
        "steps": [
            "在 Mac mini 的日常 Chrome 打开对应平台推广余额页面。",
            "人工完成登录、验证码或账号安全确认。",
            "确认页面能看到余额后，重跑推广余额巡检。",
        ],
        "verify_command": "python3 store-inspection/run_all_balances.py",
        "evidence": "store-inspection/latest.json",
    },
    "manual_browser_setup": {
        "title": "浏览器页面未准备",
        "severity": "manual_setup",
        "owner_environment": "Mac mini 生产环境",
        "steps": [
            "先在日常 Chrome 打开对应平台推广余额页面。",
            "确认浏览器允许脚本读取当前页面和截图。",
            "页面稳定后重跑推广余额巡检。",
        ],
        "verify_command": "python3 store-inspection/run_all_balances.py",
        "evidence": "store-inspection/latest.json",
    },
    "page_structure": {
        "title": "平台页面结构变化",
        "severity": "script_update",
        "owner_environment": "MacBook 开发，Mac mini 验证",
        "steps": [
            "在 Mac mini 保存失败截图、OCR 文本和当前页面状态。",
            "在 MacBook 调整余额识别脚本或选择器。",
            "提交推送后，由 Mac mini 拉取并重跑巡检。",
        ],
        "verify_command": "python3 store-inspection/run_all_balances.py",
        "evidence": "store-inspection/logs/",
    },
    "execution_failed": {
        "title": "巡检执行失败",
        "severity": "check_logs",
        "owner_environment": "Mac mini 生产环境",
        "steps": [
            "先查看推广余额巡检日志和最新截图。",
            "确认平台登录、系统权限、页面结构和 OCR 是否正常。",
            "按具体失败类型处理后重跑巡检。",
        ],
        "verify_command": "python3 store-inspection/run_all_balances.py",
        "evidence": "store-inspection/latest.json",
    },
}


def read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    return None


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


def recovery_for(platform: str, failure_type: str, message: str) -> dict[str, Any]:
    guide = RECOVERY_GUIDES.get(failure_type) or RECOVERY_GUIDES["execution_failed"]
    steps = list(guide["steps"])
    return {
        "title": guide["title"],
        "severity": guide["severity"],
        "owner_environment": guide["owner_environment"],
        "steps": steps,
        "verify_command": guide["verify_command"],
        "evidence": guide["evidence"],
        "summary": f"{platform}：{guide['title']}。{human_action_for(failure_type, message)}",
    }


def evidence_kind(path: Path) -> str:
    name = path.name.lower()
    if name.endswith(".ocr.json"):
        return "ocr"
    if path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
        return "screenshot"
    return "data"


def collect_evidence(platform: str, limit: int = 6) -> list[dict[str, Any]]:
    if not EVIDENCE_DIR.exists():
        return []
    tokens = PLATFORM_TOKENS.get(platform, (platform,))
    candidates = []
    for path in EVIDENCE_DIR.glob("*"):
        if not path.is_file() or path.suffix.lower() not in EVIDENCE_SUFFIXES:
            continue
        name = path.name.lower()
        if not any(str(token).lower() in name for token in tokens):
            continue
        if path.name.endswith(".ocr 2.json"):
            continue
        candidates.append(path)
    newest = sorted(candidates, key=lambda item: item.stat().st_mtime, reverse=True)[:limit]
    return [
        {
            "path": str(path.relative_to(ROOT)),
            "kind": evidence_kind(path),
            "updated_at": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "size": path.stat().st_size,
        }
        for path in newest
    ]


def evidence_sync_status() -> dict[str, Any]:
    manifest = read_json(EVIDENCE_MANIFEST_PATH, {})
    if not manifest:
        return {
            "status": "missing_manifest",
            "manifest": "outputs/store_inspection_evidence_manifest/latest.json",
            "upload_command": "scripts/upload_store_inspection_evidence.zsh --dry-run",
            "message": "巡检证据清单尚未生成，先运行 dry-run 检查可上传证据。",
        }
    summary = manifest.get("summary") or {}
    retention = manifest.get("retention") or {}
    return {
        "status": manifest.get("status") or "unknown",
        "manifest": "outputs/store_inspection_evidence_manifest/latest.json",
        "file_count": int(summary.get("file_count") or 0),
        "cloud_retention_days": int(retention.get("cloud_days") or 0),
        "local_retention_days": int(retention.get("local_days") or 0),
        "upload_command": "scripts/upload_store_inspection_evidence.zsh --dry-run",
        "message": manifest.get("message") or "巡检证据清单已生成。",
    }


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
                "recovery": recovery_for(platform, failure_type, detail),
                "evidence": collect_evidence(platform),
            }
        )
    return failures


def is_direct_meituan_item(item: dict) -> bool:
    return any(
        item_matches_store(item, "美团", aliases_for_direct_store("meituan", store))
        for store in DIRECT_ELEME_STORES
    )


def balance_items(payload: dict) -> list[dict]:
    return [item for item in payload.get("items") or [] if not is_direct_meituan_item(item)]


def is_unconfirmed_zero_balance(item: dict) -> bool:
    try:
        balance = float(item.get("balance"))
    except (TypeError, ValueError):
        return False
    if balance != 0:
        return False
    if item.get("confirmed_zero") is True:
        return False
    if item.get("api_seen") is True or item.get("account_response_url"):
        return False
    source = str(item.get("source") or "")
    if "接口读取" in source:
        return False
    return True


def unconfirmed_balance_items(payload: dict) -> list[dict]:
    items = []
    threshold = float(payload.get("threshold") or 100)
    for item in balance_items(payload):
        if not is_unconfirmed_zero_balance(item):
            continue
        items.append(
            {
                "platform": item.get("platform", ""),
                "store_name": item.get("store_name") or item.get("store") or "",
                "balance": item.get("balance"),
                "threshold": threshold,
                "status": "unconfirmed",
                "source": item.get("source") or "",
                "message": "页面文本读到 0 元，但接口没有确认余额，需重跑巡检或人工复核。",
                "human_action": "先重跑推广余额巡检；若仍未确认，再人工打开平台余额页核对。",
            }
        )
    return items


def low_balance_items(payload: dict) -> list[dict]:
    threshold = float(payload.get("threshold") or 100)
    warnings: list[dict] = []
    for item in balance_items(payload):
        if is_unconfirmed_zero_balance(item):
            continue
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


def direct_coverage_rows(payload: dict) -> list[dict]:
    coverage = build_direct_coverage(balance_items(payload))
    rows = []
    for scope in coverage.get("scopes") or []:
        if not scope.get("missing_count"):
            continue
        rows.append(
            {
                "platform": scope.get("platform", ""),
                "scope": scope.get("label", ""),
                "missing_stores": scope.get("missing_stores") or [],
                "message": f"{scope.get('label', '')}缺少余额结果：{', '.join(scope.get('missing_stores') or [])}",
                "human_action": "先确认这些门店是否已在平台账号里展示；若账号正常，重跑余额巡检并查看平台接口是否分页或筛选。",
            }
        )
    return rows


def recharge_plan(warnings: list[dict]) -> dict:
    items = []
    for item in sorted(warnings, key=lambda row: float(row.get("balance") or 0)):
        threshold = float(item.get("threshold") or 0)
        balance = float(item.get("balance") or 0)
        items.append(
            {
                "platform": item.get("platform", ""),
                "store_name": item.get("store_name", ""),
                "balance": balance,
                "threshold": threshold,
                "gap_to_threshold": max(0, threshold - balance),
                "action": f"给{item.get('platform', '')} {item.get('store_name', '')}充值，当前余额 {balance:.2f} 元，低于阈值 {threshold:.2f} 元。",
            }
        )
    top_items = items[:6]
    next_action = "；".join(item["action"] for item in top_items)
    return {
        "status": "waiting_recharge" if items else "clear",
        "item_count": len(items),
        "top_items": top_items,
        "next_action": next_action or "当前没有低余额充值项。",
        "message": f"当前 {len(items)} 个推广余额需要充值，先处理最低余额门店。"
        if items
        else "当前没有低余额充值项。",
    }


def build_status(payload: dict) -> dict:
    generated_at = payload.get("generated_at") or ""
    source_time = parse_time(generated_at)
    now = datetime.now()
    is_stale = bool(source_time and now - source_time > FRESHNESS_WINDOW)
    summary = payload.get("summary") or {}
    failures = split_platform_failures(payload.get("message") or "") if payload.get("status") == "failed" else []
    items = balance_items(payload)
    direct_coverage = build_direct_coverage(items)
    coverage_rows = direct_coverage_rows(payload)
    warnings = [] if is_stale else low_balance_items(payload)
    unconfirmed_items = [] if is_stale else unconfirmed_balance_items(payload)
    platform_failure_count = len(failures)
    coverage_missing_count = sum(len(row.get("missing_stores") or []) for row in coverage_rows)
    low_balance_count = len(warnings)
    unconfirmed_count = len(unconfirmed_items)
    store_count = len(items)
    threshold = float(payload.get("threshold") or 100)
    platform_count = len({item.get("platform") for item in items if item.get("platform")})
    balances = [
        float(item.get("balance") or 0)
        for item in items
        if item.get("balance") is not None and not is_unconfirmed_zero_balance(item)
    ]
    lowest_balance = min(balances) if balances else 0

    if not payload:
        status = "missing"
        message = "推广余额巡检尚未生成。"
    elif is_stale:
        status = "stale"
        age_minutes = int((now - source_time).total_seconds() // 60) if source_time else 0
        message = f"推广余额结果已过期：{generated_at}，约 {age_minutes} 分钟前采集。旧余额没有当前商业价值，需重跑后再判断。"
    elif platform_failure_count and not store_count:
        status = "failed"
        message = f"推广余额巡检失败：{platform_failure_count} 个平台需要人工处理。"
    elif platform_failure_count or coverage_missing_count or low_balance_count or unconfirmed_count:
        status = "warning"
        parts = []
        if platform_failure_count:
            parts.append(f"{platform_failure_count} 个平台巡检失败")
        if coverage_missing_count:
            parts.append(f"{coverage_missing_count} 个直营门店缺少余额结果")
        if low_balance_count:
            parts.append(f"{low_balance_count} 个低余额预警")
        if unconfirmed_count:
            parts.append(f"{unconfirmed_count} 个余额未确认")
        message = "，".join(parts) + "。"
    else:
        status = "ok"
        message = f"推广余额巡检正常，{store_count} 条余额结果。"

    human_action = ""
    if failures:
        human_action = failures[0].get("human_action", "")
    elif is_stale:
        human_action = "先重跑推广余额巡检，再汇报低余额门店；不要引用旧余额数值。"
    elif coverage_rows:
        human_action = coverage_rows[0].get("human_action", "")
    elif warnings:
        human_action = "先充值低余额门店，再执行预算或出价自动化。"
    elif unconfirmed_items:
        human_action = "先重跑推广余额巡检；若仍未确认，再人工打开平台余额页核对。"

    platform_rows_payload = platform_rows(payload, failures)
    recharge = recharge_plan(warnings)
    evidence_items = [
        evidence
        for platform in platform_rows_payload
        for evidence in platform.get("evidence", [])
    ]

    return {
        "generated_at": now_text(),
        "source_generated_at": generated_at,
        "source": "store-inspection/latest.json",
        "status": status,
        "message": message,
        "human_action": human_action,
        "summary": {
            "platform_failure_count": platform_failure_count,
            "direct_coverage_missing_count": coverage_missing_count,
            "low_balance_count": low_balance_count,
            "balance_unconfirmed_count": unconfirmed_count,
            "store_count": store_count,
            "platform_count": platform_count,
            "warning_threshold": threshold,
            "lowest_balance": lowest_balance,
            "source_is_stale": is_stale,
            "freshness_window_minutes": int(FRESHNESS_WINDOW.total_seconds() // 60),
            "evidence_count": len(evidence_items),
        },
        "evidence_index": {
            "status": "ready" if evidence_items else "missing",
            "source_dir": "outputs/store_inspection",
            "items": evidence_items[:12],
            "message": f"已索引 {len(evidence_items)} 个巡检截图/OCR证据。"
            if evidence_items
            else "未找到可关联的平台巡检截图或 OCR 证据。",
        },
        "evidence_sync": evidence_sync_status(),
        "platforms": platform_rows_payload,
        "direct_coverage": direct_coverage,
        "direct_coverage_issues": coverage_rows,
        "low_balance_items": warnings,
        "unconfirmed_balance_items": unconfirmed_items,
        "recharge_plan": recharge,
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
