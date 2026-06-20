from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent
DIRECT_CONFIG_PATH = WORKSPACE / "business-report-dashboard" / "direct_config.json"
DIRECT_MEITUAN_CONFIG_PATH = WORKSPACE / "config" / "direct_meituan_accounts.json"

DIRECT_ELEME_STORES = ["朝阳门店", "银泰城店", "万象城店", "金融城店", "保利中心店"]
DIRECT_MEITUAN_CHAIN_STORES = ["保利中心店"]


def normalized(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).replace("（", "(").replace("）", ")")


def read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def aliases_for_direct_store(platform: str, store: str) -> list[str]:
    payload = read_json(DIRECT_CONFIG_PATH, {})
    aliases: list[str] = [store]
    for item in (payload.get("platform_aliases") or {}).get(platform, []):
        if item.get("short_name") != store:
            continue
        aliases.extend(str(alias) for alias in item.get("aliases") or [])
    if store == "朝阳门店":
        aliases.extend(["雅宝食堂美食城", "B2档口雅宝食堂美食城"])
    return list(dict.fromkeys(alias for alias in aliases if alias))


def expected_direct_scopes(platforms: set[str] | None = None) -> list[dict[str, Any]]:
    scopes: list[dict[str, Any]] = [
        {
            "id": "direct_eleme_chain",
            "platform": "饿了么",
            "label": "直营店饿了么总账号",
            "stores": [
                {"store": store, "aliases": aliases_for_direct_store("eleme", store)}
                for store in DIRECT_ELEME_STORES
            ],
        }
    ]
    if platforms is not None:
        scopes = [scope for scope in scopes if scope["platform"] in platforms]

    if platforms is not None and "美团" in platforms:
        scopes.append(
            {
                "id": "direct_meituan_chain",
                "platform": "美团",
                "label": "直营店美团总账号",
                "stores": [
                    {"store": store, "aliases": aliases_for_direct_store("meituan", store)}
                    for store in DIRECT_MEITUAN_CHAIN_STORES
                ],
            }
        )
        payload = read_json(DIRECT_MEITUAN_CONFIG_PATH, {})
        for account in payload.get("accounts") or []:
            if not account.get("enabled"):
                continue
            stores = []
            for store in account.get("stores") or []:
                stores.append({"store": store, "aliases": aliases_for_direct_store("meituan", store)})
            if stores:
                scopes.append(
                    {
                        "id": str(account.get("id") or ""),
                        "platform": "美团",
                        "label": str(account.get("name") or account.get("id") or "直营美团账号"),
                        "stores": stores,
                    }
                )
    return scopes


def item_matches_store(item: dict[str, Any], platform: str, aliases: list[str]) -> bool:
    if item.get("platform") != platform:
        return False
    haystack = normalized(" ".join(str(item.get(key, "")) for key in ["store_name", "store", "store_id"]))
    return any(normalized(alias) and normalized(alias) in haystack for alias in aliases)


def build_direct_coverage(items: list[dict[str, Any]], platforms: set[str] | None = None) -> dict[str, Any]:
    scopes = []
    missing_total = 0
    expected_total = 0
    covered_total = 0

    for scope in expected_direct_scopes(platforms):
        expected_items = []
        missing = []
        covered = []
        for store in scope["stores"]:
            expected_total += 1
            matched = next(
                (
                    item
                    for item in items
                    if item_matches_store(item, scope["platform"], store.get("aliases") or [store["store"]])
                ),
                None,
            )
            row = {
                "store": store["store"],
                "aliases": store.get("aliases") or [store["store"]],
                "matched": bool(matched),
                "matched_store_name": matched.get("store_name", "") if matched else "",
                "balance": matched.get("balance") if matched else None,
            }
            expected_items.append(row)
            if matched:
                covered.append(row)
                covered_total += 1
            else:
                missing.append(row)
                missing_total += 1
        scopes.append(
            {
                "id": scope["id"],
                "platform": scope["platform"],
                "label": scope["label"],
                "expected_count": len(expected_items),
                "covered_count": len(covered),
                "missing_count": len(missing),
                "missing_stores": [item["store"] for item in missing],
                "stores": expected_items,
            }
        )

    return {
        "status": "ok" if missing_total == 0 else "missing",
        "expected_count": expected_total,
        "covered_count": covered_total,
        "missing_count": missing_total,
        "scopes": scopes,
        "message": "直营店余额巡检覆盖完整。"
        if missing_total == 0
        else "直营店余额巡检缺少：" + "；".join(
            f"{scope['label']} {','.join(scope['missing_stores'])}"
            for scope in scopes
            if scope["missing_count"]
        ),
    }


def apply_direct_coverage(data: dict[str, Any], platforms: set[str] | None = None) -> dict[str, Any]:
    coverage = build_direct_coverage(data.get("items") or [], platforms)
    data["direct_coverage"] = coverage
    if coverage["missing_count"]:
        original_message = str(data.get("message") or "").strip()
        data["message"] = "；".join(part for part in [original_message, coverage["message"]] if part)
        if data.get("status") == "ok":
            data["status"] = "partial"
    return data
