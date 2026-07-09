from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
import re

from atomic_io import atomic_write_text
import agent_notify


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "agent_inbox_worker"
LATEST_PATH = OUTPUT_DIR / "latest.json"
LAST_COMMAND_PATH = OUTPUT_DIR / "last_command.json"
DEFAULT_BASE_URL = "http://139.155.148.169"


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def load_token() -> str:
    token = os.environ.get("AGENT_INBOX_TOKEN", "").strip()
    if token:
        return token
    for path in [Path.home() / ".xiong-agent-env", ROOT / "config" / "ops_notify.json"]:
        try:
            if path.suffix == ".json":
                payload = json.loads(path.read_text(encoding="utf-8"))
                value = str(payload.get("agent_inbox_token") or "").strip()
                if value:
                    return value
            else:
                for raw in path.read_text(encoding="utf-8").splitlines():
                    line = raw.strip()
                    if line.startswith("export "):
                        line = line[len("export ") :].strip()
                    if line.startswith("AGENT_INBOX_TOKEN="):
                        return line.split("=", 1)[1].strip().strip("'\"")
        except Exception:
            continue
    return ""


def request_json(base_url: str, path: str, token: str, *, method: str = "GET", payload: dict[str, Any] | None = None, timeout: int = 20) -> dict[str, Any]:
    query = urllib.parse.urlencode({"token": token})
    url = base_url.rstrip("/") + path + ("&" if "?" in path else "?") + query
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def run_agent_command(text: str, execute: bool) -> dict[str, Any]:
    command = [sys.executable or "python3", "scripts/agent_command.py", text]
    if execute:
        command.append("--execute")
    LAST_COMMAND_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        LAST_COMMAND_PATH.unlink()
    except FileNotFoundError:
        pass
    command.extend(["--output", str(LAST_COMMAND_PATH)])
    result = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False, timeout=3900)
    command_payload = read_json(LAST_COMMAND_PATH)
    return {
        "command": command,
        "returncode": result.returncode,
        "output_tail": (result.stdout or "")[-4000:],
        "command_payload": command_payload,
    }


def infer_business_notice(status: str, command_payload: dict[str, Any], answer: str) -> tuple[str, str]:
    if command_payload.get("blocked"):
        return "blocked", "这个动作已被安全规则挡住；订货/下单/采购仍不参与。"
    if status != "success":
        return "failed", "请到 Mac mini 查看 agent_inbox_worker 和对应命令日志。"

    intent = str(command_payload.get("intent") or "")
    text = str(answer or "")
    read_match = re.search(r"已读到\s*(\d+)\s*/\s*(\d+)\s*家", text)
    unread = False
    if read_match:
        unread = int(read_match.group(1)) < int(read_match.group(2))
    counters = {}
    for label in ("异常", "未核实", "预警"):
        match = re.search(rf"{label}\s*(\d+)", text)
        if match:
            counters[label] = int(match.group(1))
    if unread or counters.get("异常", 0) > 0 or counters.get("未核实", 0) > 0:
        return "warning", "巡检未完全通过；优先处理未核实/异常门店，长链接已在通知中省略。"
    if intent == "meituan_spend_inspection" and counters.get("预警", 0) > 0:
        return "warning", "巡检读数完成，但存在预警门店；请确认是否本应投放或预算接近耗尽。"
    return "success", "队列任务已完成。"


def notify_task_completion(task: dict[str, Any], status: str, result: dict[str, Any]) -> dict[str, Any]:
    command_payload = result.get("command_payload") if isinstance(result.get("command_payload"), dict) else {}
    answer = str(command_payload.get("answer") or result.get("output_tail") or "").strip()
    intent = str(command_payload.get("intent") or task.get("intent") or "unknown")
    notice_status, action = infer_business_notice(status, command_payload, answer)
    message = agent_notify.build_message(
        title=f"企微队列 {str(task.get('id') or '')[:8]}：{task.get('text') or 'Agent 命令'}",
        status=notice_status,
        detail=answer or f"命令退出码 {result.get('returncode')}",
        action=action,
        source=f"agent_inbox_worker:{intent}",
    )
    delivered, delivery_output = agent_notify.notify_message(message, dry_run=False)
    return {
        "delivered": delivered,
        "delivery_output": delivery_output,
        "message": message,
    }


def process_once(base_url: str, token: str, limit: int) -> dict[str, Any]:
    if not token:
        return {"ok": False, "error": "missing-agent-inbox-token", "processed": []}
    processed: list[dict[str, Any]] = []
    pending = request_json(base_url, f"/agent-wecom/inbox/pending?limit={limit}", token).get("items") or []
    for item in pending[:limit]:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        task_id = str(item["id"])
        try:
            claim = request_json(base_url, "/agent-wecom/inbox/claim", token, method="POST", payload={"id": task_id, "worker": socket.gethostname()})
            claimed = claim.get("item") if isinstance(claim.get("item"), dict) else item
        except urllib.error.HTTPError as exc:
            processed.append({"id": task_id, "status": "claim_failed", "error": f"http-{exc.code}"})
            continue
        text = str(claimed.get("text") or "")
        execute = bool(claimed.get("execute"))
        try:
            result = run_agent_command(text, execute=execute)
            status = "success" if result["returncode"] == 0 else "failed"
        except Exception as exc:
            result = {"returncode": 1, "output_tail": f"{type(exc).__name__}: {exc}"}
            status = "failed"
        result["queue_notification"] = notify_task_completion(claimed, status, result)
        request_json(
            base_url,
            "/agent-wecom/inbox/complete",
            token,
            method="POST",
            payload={"id": task_id, "status": status, "result": result},
        )
        processed.append({"id": task_id, "intent": claimed.get("intent"), "status": status, "returncode": result.get("returncode")})
    return {"ok": True, "processed": processed, "pending_count": len(pending)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Mac mini 轮询云端企业微信 Agent 收件箱。")
    parser.add_argument("--base-url", default=os.environ.get("AGENT_INBOX_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--token", default="")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--output", default=str(LATEST_PATH))
    args = parser.parse_args()

    token = args.token.strip() or load_token()
    try:
        payload = process_once(args.base_url, token, args.limit)
    except Exception as exc:
        payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "processed": []}
    payload.update({"generated_at": now_text(), "host": socket.gethostname()})
    write_json(Path(args.output).expanduser(), payload)
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
