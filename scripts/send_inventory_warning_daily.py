#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from atomic_io import atomic_write_text


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "http://139.155.148.169"
STATE_PATH = ROOT / "outputs" / "inventory_warning_daily" / "state.json"
LATEST_PATH = ROOT / "outputs" / "inventory_warning_daily" / "latest.json"


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
    for path in (Path.home() / ".xiong-agent-env", ROOT / "config" / "ops_notify.json"):
        try:
            if path.suffix == ".json":
                token = str(json.loads(path.read_text(encoding="utf-8")).get("agent_inbox_token") or "").strip()
                if token:
                    return token
                continue
            for raw in path.read_text(encoding="utf-8").splitlines():
                line = raw.strip().removeprefix("export ").strip()
                if line.startswith("AGENT_INBOX_TOKEN="):
                    return line.split("=", 1)[1].strip().strip("'\"")
        except Exception:
            continue
    return ""


def trigger(base_url: str, token: str, timeout: int = 30) -> dict[str, Any]:
    query = urllib.parse.urlencode({"token": token})
    url = f"{base_url.rstrip('/')}/api/inventory/warnings/notify?{query}"
    request = urllib.request.Request(url, data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("库存预警接口返回格式不正确")
    return payload


def run(*, base_url: str, force: bool = False, today: str | None = None) -> dict[str, Any]:
    today = today or datetime.now().strftime("%Y-%m-%d")
    state = read_json(STATE_PATH)
    if not force and state.get("last_completed_date") == today:
        return {"status": "skipped", "date": today, "message": "今日16:00库存预警已处理，本次跳过。"}
    token = load_token()
    if not token:
        raise RuntimeError("缺少 AGENT_INBOX_TOKEN，无法安全触发云端库存预警")
    result = trigger(base_url, token)
    payload = {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "date": today, **result}
    LATEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(LATEST_PATH, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    if result.get("status") in {"sent", "clear"}:
        atomic_write_text(
            STATE_PATH,
            json.dumps({"last_completed_date": today, "last_status": result.get("status")}, ensure_ascii=False, indent=2) + "\n",
        )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="每天16:00单独推送仓库库存预警")
    parser.add_argument("--base-url", default=os.environ.get("INVENTORY_WARNING_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--force", action="store_true", help="忽略当天去重状态并重新触发")
    args = parser.parse_args()
    try:
        payload = run(base_url=args.base_url, force=args.force)
    except Exception as exc:
        print(f"库存预警推送失败：{exc}")
        return 1
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload.get("status") in {"sent", "clear", "skipped"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
