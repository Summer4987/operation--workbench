from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = ROOT / "outputs" / "macmini_smoke" / "latest.log"
OUTPUT_DIR = ROOT / "outputs" / "macmini_smoke_status"
LATEST_PATH = OUTPUT_DIR / "latest.json"


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def write_latest(payload: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LATEST_PATH.chmod(0o644)


def tail_lines(text: str, limit: int = 12) -> list[str]:
    return [line for line in text.splitlines() if line.strip()][-limit:]


def build_payload() -> dict[str, Any]:
    generated_at = now_text()
    if not LOG_PATH.exists():
        return {
            "generated_at": generated_at,
            "status": "waiting_log",
            "log_path": str(LOG_PATH.relative_to(ROOT)),
            "summary": {"has_log": False, "is_production": False, "completed": False},
            "message": "尚未收到 Mac mini 只读冒烟检查日志。",
            "next_action": "在 Mac mini 项目目录运行 /bin/zsh scripts/run_macmini_ai_center_smoke.zsh。",
            "tail": [],
        }

    text = LOG_PATH.read_text(encoding="utf-8", errors="replace")
    is_production = "环境：production" in text
    completed = "Mac mini 只读冒烟检查完成。" in text
    development_only = "当前不是 Mac mini 生产环境" in text or not is_production
    failed = any(token in text for token in ["Traceback", "Error:", "ERROR", "失败：", "command not found"])
    if completed and is_production and not failed:
        status = "ready"
        message = "Mac mini 只读冒烟检查已完成。"
    elif development_only:
        status = "development_only"
        message = "当前只有开发环境冒烟日志，不能代表 Mac mini 生产状态。"
    elif failed:
        status = "failed"
        message = "Mac mini 冒烟日志包含失败信息，需查看日志尾部。"
    else:
        status = "incomplete"
        message = "Mac mini 冒烟日志存在，但尚未看到完成结论。"

    return {
        "generated_at": generated_at,
        "status": status,
        "log_path": str(LOG_PATH.relative_to(ROOT)),
        "summary": {
            "has_log": True,
            "is_production": is_production,
            "completed": completed,
            "failed": failed,
            "size": LOG_PATH.stat().st_size,
            "updated_at": datetime.fromtimestamp(LOG_PATH.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        },
        "message": message,
        "next_action": "如需生产确认，请在 Mac mini 运行只读冒烟检查并保留 latest.log。",
        "tail": tail_lines(text),
    }


def main() -> int:
    payload = build_payload()
    write_latest(payload)
    print(payload["message"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
