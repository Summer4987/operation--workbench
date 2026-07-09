from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from atomic_io import atomic_write_text


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "agent_system_check"
LATEST_PATH = OUTPUT_DIR / "latest.json"
DEFAULT_CLOUD_BASE = "http://139.155.148.169/operation-workbench"
DEFAULT_AGENT_BASE = "http://139.155.148.169"


def now_text() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def load_agent_token() -> str:
    token = os.environ.get("AGENT_INBOX_TOKEN", "").strip()
    if token:
        return token
    private_json = ROOT / "config" / "agent_private.json"
    if private_json.exists():
        value = str(read_json(private_json).get("agent_inbox_token") or "").strip()
        if value:
            return value
    env_file = Path.home() / ".xiong-agent-env"
    for line in read_text(env_file).splitlines():
        if line.startswith("AGENT_INBOX_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def run(command: list[str], timeout: int = 20) -> dict[str, Any]:
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
        return {"ok": result.returncode == 0, "returncode": result.returncode, "output": (result.stdout or "").strip()}
    except Exception as exc:
        return {"ok": False, "returncode": 1, "output": str(exc)}


def http_text(url: str, timeout: int = 8) -> tuple[bool, str]:
    try:
        with urlopen(url, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return 200 <= response.status < 400, body
    except HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = str(exc)
        return False, f"HTTP {exc.code}: {body}"
    except (URLError, OSError, TimeoutError) as exc:
        return False, str(exc)
    except Exception as exc:
        return False, str(exc)


def cloud_contains_check(name: str, url: str, store: str) -> dict[str, Any]:
    ok, body = http_text(url)
    if ok and store in body:
        return item(name, True, "云端可访问且含门店")
    if ok and ("业务中心登录" in body or "需要登录" in body or "<title>熊小小业务中心登录</title>" in body):
        return item(name, False, "云端需要登录，公开 HTTP 无法直接验内容；以发布校验和服务端文件为准", severity="should")
    return item(name, False, f"云端未确认：{body[:120]}", severity="should")


def cloud_reachable_check(name: str, url: str) -> dict[str, Any]:
    ok, body = http_text(url)
    if ok and len(body) > 20:
        return item(name, True, "可访问")
    if "HTTP 401" in body or "业务中心登录" in body or "需要登录" in body:
        return item(name, True, "受登录保护，服务可达")
    return item(name, False, body[:160], severity="should")


def item(name: str, ok: bool, detail: str, *, severity: str = "must") -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "detail": detail, "severity": severity}


def contains_json_row(payload: dict[str, Any], store: str) -> bool:
    needle = store.strip()
    if not needle:
        return False
    return needle in json.dumps(payload, ensure_ascii=False)


def feature_acceptance(store: str, *, cloud_base: str, agent_base: str, token: str) -> dict[str, Any]:
    store = store.strip() or "望京"
    realtime = read_json(ROOT / "outputs" / "realtime_order_income" / "latest.json")
    daily = read_json(ROOT / "business-report-dashboard" / "data" / "latest.json")
    preview = read_json(ROOT / "outputs" / "promo_budget_preview" / "latest.json")
    balance = read_json(ROOT / "store-inspection" / "latest.json")
    spend = read_json(ROOT / "outputs" / "meituan_promo_spend" / "latest.json")

    checks: list[dict[str, Any]] = []
    realtime_hits = [row for row in realtime.get("items", []) if isinstance(row, dict) and row.get("store") == store]
    checks.append(item("加盟店实时采集", bool(realtime_hits), f"{len(realtime_hits)} 条平台记录；平台门店数 {(realtime.get('summary') or {}).get('platform_store_count', '-')}"))

    daily_stores = [row.get("store") for row in daily.get("store_summary", []) if isinstance(row, dict)]
    checks.append(item("加盟商日报看板", store in daily_stores, f"当前日报门店 {len(daily_stores)} 家；{'已包含' if store in daily_stores else '未包含'}{store}"))

    preview_keys = ["eleme_lunch", "eleme_dinner", "meituan_lunch", "meituan_dinner"]
    preview_hits = {
        key: any(store in json.dumps(row, ensure_ascii=False) for row in preview.get(key, []) if isinstance(row, dict))
        for key in preview_keys
    }
    checks.append(item("推广预算设置", all(preview_hits.values()), "；".join(f"{key}={'OK' if ok else 'MISS'}" for key, ok in preview_hits.items())))

    checks.append(item("推广余额巡检", contains_json_row(balance, store), "余额巡检 latest " + ("已包含门店" if contains_json_row(balance, store) else "未包含门店")))
    checks.append(item("美团消耗/余量巡检", contains_json_row(spend, store), "美团消耗 latest " + ("已包含门店" if contains_json_row(spend, store) else "未包含门店"), severity="should"))

    cloud_checks = [
        ("云端实时 latest", f"{cloud_base}/outputs/realtime_order_income/latest.json"),
        ("云端预算预览", f"{cloud_base}/outputs/promo_budget_preview/latest.json"),
        ("云端加盟日报", f"{cloud_base}/business-report-dashboard/data/latest.json"),
        ("云端余额巡检", f"{cloud_base}/store-inspection/latest.json"),
        ("云端工作台数据", f"{cloud_base}/workbench-data.js"),
    ]
    for name, url in cloud_checks:
        checks.append(cloud_contains_check(name, url, store))

    if token:
        agent_ok, agent_body = http_text(f"{agent_base}/agent/api/status?token={token}&limit=1")
        checks.append(item("Agent 手机入口 API", agent_ok and store in agent_body, "Agent API 已返回门店" if agent_ok and store in agent_body else f"Agent API 未确认：{agent_body[:120]}"))
    else:
        checks.append(item("Agent 手机入口 API", False, "未配置 AGENT_INBOX_TOKEN，跳过 API 内容校验", severity="should"))

    return build_result("feature_acceptance", checks, store=store)


def system_check(*, cloud_base: str, agent_base: str, token: str) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    git_head = run(["git", "rev-parse", "--short", "HEAD"])
    git_origin = run(["git", "rev-parse", "--short", "origin/main"])
    same_head = git_head.get("ok") and git_origin.get("ok") and git_head.get("output") == git_origin.get("output")
    checks.append(item("GitHub main 部署版本", same_head, f"HEAD={git_head.get('output') or '-'}；origin/main={git_origin.get('output') or '-'}"))

    for label, path in [
        ("实时采集产物", ROOT / "outputs" / "realtime_order_income" / "latest.json"),
        ("加盟日报产物", ROOT / "business-report-dashboard" / "data" / "latest.json"),
        ("预算预览产物", ROOT / "outputs" / "promo_budget_preview" / "latest.json"),
        ("余额巡检产物", ROOT / "store-inspection" / "latest.json"),
        ("Agent 手机入口产物", ROOT / "outputs" / "agent_mobile" / "latest.json"),
    ]:
        checks.append(item(label, path.exists(), str(path.relative_to(ROOT)) if path.exists() else "文件不存在"))

    plist_dir = Path.home() / "Library" / "LaunchAgents"
    launchd_names = ["com.summer.operation.realtime-order-income.plist", "com.summer.operation.morning.plist"]
    for name in launchd_names:
        checks.append(item(f"Mac mini 定时任务 {name}", (plist_dir / name).exists(), str(plist_dir / name), severity="should"))

    cloud_targets = [
        ("云端工作台", f"{cloud_base}/workbench-data.js"),
        ("云端实时 latest", f"{cloud_base}/outputs/realtime_order_income/latest.json"),
        ("云端预算预览", f"{cloud_base}/outputs/promo_budget_preview/latest.json"),
        ("云端 Agent 数据", f"{cloud_base}/outputs/agent_mobile/latest.json"),
    ]
    for label, url in cloud_targets:
        checks.append(cloud_reachable_check(label, url))

    if token:
        agent_ok, agent_body = http_text(f"{agent_base}/agent/api/status?token={token}&limit=1")
        checks.append(item("Agent 队列/API", agent_ok and "summary" in agent_body, "API 正常" if agent_ok else agent_body[:160]))
    else:
        checks.append(item("Agent 队列/API", False, "未配置 AGENT_INBOX_TOKEN，跳过 API 内容校验", severity="should"))
    return build_result("system_check", checks)


def build_result(kind: str, checks: list[dict[str, Any]], *, store: str = "") -> dict[str, Any]:
    failed = [row for row in checks if not row.get("ok") and row.get("severity") == "must"]
    warnings = [row for row in checks if not row.get("ok") and row.get("severity") != "must"]
    status = "ok" if not failed and not warnings else "warning" if not failed else "failed"
    return {
        "generated_at": now_text(),
        "kind": kind,
        "store": store,
        "status": status,
        "summary": {
            "total": len(checks),
            "ok": len([row for row in checks if row.get("ok")]),
            "failed": len(failed),
            "warnings": len(warnings),
        },
        "checks": checks,
        "message": format_message(kind, status, checks, store=store),
    }


def format_message(kind: str, status: str, checks: list[dict[str, Any]], *, store: str = "") -> str:
    title = "系统自检" if kind == "system_check" else f"{store} 功能验收"
    status_text = {"ok": "通过", "warning": "部分通过", "failed": "未通过"}.get(status, status)
    lines = [f"{title}：{status_text}。"]
    for index, row in enumerate(checks, start=1):
        mark = "OK" if row.get("ok") else "MISS"
        lines.append(f"{index}. {mark} {row.get('name')}：{row.get('detail')}")
    return "\n".join(lines)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Agent 系统自检和功能验收。")
    parser.add_argument("--mode", choices=["system", "feature"], default="system")
    parser.add_argument("--store", default="望京")
    parser.add_argument("--cloud-base", default=os.environ.get("OPERATION_CLOUD_PUBLIC_URL", DEFAULT_CLOUD_BASE).rstrip("/"))
    parser.add_argument("--agent-base", default=os.environ.get("AGENT_PUBLIC_BASE_URL", DEFAULT_AGENT_BASE).rstrip("/"))
    parser.add_argument("--token", default=load_agent_token())
    parser.add_argument("--output", default=str(LATEST_PATH))
    args = parser.parse_args()

    payload = (
        feature_acceptance(args.store, cloud_base=args.cloud_base, agent_base=args.agent_base, token=args.token)
        if args.mode == "feature"
        else system_check(cloud_base=args.cloud_base, agent_base=args.agent_base, token=args.token)
    )
    write_json(Path(args.output).expanduser(), payload)
    print(payload["message"])
    return 0 if payload["status"] != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
