from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import finance_inbox  # noqa: E402


FINANCE_INBOX = ROOT / "scripts" / "finance_inbox.py"
FEISHU_SYNC = ROOT / "scripts" / "finance_feishu_sync.py"
FINANCE_WEB = ROOT / "scripts" / "finance_web.py"
RUNBOOK = ROOT / "docs" / "FINANCE_SYSTEM_RUNBOOK.md"


def run_script(script: Path, args: list[str]) -> int:
    completed = subprocess.run([sys.executable, str(script), *args], cwd=ROOT, check=False)
    return int(completed.returncode)


def env_present(*names: str) -> dict[str, bool]:
    return {name: bool(os.environ.get(name, "").strip()) for name in names}


def command_status(_: argparse.Namespace) -> int:
    drafts = finance_inbox.read_jsonl(finance_inbox.DRAFTS_PATH)
    ledger = finance_inbox.read_jsonl(finance_inbox.LEDGER_PATH)
    draft_status = Counter(str(item.get("status") or "unknown") for item in drafts)
    ledger_status = Counter(str(item.get("sync_status") or "unknown") for item in ledger)
    pending = [
        item
        for item in drafts
        if item.get("status") == finance_inbox.DRAFT_PENDING and item.get("draft_id") not in finance_inbox.ledger_draft_ids()
    ]
    config = env_present(
        "FEISHU_TENANT_ACCESS_TOKEN",
        "FEISHU_FINANCE_APP_TOKEN",
        "FEISHU_APP_ID",
        "FEISHU_APP_SECRET",
        "FEISHU_FINANCE_WIKI_TOKEN",
        "FEISHU_FINANCE_TABLE_ID",
    )
    can_execute_by_token = config["FEISHU_TENANT_ACCESS_TOKEN"] and config["FEISHU_FINANCE_APP_TOKEN"] and config["FEISHU_FINANCE_TABLE_ID"]
    can_execute_by_app = config["FEISHU_APP_ID"] and config["FEISHU_APP_SECRET"] and config["FEISHU_FINANCE_WIKI_TOKEN"] and config["FEISHU_FINANCE_TABLE_ID"]
    status: dict[str, Any] = {
        "system": "熊小小财务系统",
        "data_dir": str(finance_inbox.DATA_DIR),
        "drafts": {
            "total": len(drafts),
            "pending_confirmation": len(pending),
            "by_status": dict(draft_status),
        },
        "ledger": {
            "total": len(ledger),
            "by_sync_status": dict(ledger_status),
            "ready_for_feishu": ledger_status.get("ready_for_feishu", 0),
            "synced": ledger_status.get("synced", 0),
            "sync_failed": ledger_status.get("sync_failed", 0),
        },
        "feishu": {
            "execute_config_ready": bool(can_execute_by_token or can_execute_by_app),
            "configured_env": config,
            "default_mode": "dry-run/export-only unless --execute is passed",
        },
        "safety": {
            "wechat_intake_auto_confirm": False,
            "wechat_intake_auto_sync": False,
            "requires_human_confirm": True,
            "requires_human_mark_ready": True,
        },
    }
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


def command_record(args: argparse.Namespace) -> int:
    text = args.text or " ".join(args.text_parts)
    if not text.strip():
        raise SystemExit("请提供财务文本，例如：record 今天 熊小小万象城 微信支付采购原料 12.34 元")
    return run_script(FINANCE_INBOX, ["intake", "--operator", args.operator, "--text", text])


def command_drafts(args: argparse.Namespace) -> int:
    cli_args = ["list-drafts"]
    if args.all:
        cli_args.append("--all")
    if args.json:
        cli_args.append("--json")
    return run_script(FINANCE_INBOX, cli_args)


def command_ledger(args: argparse.Namespace) -> int:
    cli_args = ["list-ledger"]
    if args.status:
        cli_args.extend(["--status", args.status])
    if args.json:
        cli_args.append("--json")
    return run_script(FINANCE_INBOX, cli_args)


