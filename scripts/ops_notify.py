from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from urllib import request as url_request


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "ops_notify.json"
LEGACY_NOTICE = "未配置 OPS_NOTIFY_WEBHOOK；WorkBuddy/Hermes 已标记为 legacy，不再自动使用。"


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def notify(text: str) -> bool:
    config = load_config()
    webhook = os.environ.get("OPS_NOTIFY_WEBHOOK") or config.get("webhook") or ""
    webhook = str(webhook).strip()
    if not webhook:
        if legacy_fallback_enabled(config):
            return notify_via_workbuddy(text, config) or notify_via_hermes(text, config)
        print(LEGACY_NOTICE, file=sys.stderr)
        return False

    notify_type = str(os.environ.get("OPS_NOTIFY_TYPE") or config.get("type") or "wecom").strip().lower()
    if notify_type in {"wecom", "wechat_work", "企业微信", "企微"}:
        body = {"msgtype": "text", "text": {"content": text}}
    else:
        body = {"msg_type": "text", "content": {"text": text}}

    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = url_request.Request(webhook, data=payload, method="POST", headers={"Content-Type": "application/json"})
    try:
        url_request.urlopen(req, timeout=8).read()
        return True
    except Exception as exc:
        print(f"通知发送失败：{exc}", file=sys.stderr)
        return False


def legacy_fallback_enabled(config: dict) -> bool:
    raw = os.environ.get("OPS_NOTIFY_ALLOW_LEGACY_FALLBACK")
    if raw is None:
        raw = str(config.get("allow_legacy_fallback") or "")
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def notify_via_workbuddy(text: str, config: dict) -> bool:
    workbuddy_bin = resolve_workbuddy_bin(config)
    if not Path(workbuddy_bin).exists():
        return False
    target = str(os.environ.get("OPS_NOTIFY_TARGET") or config.get("target") or "weixin")
    try:
        result = subprocess.run(
            [workbuddy_bin, "send", "--to", target, text],
            cwd=ROOT,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=45,
        )
    except Exception as exc:
        print(f"WorkBuddy 通知发送失败：{exc}", file=sys.stderr)
        return False
    output = (result.stdout or "").strip()
    if output:
        print(output)
    if result.returncode != 0:
        print(f"WorkBuddy 通知发送失败，退出码：{result.returncode}", file=sys.stderr)
    return result.returncode == 0


def resolve_workbuddy_bin(config: dict) -> str:
    configured = os.environ.get("OPS_NOTIFY_WORKBUDDY_BIN") or config.get("workbuddy_bin")
    candidates = [
        configured,
        Path.home() / "HermesPrivate" / "bin" / "workbuddy_hermes_send_compat.zsh",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(str(candidate)).expanduser()
        if path.exists():
            return str(path)
    return str(Path.home() / "HermesPrivate" / "bin" / "workbuddy_hermes_send_compat.zsh")


def notify_via_hermes(text: str, config: dict) -> bool:
    hermes_bin = resolve_hermes_bin(config)
    target = str(os.environ.get("OPS_NOTIFY_TARGET") or config.get("target") or "weixin")
    if not Path(hermes_bin).exists():
        print("未配置 OPS_NOTIFY_WEBHOOK，且 Hermes CLI 不存在，跳过通知。")
        return False
    try:
        result = subprocess.run(
            [hermes_bin, "send", "--to", target, text],
            cwd=ROOT,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=45,
        )
    except Exception as exc:
        print(f"Hermes 通知发送失败：{exc}", file=sys.stderr)
        return False
    output = (result.stdout or "").strip()
    if output:
        print(output)
    if result.returncode != 0:
        print(f"Hermes 通知发送失败，退出码：{result.returncode}", file=sys.stderr)
    return result.returncode == 0


def resolve_hermes_bin(config: dict) -> str:
    configured = os.environ.get("OPS_NOTIFY_HERMES_BIN") or config.get("hermes_bin")
    candidates = [
        configured,
        Path.home() / ".local" / "bin" / "hermes",
        Path.home() / ".hermes" / "hermes-agent" / "venv" / "bin" / "hermes",
        Path.home() / ".hermes" / "hermes-agent" / "hermes",
        Path.home() / "HermesUninstalledBackup" / "20260702_163629" / "bin" / "hermes",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(str(candidate)).expanduser()
        if path.exists():
            return str(path)
    return str(Path.home() / ".local" / "bin" / "hermes")


def main() -> int:
    text = "\n".join(sys.argv[1:]).strip() if len(sys.argv) > 1 else sys.stdin.read().strip()
    if not text:
        text = "运营自动化通知"
    return 0 if notify(text) else 1


if __name__ == "__main__":
    raise SystemExit(main())
