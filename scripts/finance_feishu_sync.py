from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import finance_inbox  # noqa: E402


DEFAULT_EXPORT_DIR = finance_inbox.DATA_DIR / "feishu_exports"
EXPORT_DIR = Path(os.environ.get("FINANCE_FEISHU_EXPORT_DIR", DEFAULT_EXPORT_DIR))
DEFAULT_CSV_EXPORT_PATH = EXPORT_DIR / "finance_ledger_feishu_upload.csv"
DEFAULT_JSON_EXPORT_PATH = EXPORT_DIR / "finance_ledger_feishu_payload.json"

FEISHU_API_BASE = os.environ.get("FEISHU_API_BASE", "https://open.feishu.cn")
TOKEN_ENV = "FEISHU_TENANT_ACCESS_TOKEN"
APP_ID_ENV = "FEISHU_APP_ID"
APP_SECRET_ENV = "FEISHU_APP_SECRET"
APP_TOKEN_ENV = "FEISHU_FINANCE_APP_TOKEN"
WIKI_TOKEN_ENV = "FEISHU_FINANCE_WIKI_TOKEN"
TABLE_ID_ENV = "FEISHU_FINANCE_TABLE_ID"

FEISHU_LEDGER_FIELD_MAP = {
    "ledger_id": "账本ID",
    "draft_id": "来源草稿ID",
    "confirmed_at": "确认时间",
    "confirmed_by": "确认人",
    "transaction_date": "业务日期",
    "direction": "收支方向",
    "amount": "金额",
    "currency": "币种",
    "store": "门店",
    "counterparty": "交易对方",
    "category": "财务分类",
    "payment_method": "收付款方式",
    "source_channel": "来源渠道",
    "raw_text": "原始文本",
    "note": "备注",
    "sync_status": "飞书同步状态",
}
FEISHU_DATE_FIELDS = {"transaction_date", "confirmed_at"}


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_ready_records() -> list[dict[str, Any]]:
    return [
        record
        for record in finance_inbox.read_jsonl(finance_inbox.LEDGER_PATH)
        if record.get("sync_status") == "ready_for_feishu"
    ]


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_direction: dict[str, dict[str, Any]] = {}
    total = 0.0
    for record in records:
        direction = str(record.get("direction") or "unknown")
        amount = float(record.get("amount") or 0)
        total += amount
        bucket = by_direction.setdefault(direction, {"count": 0, "amount": 0.0})
        bucket["count"] += 1
        bucket["amount"] = round(float(bucket["amount"]) + amount, 2)
    return {
        "record_count": len(records),
        "amount_total": round(total, 2),
        "by_direction": by_direction,
    }


