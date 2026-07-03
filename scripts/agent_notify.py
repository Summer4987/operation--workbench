from __future__ import annotations

import argparse
import json
import socket
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from atomic_io import atomic_write_text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ops_notify  # noqa: E402


OUTPUT_DIR = ROOT / "outputs" / "agent_notify"
LATEST_PATH = OUTPUT_DIR / "latest.json"

STATUS_LABELS = {
    "success": "正常",
    "failed": "失败",
    "warning": "注意",
    "blocked": "已拦截",
    "preview": "预览",
    "info": "通知",
}


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def compact(text: str, *, limit: int = 900) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def build_message(
    *,
    title: str,
    status: str,
    detail: str = "",
    action: str = "",
    source: str = "Agent",
    generated_at: str | None = None,
) -> str:
    label = STATUS_LABELS.get(status, status or "通知")
    lines = [
        f"【熊小小运营 Agent｜{label}】",
        f"事项：{compact(title, limit=120)}",
    ]
    if detail:
        lines.append(f"说明：{compact(detail)}")
    if action:
        lines.append(f"建议：{compact(action, limit=260)}")
    lines.append(f"来源：{compact(source, limit=80)}")
    lines.append(f"时间：{generated_at or now_text()}")
    return "\n".join(lines)


def message_from_command_payload(payload: dict[str, Any]) -> tuple[str, str]:
    intent = str(payload.get("intent") or "chat")
    answer = str(payload.get("answer") or "")
    command_text = str(payload.get("command_text") or "")
    actions = payload.get("actions") if isinstance(payload.get("actions"), list) else []
    failed_actions = [item for item in actions if isinstance(item, dict) and item.get("returncode") not in {0, None}]

    if payload.get("blocked"):
        status = "blocked"
        action = "这个动作已被安全规则挡住；如需开放，需要单独设计流程。"
    elif failed_actions:
        status = "failed"
        action = "请先看 Mac mini 上对应日志；高风险动作不要绕过安全闸。"
    elif intent in {"budget_preview", "budget_commit"} and payload.get("execute"):
        status = "success"
        action = "已按当前权限执行；真实提交仍受预算脚本时间窗口和登录态检查保护。"
    elif intent in {"budget_preview", "budget_commit"}:
        status = "preview"
        action = "未执行生产动作；需要在 Mac mini 命令后加 --execute。"
    else:
        status = "info"
        action = ""

    title = command_text or "Agent 命令结果"
    return status, build_message(
        title=title,
        status=status,
        detail=answer,
        action=action,
        source=f"agent_command:{intent}",
        generated_at=str(payload.get("generated_at") or now_text()),
    )


def notify_message(message: str, *, dry_run: bool) -> tuple[bool, str]:
    if dry_run:
        return True, "dry-run"
    ok = ops_notify.notify(message)
    return ok, "sent" if ok else "send-failed"


def send_agent_notification(
    *,
    title: str,
    status: str = "info",
    detail: str = "",
    action: str = "",
    source: str = "Agent",
    dry_run: bool = False,
    output: Path = LATEST_PATH,
) -> dict[str, Any]:
    message = build_message(title=title, status=status, detail=detail, action=action, source=source)
    delivered, delivery_output = notify_message(message, dry_run=dry_run)
    payload = {
        "generated_at": now_text(),
        "host": socket.gethostname(),
        "dry_run": bool(dry_run),
        "delivered": delivered,
        "delivery_output": delivery_output,
        "message": message,
    }
    write_json(output, payload)
    return payload


def send_command_notification(payload: dict[str, Any], *, dry_run: bool = False, output: Path = LATEST_PATH) -> dict[str, Any]:
    status, message = message_from_command_payload(payload)
    delivered, delivery_output = notify_message(message, dry_run=dry_run)
    record = {
        "generated_at": now_text(),
        "host": socket.gethostname(),
        "dry_run": bool(dry_run),
        "status": status,
        "intent": payload.get("intent"),
        "delivered": delivered,
        "delivery_output": delivery_output,
        "message": message,
    }
    write_json(output, record)
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description="Agent 企业微信通知入口。")
    parser.add_argument("--title", default="Agent 通知", help="通知事项")
    parser.add_argument("--status", default="info", choices=sorted(STATUS_LABELS), help="通知状态")
    parser.add_argument("--detail", default="", help="通知说明")
    parser.add_argument("--action", default="", help="建议动作")
    parser.add_argument("--source", default="Agent", help="通知来源")
    parser.add_argument("--dry-run", action="store_true", help="只生成消息，不发送到企业微信")
    parser.add_argument("--output", default=str(LATEST_PATH), help="输出 JSON 路径")
    args = parser.parse_args()

    payload = send_agent_notification(
        title=args.title,
        status=args.status,
        detail=args.detail,
        action=args.action,
        source=args.source,
        dry_run=args.dry_run,
        output=Path(args.output).expanduser(),
    )
    print(payload["message"])
    return 0 if payload["delivered"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
