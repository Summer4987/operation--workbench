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

from atomic_io import atomic_write_text


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "agent_inbox_worker"
LATEST_PATH = OUTPUT_DIR / "latest.json"
DEFAULT_BASE_URL = "http://139.155.148.169"


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


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
    command.extend(["--notify", "--output", str(LATEST_PATH.parent / "last_command.json")])
    result = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False, timeout=3900)
    return {
        "command": command,
        "returncode": result.returncode,
        "output_tail": (result.stdout or "")[-4000:],
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
