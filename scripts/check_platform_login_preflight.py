from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "business-report-dashboard"
DIRECT_ACCOUNT_CHECKER = ROOT / "scripts" / "check_direct_meituan_account.py"
NOTIFY_RUNNER = ROOT / "scripts" / "ops_notify.py"
OUTPUT_DIR = ROOT / "outputs" / "platform_login_preflight"
LATEST_PATH = OUTPUT_DIR / "latest.json"

WORKING_NODE = "/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
if Path(WORKING_NODE).exists():
    os.environ.setdefault("PLAYWRIGHT_NODEJS_PATH", WORKING_NODE)

if str(REPORT_DIR) not in sys.path:
    sys.path.insert(0, str(REPORT_DIR))

import chrome_cdp_reports as cdp  # noqa: E402


LOGIN_BLOCKERS = [
    "账号登录",
    "验证码登录",
    "验证码",
    "安全验证",
    "扫码登录",
    "身份核实",
    "拖动滑块",
    "忘记密码",
    "未登录",
    "login",
    "verify.meituan.com",
    "无效店铺",
    "当前账号无法访问该店铺",
]

ELEME_REALTIME_URL = "https://melody.shop.ele.me/app/unit/stats__center#app.unit.stats.center"


def require_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError:
        print("缺少 playwright，无法做开跑前登录态预检。")
        raise SystemExit(2)
    return sync_playwright


def compact_text(value: str, limit: int = 360) -> str:
    return " ".join(str(value or "").split())[:limit]


def page_text(page) -> str:
    parts: list[str] = []
    for target in [page, *page.frames]:
        try:
            text = target.evaluate("() => document.body ? document.body.innerText : ''")
        except Exception:
            continue
        if text:
            parts.append(str(text))
    return "\n".join(parts)


def classify_page(platform: str, title: str, url: str, body: str, ready_texts: list[str]) -> dict[str, Any]:
    haystack = "\n".join([title or "", url or "", body or ""])
    blockers = [token for token in LOGIN_BLOCKERS if token and token in haystack]
    matched = [token for token in ready_texts if token and token in haystack]
    if blockers:
        status = "auth_block"
    elif matched:
        status = "ok"
    else:
        status = "needs_manual"
    return {
        "platform": platform,
        "status": status,
        "title": title,
        "url": url,
        "matched_texts": matched,
        "blocking_texts": blockers,
        "text_sample": compact_text(body),
    }


def check_common_platforms(scope: str, wait_ms: int) -> list[dict[str, Any]]:
    config = cdp.load_config()
    if not cdp.cdp_available(config):
        if not cdp.start_chrome(wait_seconds=45):
            return [
                {
                    "platform": "日常Chrome",
                    "status": "browser_unavailable",
                    "message": f"Chrome/CDP 调试端口不可用：{cdp.debug_url(config)}",
                    "url": cdp.debug_url(config),
                }
            ]
    playwright, browser = cdp.connect_browser(config)
    results: list[dict[str, Any]] = []
    try:
        context = cdp.first_context(browser)
        for key, platform in config.get("platforms", {}).items():
            if scope == "budget" and key not in {"eleme", "meituan"}:
                continue
            page = cdp.reusable_page(context)
            url = platform.get("download_url") or platform.get("entry_url")
            if scope == "realtime" and key == "eleme":
                url = ELEME_REALTIME_URL
            try:
                cdp.goto_backend_page(page, url, timeout=90_000)
                page.wait_for_timeout(wait_ms)
                results.append(
                    classify_page(
                        str(platform.get("name") or key),
                        page.title(),
                        page.url,
                        page_text(page),
                        [str(item) for item in platform.get("ready_texts") or []],
                    )
                )
            except Exception as exc:
                results.append(
                    {
                        "platform": str(platform.get("name") or key),
                        "status": "page_error",
                        "message": str(exc),
                        "url": url,
                    }
                )
    finally:
        cdp.disconnect_browser(playwright, browser)
    return results


