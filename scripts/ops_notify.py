from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib import request as url_request

sys.path.insert(0, str(Path(__file__).resolve().parent))
import notify_text  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "ops_notify.json"
ASSISTANT_TOKEN = Path.home() / ".local/share/xiong-wecom-assistant/operator-token"
SEND_LOG_DIR = ROOT / "outputs" / "ops_notify"
LEGACY_NOTICE = "未配置 OPS_NOTIFY_WEBHOOK；WorkBuddy/Hermes 已标记为 legacy，不再自动使用。"


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def notify(text: str) -> bool:
    delivered, _output = notify_with_result(text)
    return delivered


def notify_with_result(text: str) -> tuple[bool, str]:
    text = notify_text.clean(text)
    config = load_config()
    channel = str(os.environ.get("OPS_NOTIFY_CHANNEL") or config.get("channel") or "webhook").strip().lower()
    if channel == "assistant":
        delivered, output = notify_via_assistant(text, config)
        if delivered:
            record_send(text, "assistant", True, output)
            return True, output
        # 助手不在线时退回群机器人，保证通知不丢。
        print(f"工作助手推送失败，改用群机器人：{output}", file=sys.stderr)
    delivered, output = notify_via_webhook(text, config)
    record_send(text, "webhook", delivered, output)
    return delivered, output


def notify_via_assistant(text: str, config: dict) -> tuple[bool, str]:
    port = int(os.environ.get("WECOM_HEALTH_PORT") or config.get("assistant_port") or 18769)
    try:
        token = ASSISTANT_TOKEN.read_text(encoding="utf-8").strip()
    except OSError:
        return False, "assistant token missing"
    req = url_request.Request(
        f"http://127.0.0.1:{port}/operator/notify",
        data=json.dumps({"text": text}, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + token},
    )
    opener = url_request.build_opener(url_request.ProxyHandler({}))
    try:
        body = json.loads(opener.open(req, timeout=15).read().decode("utf-8") or "{}")
    except Exception as exc:
        return False, f"assistant request failed: {exc}"
    return (True, "assistant ok") if body.get("ok") else (False, f"assistant error: {body.get('error')}")


def record_send(text: str, channel: str, delivered: bool, output: str) -> None:
    try:
        SEND_LOG_DIR.mkdir(parents=True, exist_ok=True)
        row = {"at": datetime.now().isoformat(timespec="seconds"), "channel": channel,
               "delivered": delivered, "output": output[:200], "text": text}
        with (SEND_LOG_DIR / f"{datetime.now():%F}.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass


def notify_via_webhook(text: str, config: dict) -> tuple[bool, str]:
    webhook = os.environ.get("OPS_NOTIFY_WEBHOOK") or config.get("webhook") or ""
    webhook = str(webhook).strip()
    if not webhook:
        if legacy_fallback_enabled(config):
            if notify_via_workbuddy(text, config):
                return True, "legacy-workbuddy"
            if notify_via_hermes(text, config):
                return True, "legacy-hermes"
            return False, "legacy fallback failed"
        print(LEGACY_NOTICE, file=sys.stderr)
        return False, LEGACY_NOTICE

    notify_type = str(os.environ.get("OPS_NOTIFY_TYPE") or config.get("type") or "wecom").strip().lower()
    if notify_type in {"wecom", "wechat_work", "企业微信", "企微"}:
        body = {"msgtype": "text", "text": {"content": text}}
    else:
        body = {"msg_type": "text", "content": {"text": text}}

    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = url_request.Request(webhook, data=payload, method="POST", headers={"Content-Type": "application/json"})
    try:
        response_body = url_request.urlopen(req, timeout=8).read()
    except Exception as exc:
        print(f"通知发送失败：{exc}", file=sys.stderr)
        return False, f"request failed: {exc}"

    delivered, output = parse_webhook_response(response_body, notify_type)
    if not delivered:
        print(f"通知发送失败：{output}", file=sys.stderr)
    return delivered, output


def parse_webhook_response(response_body: bytes, notify_type: str) -> tuple[bool, str]:
    text = response_body.decode("utf-8", errors="replace").strip()
    if not text:
        return False, "empty webhook response"
    try:
        payload = json.loads(text)
    except Exception:
        return False, f"non-json webhook response: {text[:200]}"

    notify_type = str(notify_type or "").strip().lower()
    if notify_type in {"wecom", "wechat_work", "企业微信", "企微"}:
        errcode = payload.get("errcode")
        errmsg = payload.get("errmsg") or payload.get("msg") or ""
        if str(errcode) == "0":
            return True, f"wecom errcode=0 errmsg={errmsg or 'ok'}"
        return False, f"wecom errcode={errcode} errmsg={errmsg or 'unknown'}"

    code = payload.get("code", payload.get("StatusCode"))
    msg = payload.get("msg") or payload.get("message") or payload.get("StatusMessage") or ""
    if code in (0, "0", None):
        return True, f"webhook accepted{': ' + str(msg) if msg else ''}"
    return False, f"webhook code={code} message={msg or 'unknown'}"


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