def feishu_fields(record: dict[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for local_name, feishu_name in FEISHU_LEDGER_FIELD_MAP.items():
        value = record.get(local_name)
        if value is None:
            continue
        if local_name in FEISHU_DATE_FIELDS:
            value = feishu_date_value(str(value), local_name)
        fields[feishu_name] = value
    return fields


def feishu_date_value(value: str, field_name: str) -> int | str:
    formats = ["%Y-%m-%d %H:%M:%S"] if field_name == "confirmed_at" else ["%Y-%m-%d", "%Y-%m-%d %H:%M:%S"]
    for date_format in formats:
        try:
            return int(datetime.strptime(value, date_format).timestamp() * 1000)
        except ValueError:
            continue
    return value


def csv_fields(record: dict[str, Any]) -> dict[str, Any]:
    return {
        feishu_name: record.get(local_name)
        for local_name, feishu_name in FEISHU_LEDGER_FIELD_MAP.items()
        if record.get(local_name) is not None
    }


def write_exports(records: list[dict[str, Any]], csv_path: Path, json_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [csv_fields(record) for record in records]
    headers = list(FEISHU_LEDGER_FIELD_MAP.values())
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    csv_path.chmod(0o600)

    payload = {"records": [{"fields": feishu_fields(record)} for record in records]}
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    json_path.chmod(0o600)


def chunked(records: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [records[index : index + size] for index in range(0, len(records), size)]


def post_feishu_records(records: list[dict[str, Any]], token: str, app_token: str, table_id: str) -> list[str]:
    created_record_ids: list[str] = []
    endpoint = f"{FEISHU_API_BASE}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create"
    for batch in chunked(records, 500):
        body = json.dumps({"records": [{"fields": feishu_fields(record)} for record in batch]}, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                response_body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_text = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"飞书 API HTTP {exc.code}: {error_text}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"飞书 API 网络失败：{exc.reason}") from exc
        if response_body.get("code") != 0:
            raise RuntimeError(f"飞书 API 返回失败：{json.dumps(response_body, ensure_ascii=False)}")
        for item in response_body.get("data", {}).get("records", []):
            if item.get("record_id"):
                created_record_ids.append(str(item["record_id"]))
    return created_record_ids


def post_json(path: str, body: dict[str, Any], token: str | None = None) -> dict[str, Any]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(f"{FEISHU_API_BASE}{path}", data=data, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"飞书 API HTTP {exc.code}: {error_text}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"飞书 API 网络失败：{exc.reason}") from exc


def get_json(path: str, token: str) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{FEISHU_API_BASE}{path}",
        method="GET",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"飞书 API HTTP {exc.code}: {error_text}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"飞书 API 网络失败：{exc.reason}") from exc


def get_tenant_access_token() -> tuple[str, str]:
    preset_token = os.environ.get(TOKEN_ENV, "").strip()
    if preset_token:
        return preset_token, TOKEN_ENV
    app_id = os.environ.get(APP_ID_ENV, "").strip()
    app_secret = os.environ.get(APP_SECRET_ENV, "").strip()
    missing = [name for name, value in [(APP_ID_ENV, app_id), (APP_SECRET_ENV, app_secret)] if not value]
    if missing:
        raise RuntimeError("缺少飞书鉴权环境变量 " + ", ".join(missing))
    response = post_json(
        "/open-apis/auth/v3/tenant_access_token/internal",
        {"app_id": app_id, "app_secret": app_secret},
    )
    if response.get("code") != 0:
        raise RuntimeError(f"获取 tenant_access_token 失败：{json.dumps(response, ensure_ascii=False)}")
    token = str(response.get("tenant_access_token") or "")
    if not token:
        raise RuntimeError("获取 tenant_access_token 失败：响应中没有 token")
    return token, f"{APP_ID_ENV}+{APP_SECRET_ENV}"


def resolve_bitable_app_token(token: str) -> tuple[str, str]:
    app_token = os.environ.get(APP_TOKEN_ENV, "").strip()
    if app_token:
        return app_token, APP_TOKEN_ENV
    wiki_token = os.environ.get(WIKI_TOKEN_ENV, "").strip()
    if not wiki_token:
        raise RuntimeError(f"缺少 {APP_TOKEN_ENV}；如果链接是 /wiki/...，请设置 {WIKI_TOKEN_ENV}")
    response = get_json(f"/open-apis/wiki/v2/spaces/get_node?token={wiki_token}", token)
    if response.get("code") != 0:
        raise RuntimeError(f"解析 Wiki 节点失败：{json.dumps(response, ensure_ascii=False)}")
    node = response.get("data", {}).get("node", {})
    if node.get("obj_type") != "bitable":
        raise RuntimeError(f"Wiki 节点不是多维表格：obj_type={node.get('obj_type')}")
    obj_token = str(node.get("obj_token") or "")
    if not obj_token:
        raise RuntimeError("解析 Wiki 节点失败：响应中没有 obj_token")
    return obj_token, WIKI_TOKEN_ENV


def rewrite_ledger_after_sync(records: list[dict[str, Any]], record_ids: list[str] | None = None, error: str | None = None) -> None:
    ledger_records = finance_inbox.read_jsonl(finance_inbox.LEDGER_PATH)
    target_ids = [str(record.get("ledger_id") or "") for record in records]
    record_id_by_ledger_id = dict(zip(target_ids, record_ids or []))
    for record in ledger_records:
        ledger_id = str(record.get("ledger_id") or "")
        if ledger_id not in target_ids:
            continue
        if error:
            record["sync_status"] = "sync_failed"
            record["sync_error"] = error[:500]
            continue
        record["sync_status"] = "synced"
        record["synced_at"] = now_text()
        if record_id_by_ledger_id.get(ledger_id):
            record["feishu_record_id"] = record_id_by_ledger_id[ledger_id]
        record.pop("sync_error", None)
    finance_inbox.write_jsonl(finance_inbox.LEDGER_PATH, ledger_records)
    finance_inbox.export_ledger_csv()


def command_sync(args: argparse.Namespace) -> int:
    records = load_ready_records()
    summary = summarize(records)
    print("飞书财务账本同步预检：")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    csv_path = Path(args.csv_path or DEFAULT_CSV_EXPORT_PATH)
    json_path = Path(args.json_path or DEFAULT_JSON_EXPORT_PATH)
    write_exports(records, csv_path, json_path)
    print(f"已生成飞书导入 CSV：{csv_path}")
    print(f"已生成飞书 API payload：{json_path}")

    table_id = os.environ.get(TABLE_ID_ENV, "").strip()
    if not args.execute:
        print("当前为 dry-run/export-only：未传入 --execute，不会写入飞书。")
        return 0
    if not table_id:
        print(f"当前为 export-only：缺少飞书环境变量 {TABLE_ID_ENV}，不会写入飞书。")
        return 2
    if not records:
        print("没有 sync_status=ready_for_feishu 的账本记录，无需写入飞书。")
        return 0

    try:
        token, token_source = get_tenant_access_token()
        app_token, app_token_source = resolve_bitable_app_token(token)
        print(f"飞书鉴权来源：{token_source}；多维表 token 来源：{app_token_source}。")
        record_ids = post_feishu_records(records, token, app_token, table_id)
    except RuntimeError as exc:
        print(str(exc))
        if "缺少" in str(exc):
            print("当前为 export-only：飞书鉴权或表配置不完整，不会写入飞书。")
            return 2
        rewrite_ledger_after_sync(records, error=str(exc))
        print("飞书写入失败；本地记录已标记 sync_failed。")
        return 1

    rewrite_ledger_after_sync(records, record_ids=record_ids)
    print(f"飞书写入成功：{len(records)} 条。本地记录已标记 synced。")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="飞书财务确认账本同步脚本；默认 dry-run/export-only。")
    parser.add_argument("--execute", action="store_true", help="token 齐全时实际写入飞书。默认只导出和预检。")
    parser.add_argument("--csv-path", help="覆盖飞书导入 CSV 输出路径。")
    parser.add_argument("--json-path", help="覆盖飞书 API payload 输出路径。")
    return parser


def main() -> int:
    return command_sync(build_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
