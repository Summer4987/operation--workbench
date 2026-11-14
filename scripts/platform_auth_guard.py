"""Local, platform-specific hold after a real login or verification failure.

No browser calls, automatic expiry, credentials, or budget actions. A person
confirms verification before access resumes.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

STATE_DIR = Path(__file__).resolve().parents[1] / "outputs/platform_auth_guard"
PLATFORMS = {"美团": "meituan", "饿了么": "eleme"}


class PlatformAuthBlocked(RuntimeError):
    pass


def is_auth_failure(value: object) -> bool:
    return isinstance(value, PlatformAuthBlocked) or any(word in str(value) for word in (
        "安全验证", "身份核实", "滑块", "验证码", "登录态失效", "登录页",
        "登录已过期", "请重新登录", "要求重新登录", "verify.meituan.com",
    ))


def state_path(platform: str) -> Path:
    return STATE_DIR / f"{PLATFORMS[platform]}.json"


def pending(platform: str) -> dict | None:
    path = state_path(platform)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if payload.get("status") == "blocked" else None


def write_state(platform: str, payload: dict) -> None:
    path = state_path(platform)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def safe_url(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}" if parts.netloc else ""


def block(platform: str, reason: str, url: str = "") -> dict:
    existing = pending(platform)
    if existing:
        return existing
    reason = re.sub(r"https?://[^\s）)]+", lambda match: safe_url(match.group()), reason)
    payload = {"platform": platform, "status": "blocked", "reason": reason[:800],
               "detected_at": datetime.now().isoformat(timespec="seconds"),
               "page_url": safe_url(url), "resume_requires": "manual_verification_confirmation"}
    write_state(platform, payload)
    return payload


def require_access(platform: str) -> None:
    if pending(platform):
        raise PlatformAuthBlocked(f"{platform}安全验证/登录待人工确认；本轮不再打开后台或自动重试。完成验证后再确认恢复。")


def release(platform: str, *, confirmed: bool) -> None:
    if not confirmed:
        raise ValueError("必须先明确确认已完成人工验证，才能恢复一次访问。")
    write_state(platform, {"platform": platform, "status": "released",
                           "confirmed_at": datetime.now().isoformat(timespec="seconds")})


def begin_page_attempt(page) -> None:
    context = getattr(page, "context", None)
    page._auth_attempt_baseline = {id(item): getattr(item, "url", "")
                                   for item in getattr(context, "pages", [])}


def current_meituan_challenge(page):
    """Only this page, a new popup, or an existing tab newly redirected now."""
    baseline = getattr(page, "_auth_attempt_baseline", None)
    context = getattr(page, "context", None)
    for candidate in [page, *getattr(context, "pages", [])]:
        url = getattr(candidate, "url", "") or ""
        if urlsplit(url).hostname != "verify.meituan.com":
            continue
        if candidate is page:
            return candidate
        if baseline is not None and (id(candidate) not in baseline or baseline[id(candidate)] != url):
            return candidate
    return None


def failure_needs_human(path: Path, since: float) -> bool:
    if not path.exists() or path.stat().st_mtime < since:
        return False
    payload = json.loads(path.read_text(encoding="utf-8"))
    return any(is_auth_failure(error) for error in payload.get("errors", []))


def main() -> int:
    parser = argparse.ArgumentParser(description="平台验证等待状态；不会打开后台或提交预算。")
    parser.add_argument("action", choices=["status", "block", "release", "failure-needs-human"])
    parser.add_argument("--platform", choices=list(PLATFORMS), default="美团")
    parser.add_argument("--reason", default="平台安全验证等待人工处理")
    parser.add_argument("--confirmed", action="store_true")
    parser.add_argument("--failure-path", type=Path)
    parser.add_argument("--since", type=float, default=0)
    args = parser.parse_args()
    if args.action == "failure-needs-human":
        return 0 if args.failure_path and failure_needs_human(args.failure_path, args.since) else 1
    if args.action == "block":
        block(args.platform, args.reason)
    elif args.action == "release":
        release(args.platform, confirmed=args.confirmed)
    print(json.dumps(pending(args.platform) or {"platform": args.platform, "status": "released"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
