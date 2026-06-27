from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "config" / "promo_budget_overrides.json"
URL = os.environ.get("PROMO_BUDGET_OVERRIDES_URL", "http://139.155.148.169/api/promo-budget-overrides?token=xiongxiaoxiao-order")
COPY_PATH = os.environ.get("PROMO_BUDGET_OVERRIDES_COPY_PATH", "").strip()
AUTH_USERNAME = os.environ.get("PROMO_BUDGET_AUTH_USERNAME", os.environ.get("OPERATION_AUTH_USERNAME", "summer"))
AUTH_PASSWORD = os.environ.get("PROMO_BUDGET_AUTH_PASSWORD", os.environ.get("INVENTORY_PASSWORD", ""))
SSH_SOURCE = os.environ.get("PROMO_BUDGET_OVERRIDES_SSH_SOURCE", "").strip()


def canonical_store_name(name: str) -> str:
    return "丽泽门店" if any(token in str(name) for token in ("第13档口", "熙悦", "丽泽")) else str(name)


def normalize_store_names(data: dict) -> dict:
    stores = data.get("stores")
    if not isinstance(stores, dict):
        return data
    normalized: dict[str, dict] = {}
    for store, config in stores.items():
        key = canonical_store_name(store)
        merged = normalized.setdefault(key, {})
        if isinstance(config, dict):
            merged.update(config)
    return {**data, "stores": normalized}


def merge_missing_defaults(data: dict, defaults: dict) -> dict:
    merged = dict(data)
    if "weekendPreset" not in merged and isinstance(defaults.get("weekendPreset"), dict):
        merged["weekendPreset"] = defaults["weekendPreset"]
    for key in ["chinaHolidays", "chinaAdjustedWorkdays"]:
        if key not in merged and isinstance(defaults.get(key), dict):
            merged[key] = defaults[key]

    stores = merged.setdefault("stores", {})
    default_stores = defaults.get("stores") if isinstance(defaults.get("stores"), dict) else {}
    if not isinstance(stores, dict):
        merged["stores"] = {}
        stores = merged["stores"]
    for store, default_config in default_stores.items():
        if not isinstance(default_config, dict):
            continue
        store_config = stores.setdefault(store, {})
        if not isinstance(store_config, dict):
            stores[store] = {}
            store_config = stores[store]
        for platform, platform_defaults in default_config.items():
            if not isinstance(platform_defaults, dict):
                continue
            platform_config = store_config.setdefault(platform, {})
            if not isinstance(platform_config, dict):
                store_config[platform] = {}
                platform_config = store_config[platform]
            for field in ["weekendLunchBudget", "weekendDinnerBudget"]:
                if field not in platform_config and field in platform_defaults:
                    platform_config[field] = platform_defaults[field]
    return merged


def read_remote_http() -> dict:
    request = Request(URL, headers={"Accept": "application/json"})
    if AUTH_PASSWORD:
        import base64

        token = base64.b64encode(f"{AUTH_USERNAME}:{AUTH_PASSWORD}".encode("utf-8")).decode("ascii")
        request.add_header("Authorization", f"Basic {token}")
    with urlopen(request, timeout=10) as response:
        status = getattr(response, "status", 200)
        raw = response.read()
        content_type = response.headers.get("Content-Type", "")
    if status >= 400:
        raise RuntimeError(f"HTTP {status}")
    body = raw.decode("utf-8", errors="replace").strip()
    if not body:
        raise RuntimeError("云端返回空内容")
    if "json" not in content_type.lower() and not body.startswith(("{", "[")):
        preview = body[:120].replace("\n", " ")
        raise RuntimeError(f"云端返回非 JSON 内容：Content-Type={content_type or 'unknown'}，片段={preview!r}")
    data = json.loads(body)
    if not isinstance(data, dict):
        raise RuntimeError(f"云端 JSON 顶层不是对象：{type(data).__name__}")
    return data


def read_remote_ssh() -> dict:
    if not SSH_SOURCE:
        raise RuntimeError("未配置 PROMO_BUDGET_OVERRIDES_SSH_SOURCE")
    if ":" not in SSH_SOURCE:
        raise RuntimeError(f"SSH 来源格式错误：{SSH_SOURCE}")
    host, path = SSH_SOURCE.split(":", 1)
    result = subprocess.run(
        ["ssh", "-o", "ConnectTimeout=8", host, "cat", path],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    data = json.loads(result.stdout)
    if not isinstance(data, dict):
        raise RuntimeError(f"SSH JSON 顶层不是对象：{type(data).__name__}")
    return data


def main() -> int:
    try:
        defaults = normalize_store_names(json.loads(TARGET.read_text(encoding="utf-8")))
    except Exception:
        defaults = {"stores": {}}
    try:
        data = read_remote_http()
    except Exception as exc:
        if isinstance(exc, HTTPError):
            reason = f"HTTP {exc.code} {exc.reason}"
        elif isinstance(exc, URLError):
            reason = f"网络错误 {exc.reason}"
        else:
            reason = str(exc)
        try:
            data = read_remote_ssh()
            print(f"HTTP 预算配置读取失败，已改用 SSH 只读同步：{reason}")
        except Exception as ssh_exc:
            print(f"云端预算配置读取失败，继续使用本地最后可用配置：{reason}；SSH 兜底失败：{ssh_exc}")
            return 0
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    data = merge_missing_defaults(normalize_store_names(data), defaults)
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    TARGET.write_text(text, encoding="utf-8")
    if COPY_PATH:
        copy_target = Path(COPY_PATH)
        copy_target.parent.mkdir(parents=True, exist_ok=True)
        copy_target.write_text(text, encoding="utf-8")
    print(f"已同步云端预算配置：{TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