def command_confirm(args: argparse.Namespace) -> int:
    cli_args = ["confirm", "--draft-id", args.draft_id, "--operator", args.operator]
    optional = {
        "--transaction-date": args.transaction_date,
        "--direction": args.direction,
        "--amount": args.amount,
        "--category": args.category,
        "--payment-method": args.payment_method,
        "--store": args.store,
        "--counterparty": args.counterparty,
        "--note": args.note,
    }
    for name, value in optional.items():
        if value is not None and value != "":
            cli_args.extend([name, str(value)])
    return run_script(FINANCE_INBOX, cli_args)


def command_ready(args: argparse.Namespace) -> int:
    return run_script(FINANCE_INBOX, ["mark-ready", "--ledger-id", args.ledger_id, "--operator", args.operator])


def command_sync(args: argparse.Namespace) -> int:
    cli_args: list[str] = []
    if args.execute:
        cli_args.append("--execute")
    return run_script(FEISHU_SYNC, cli_args)


def command_guide(_: argparse.Namespace) -> int:
    print(RUNBOOK.read_text(encoding="utf-8"))
    return 0


def command_serve(args: argparse.Namespace) -> int:
    return run_script(FINANCE_WEB, ["--host", args.host, "--port", str(args.port)])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="熊小小财务系统正式入口：草稿、确认账本、飞书同步。")
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", aliases=["状态"], help="查看草稿、账本和飞书配置状态。")
    status.set_defaults(func=command_status)

    record = subparsers.add_parser("record", aliases=["记录", "录入"], help="录入一条财务文本为待确认草稿。")
    record.add_argument("--text", help="财务文本。")
    record.add_argument("--operator", default="finance-system", help="录入人。")
    record.add_argument("text_parts", nargs="*", help="不使用 --text 时，剩余参数会拼成财务文本。")
    record.set_defaults(func=command_record)

    drafts = subparsers.add_parser("drafts", aliases=["草稿"], help="列出财务草稿。")
    drafts.add_argument("--all", action="store_true", help="显示全部草稿。")
    drafts.add_argument("--json", action="store_true", help="输出 JSON。")
    drafts.set_defaults(func=command_drafts)

    ledger = subparsers.add_parser("ledger", aliases=["账本"], help="列出确认账本。")
    ledger.add_argument("--status", choices=["local_only", "ready_for_feishu", "synced", "sync_failed"], help="按同步状态过滤。")
    ledger.add_argument("--json", action="store_true", help="输出 JSON。")
    ledger.set_defaults(func=command_ledger)

    confirm = subparsers.add_parser("confirm", aliases=["确认"], help="人工确认草稿进入本地账本。")
    confirm.add_argument("--draft-id", required=True)
    confirm.add_argument("--operator", required=True)
    confirm.add_argument("--transaction-date")
    confirm.add_argument("--direction", choices=sorted(finance_inbox.CONFIRMABLE_DIRECTIONS))
    confirm.add_argument("--amount", type=float)
    confirm.add_argument("--category", choices=sorted(finance_inbox.CONFIRMABLE_CATEGORIES))
    confirm.add_argument("--payment-method", choices=sorted(finance_inbox.VALID_PAYMENT_METHODS))
    confirm.add_argument("--store")
    confirm.add_argument("--counterparty")
    confirm.add_argument("--note", default="")
    confirm.set_defaults(func=command_confirm)

    ready = subparsers.add_parser("ready", aliases=["待同步"], help="人工标记一条账本可同步飞书。")
    ready.add_argument("--ledger-id", required=True)
    ready.add_argument("--operator", required=True)
    ready.set_defaults(func=command_ready)

    sync = subparsers.add_parser("sync", aliases=["同步"], help="飞书同步；默认 dry-run/export-only。")
    sync.add_argument("--execute", action="store_true", help="实际写入飞书。")
    sync.set_defaults(func=command_sync)

    guide = subparsers.add_parser("guide", aliases=["说明", "手册"], help="打印财务系统使用说明。")
    guide.set_defaults(func=command_guide)

    serve = subparsers.add_parser("serve", aliases=["入口", "网页"], help="启动财务系统网页录入口。")
    serve.add_argument("--host", default="127.0.0.1", help="监听地址。")
    serve.add_argument("--port", type=int, default=8765, help="监听端口。")
    serve.set_defaults(func=command_serve)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
