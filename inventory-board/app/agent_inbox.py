from __future__ import annotations

import json
import os
import secrets
import time
import uuid
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_INBOX_PATH = BASE_DIR / "data" / "agent_inbox.json"


def inbox_path() -> Path:
    return Path(os.environ.get("AGENT_INBOX_PATH", str(DEFAULT_INBOX_PATH))).expanduser()


def inbox_token() -> str:
    return os.environ.get("AGENT_INBOX_TOKEN", "").strip()


def token_valid(token: str) -> bool:
    expected = inbox_token()
    return bool(expected and secrets.compare_digest(str(token or ""), expected))


def now_ts() -> int:
    return int(time.time())


def read_inbox(path: Path | None = None) -> dict[str, Any]:
    target = path or inbox_path()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload.setdefault("items", [])
            return payload
    except Exception:
        pass
    return {"version": 1, "items": []}


def write_inbox(payload: dict[str, Any], path: Path | None = None) -> None:
    target = path or inbox_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(target)


def append_task(
    *,
    text: str,
    intent: str,
    execute: bool,
    source: str,
    sender: str = "",
    path: Path | None = None,
) -> dict[str, Any]:
    payload = read_inbox(path)
    item = {
        "id": uuid.uuid4().hex,
        "created_at": now_ts(),
        "updated_at": now_ts(),
        "status": "pending",
        "text": str(text or "").strip(),
        "intent": intent,
        "execute": bool(execute),
        "source": source,
        "sender": sender,
        "attempts": 0,
        "result": {},
    }
    items = [existing for existing in payload.get("items", []) if isinstance(existing, dict)]
    items.append(item)
    payload["items"] = items[-200:]
    write_inbox(payload, path)
    return item


def pending_tasks(limit: int = 5, path: Path | None = None) -> list[dict[str, Any]]:
    payload = read_inbox(path)
    rows = [item for item in payload.get("items", []) if isinstance(item, dict) and item.get("status") == "pending"]
    return rows[: max(1, min(int(limit or 5), 20))]


def claim_task(task_id: str, *, worker: str, path: Path | None = None) -> dict[str, Any] | None:
    payload = read_inbox(path)
    claimed = None
    for item in payload.get("items", []):
        if not isinstance(item, dict) or item.get("id") != task_id or item.get("status") != "pending":
            continue
        item["status"] = "running"
        item["updated_at"] = now_ts()
        item["worker"] = worker
        item["attempts"] = int(item.get("attempts") or 0) + 1
        claimed = item
        break
    if claimed:
        write_inbox(payload, path)
    return claimed


def complete_task(task_id: str, *, status: str, result: dict[str, Any], path: Path | None = None) -> dict[str, Any] | None:
    payload = read_inbox(path)
    updated = None
    for item in payload.get("items", []):
        if not isinstance(item, dict) or item.get("id") != task_id:
            continue
        item["status"] = "success" if status == "success" else "failed"
        item["updated_at"] = now_ts()
        item["result"] = result if isinstance(result, dict) else {}
        updated = item
        break
    if updated:
        write_inbox(payload, path)
    return updated


def command_policy(text: str) -> dict[str, Any]:
    clean = " ".join(str(text or "").split())
    if not clean:
        return {"enqueue": False, "intent": "help", "execute": False, "reason": "empty"}
    lower = clean.lower()
    if any(word in clean for word in ("订货", "下单", "采购", "快驴")) or any(word in lower for word in ("order", "purchase")):
        return {"enqueue": False, "intent": "blocked_ordering", "execute": False, "reason": "ordering-blocked"}
    if any(word in clean for word in ("确认执行预算重跑", "确认重跑预算设置", "确认真实提交预算", "确认提交预算")):
        return {"enqueue": True, "intent": "budget_commit", "execute": True, "reason": "explicit-budget-confirmation"}
    if "预算" in clean and any(word in clean for word in ("重跑", "补跑", "重新", "设置", "初始化")):
        return {"enqueue": True, "intent": "budget_preview", "execute": True, "reason": "budget-preview-only"}
    if any(word in clean for word in ("刷新", "更新", "重新生成")) and any(word in clean for word in ("状态", "agent", "Agent", "入口")):
        return {"enqueue": True, "intent": "refresh_status", "execute": True, "reason": "refresh-status"}
    if any(word in clean for word in ("发布手机入口", "发布入口", "同步到云端", "上线手机入口")):
        return {"enqueue": True, "intent": "publish_mobile", "execute": True, "reason": "publish-mobile"}
    if "非订货" in clean and any(word in clean for word in ("执行", "恢复", "处理", "补跑", "修复")):
        return {"enqueue": True, "intent": "execute_non_ordering", "execute": True, "reason": "non-ordering-execution"}
    return {"enqueue": False, "intent": "", "execute": False, "reason": "read-only"}
