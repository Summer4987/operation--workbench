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
    for path in [Path.home() / ".xiong-agent-env", ROOT / "config" / "ops_notify.json", ROOT / "config" / "agent_private.json"]:
        try:
            if path.suffix == ".json":
                value = str(read_json(path).get("agent_inbox_token") or "").strip()
                if value:
                    return value
                continue
            for raw in read_text(path).splitlines():
                line = raw.strip()
                if line.startswith("export "):
                    line = line[len("export ") :].strip()
                if line.startswith("AGENT_INBOX_TOKEN="):
                    return line.split("=", 1)[1].strip().strip("'\"")
        except Exception:
            continue
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


def feature_status_checks(*, agent_base: str, token: str) -> list[dict[str, Any]]:
    realtime = read_json(ROOT / "outputs" / "realtime_order_income" / "latest.json")
    daily = read_json(ROOT / "business-report-dashboard" / "data" / "latest.json")
    preview = read_json(ROOT / "outputs" / "promo_budget_preview" / "latest.json")
    balance = read_json(ROOT / "store-inspection" / "latest.json")
    spend = read_json(ROOT / "outputs" / "meituan_promo_spend" / "latest.json")
    agent_mobile = read_json(ROOT / "outputs" / "agent_mobile" / "latest.json")

    checks: list[dict[str, Any]] = []
    realtime_summary = realtime.get("summary") if isinstance(realtime.get("summary"), dict) else {}
    realtime_ok = int(realtime_summary.get("missing_count") or 0) == 0 and int(realtime_summary.get("platform_store_count") or 0) > 0
    checks.append(item("功能验收：加盟店实时采集", realtime_ok, f"平台门店 {realtime_summary.get('platform_store_count', 0)}；缺失 {realtime_summary.get('missing_count', 0)}"))

    daily_stores = [row.get("store") for row in daily.get("store_summary", []) if isinstance(row, dict)]
    checks.append(item("功能验收：加盟商日报看板", bool(daily_stores), f"日报门店 {len(daily_stores)} 家；日期 {daily.get('latest_date') or daily.get('report_date') or '-'}"))

    preview_keys = ["eleme_lunch", "eleme_dinner", "meituan_lunch", "meituan_dinner"]
    preview_hits = {key: bool(preview.get(key)) for key in preview_keys}
    checks.append(item("功能验收：推广预算设置", all(preview_hits.values()), "；".join(f"{key}={'OK' if ok else 'MISS'}" for key, ok in preview_hits.items())))

    balance_summary = balance.get("summary") if isinstance(balance.get("summary"), dict) else {}
    balance_ok = bool(balance) and not bool(balance_summary.get("source_is_stale"))
    checks.append(item("功能验收：推广余额巡检", balance_ok, f"门店 {balance_summary.get('store_count', 0)}；预警 {balance_summary.get('warning_count', balance_summary.get('low_balance_count', 0))}"))

    spend_summary = spend.get("summary") if isinstance(spend.get("summary"), dict) else {}
    spend_total = int(spend_summary.get("total_store_count") or spend_summary.get("store_count") or len(spend.get("items") or []))
    spend_read = int(spend_summary.get("read_store_count") or spend_summary.get("read_count") or spend_total)
    checks.append(item("功能验收：美团消耗/余量巡检", bool(spend) and (not spend_total or spend_read >= spend_total), f"已读 {spend_read}/{spend_total or '-'} 家", severity="should"))

    mobile_summary = agent_mobile.get("summary") if isinstance(agent_mobile.get("summary"), dict) else {}
    checks.append(item("功能验收：Agent 手机入口", bool(agent_mobile), f"入口数据 {agent_mobile.get('generated_at') or '-'}；失败 {mobile_summary.get('agent_failed', 0)}"))
    if token:
        agent_ok, agent_body = http_text(f"{agent_base}/agent/api/status?token={token}&limit=1")
        checks.append(item("功能验收：Agent 队列/API", agent_ok and "summary" in agent_body, "API 正常" if agent_ok and "summary" in agent_body else f"Agent API 未确认：{agent_body[:120]}"))
    else:
        checks.append(item("功能验收：Agent 队列/API", False, "未配置 AGENT_INBOX_TOKEN，跳过 API 内容校验", severity="should"))

    notify_state = ROOT / "outputs" / "agent_task_notifications" / "state.json"
    checks.append(item("功能验收：主动通知", notify_state.exists(), str(notify_state.relative_to(ROOT)) if notify_state.exists() else "尚未写入通知去重状态", severity="should"))
    return checks


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

    checks.extend(feature_status_checks(agent_base=agent_base, token=token))

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


def build_result(kind: str, checks: list[dict[str, Any]]) -> dict[str, Any]:
    failed = [row for row in checks if not row.get("ok") and row.get("severity") == "must"]
    warnings = [row for row in checks if not row.get("ok") and row.get("severity") != "must"]
    status = "ok" if not failed and not warnings else "warning" if not failed else "failed"
    return {
        "generated_at": now_text(),
        "kind": kind,
        "status": status,
        "summary": {
            "total": len(checks),
            "ok": len([row for row in checks if row.get("ok")]),
            "failed": len(failed),
            "warnings": len(warnings),
        },
        "checks": checks,
        "message": format_message(kind, status, checks),
    }


def format_message(kind: str, status: str, checks: list[dict[str, Any]]) -> str:
    title = "系统自检"
    status_text = {"ok": "通过", "warning": "部分通过", "failed": "未通过"}.get(status, status)
    failed = [row for row in checks if not row.get("ok") and row.get("severity") == "must"]
    warnings = [row for row in checks if not row.get("ok") and row.get("severity") != "must"]
    conclusion = "所有核心功能可用" if not failed else f"{len(failed)} 个核心项未通过"
    if warnings and not failed:
        conclusion = f"核心功能可用，{len(warnings)} 个提示项需关注"
    lines = [f"{title}：{status_text}。", f"结论：{conclusion}。", "功能验收状态："]
    feature_rows = [row for row in checks if str(row.get("name") or "").startswith("功能验收：")]
    other_rows = [row for row in checks if row not in feature_rows]
    for index, row in enumerate(feature_rows, start=1):
        mark = "OK" if row.get("ok") else "MISS"
        name = str(row.get("name") or "").replace("功能验收：", "")
        lines.append(f"{index}. {mark} {name}：{row.get('detail')}")
    if other_rows:
        lines.append("系统依赖：")
        for index, row in enumerate(other_rows, start=1):
            mark = "OK" if row.get("ok") else "MISS"
            lines.append(f"{index}. {mark} {row.get('name')}：{row.get('detail')}")
    return "\n".join(lines)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Agent 系统自检和长期功能验收。")
    parser.add_argument("--mode", choices=["system"], default="system")
    parser.add_argument("--cloud-base", default=os.environ.get("OPERATION_CLOUD_PUBLIC_URL", DEFAULT_CLOUD_BASE).rstrip("/"))
    parser.add_argument("--agent-base", default=os.environ.get("AGENT_PUBLIC_BASE_URL", DEFAULT_AGENT_BASE).rstrip("/"))
    parser.add_argument("--token", default=load_agent_token())
    parser.add_argument("--output", default=str(LATEST_PATH))
    args = parser.parse_args()

    payload = system_check(cloud_base=args.cloud_base, agent_base=args.agent_base, token=args.token)
    write_json(Path(args.output).expanduser(), payload)
    print(payload["message"])
    return 0 if payload["status"] != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