def direct_accounts_enabled() -> list[str]:
    config_path = ROOT / "config" / "direct_meituan_accounts.json"
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return [
        str(item.get("id"))
        for item in payload.get("accounts") or []
        if item.get("enabled") and item.get("id")
    ]


def check_direct_meituan_accounts(wait_ms: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for account_id in direct_accounts_enabled():
        cmd = [
            sys.executable,
            str(DIRECT_ACCOUNT_CHECKER),
            "--account",
            account_id,
            "--pages",
            "home",
            "--wait-ms",
            str(wait_ms),
        ]
        completed = subprocess.run(
            cmd,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=max(45, int(wait_ms / 1000) + 45),
        )
        output = completed.stdout or ""
        results.append(
            {
                "platform": "直营美团",
                "account_id": account_id,
                "status": "ok" if completed.returncode == 0 else "auth_block",
                "message": compact_text(output, 600),
            }
        )
    return results


def should_check_direct(scope: str, include_direct: bool) -> bool:
    return include_direct or scope in {"morning", "all"}


def notify(text: str) -> None:
    try:
        subprocess.run([sys.executable, str(NOTIFY_RUNNER), text], cwd=ROOT, timeout=12)
    except Exception:
        pass


def write_payload(payload: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LATEST_PATH.chmod(0o644)


def build_notice(scope: str, failed: list[dict[str, Any]], continue_on_direct_failure: bool = False) -> str:
    direct_only = bool(failed) and all(item.get("platform") == "直营美团" for item in failed)
    lines = [
        "【运营自动化开跑前预检失败】",
        f"范围：{scope}",
        (
            "发现直营账号登录问题；失败门店将单独跳过，其它门店和总部任务继续执行。"
            if continue_on_direct_failure and direct_only
            else "发现登录态/验证码/Chrome 页面问题，已停止对应正式动作。"
        ),
    ]
    for item in failed[:6]:
        platform = item.get("platform") or item.get("account_id") or "未知平台"
        blockers = "、".join(item.get("blocking_texts") or []) or item.get("status") or "needs_manual"
        lines.append(f"- {platform}：{blockers}")
    lines.append("请在 Mac mini 对应 Chrome 页面完成登录、验证码或安全验证后再补跑失败门店。")
    return "\n".join(lines)


def build_payload(scope: str, include_direct: bool, wait_ms: int) -> dict[str, Any]:
    checks = check_common_platforms(scope, wait_ms)
    if should_check_direct(scope, include_direct):
        checks.extend(check_direct_meituan_accounts(wait_ms))
    failed = [item for item in checks if item.get("status") != "ok"]
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scope": scope,
        "status": "ok" if not failed else "failed",
        "summary": {
            "check_count": len(checks),
            "ok_count": len(checks) - len(failed),
            "failed_count": len(failed),
        },
        "checks": checks,
        "failed_checks": failed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="运营自动化开跑前登录态只读预检。")
    parser.add_argument("--scope", choices=["morning", "budget", "realtime", "all"], default="all")
    parser.add_argument("--include-direct", action="store_true", help="额外检查直营美团独立账号。")
    parser.add_argument("--wait-ms", type=int, default=3500)
    parser.add_argument("--notify", action="store_true", help="失败时发送运营通知。")
    parser.add_argument(
        "--continue-on-direct-failure",
        action="store_true",
        help="直营账号失败时明确标记为单店隔离；调用方可继续其它门店和总部任务。",
    )
    args = parser.parse_args()

    payload = build_payload(args.scope, args.include_direct, args.wait_ms)
    write_payload(payload)
    summary = payload["summary"]
    print(
        f"开跑前登录态预检：{payload['status']}，"
        f"检查 {summary['check_count']} 项，失败 {summary['failed_count']} 项，结果：{LATEST_PATH}"
    )
    for item in payload["checks"]:
        detail = "、".join(item.get("blocking_texts") or []) or item.get("message") or ""
        print(f"- {item.get('platform')}: {item.get('status')} {detail}".rstrip())
    if payload["status"] != "ok":
        notice = build_notice(args.scope, payload["failed_checks"], args.continue_on_direct_failure)
        print(notice)
        if args.notify:
            notify(notice)
        return 66
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
