from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any
from urllib import error as url_error
from urllib import parse as url_parse
from urllib import request as url_request


FEISHU_API_BASE = os.environ.get("FEISHU_API_BASE", "https://open.feishu.cn").rstrip("/")
DEFAULT_WIKI_TOKEN = ""
DEFAULT_SHEET_ID = "直营店仓库"


class FeishuInventoryError(RuntimeError):
    pass


def sync_inventory(items: list[dict[str, Any]]) -> dict[str, Any]:
    token = _tenant_access_token()
    spreadsheet_token = _spreadsheet_token(token)
    sheet_id = os.environ.get("FEISHU_INVENTORY_SHEET_ID", DEFAULT_SHEET_ID).strip() or DEFAULT_SHEET_ID
    sheet_meta = _spreadsheet_meta(token, spreadsheet_token, sheet_id)
    headers = ["商品编码", "商品名称", "规格", "单位", "仓库", "库存余额", "预警值", "同步时间"]
    synced_at = datetime.now().astimezone().isoformat(timespec="seconds")
    rows = [
        [
            item.get("sku", ""),
            item.get("name", ""),
            item.get("spec", ""),
            item.get("unit", ""),
            item.get("warehouse", ""),
            _number(item.get("balance")),
            _number(item.get("warning_threshold")),
            synced_at,
        ]
        for item in items
    ]
    write_range = f"{sheet_id}!A1:H{len(rows) + 1}"
    _api_json(
        "POST",
        f"/open-apis/sheets/v2/spreadsheets/{url_parse.quote(spreadsheet_token, safe='')}/values_batch_update",
        token,
        {"valueRanges": [{"range": write_range, "values": [headers, *rows]}]},
    )
    verified_rows = _verify_written_values(token, spreadsheet_token, sheet_id, headers, rows)
    return {
        "status": "success",
        "row_count": len(rows),
        "verified_row_count": verified_rows,
        "sheet_id": sheet_id,
        "spreadsheet_title": sheet_meta.get("spreadsheet_title") or "",
        "sheet_title": sheet_meta.get("sheet_title") or sheet_id,
        "synced_at": synced_at,
    }


def _number(value: Any) -> int | float:
    number = float(value or 0)
    return int(number) if number.is_integer() else round(number, 4)


def _tenant_access_token() -> str:
    configured = os.environ.get("FEISHU_TENANT_ACCESS_TOKEN", "").strip()
    if configured:
        return configured
    app_id = os.environ.get("FEISHU_APP_ID", "").strip()
    app_secret = os.environ.get("FEISHU_APP_SECRET", "").strip()
    if not app_id or not app_secret:
        raise FeishuInventoryError("未配置 FEISHU_APP_ID / FEISHU_APP_SECRET，暂时无法同步到飞书")
    payload = _api_json(
        "POST",
        "/open-apis/auth/v3/tenant_access_token/internal",
        "",
        {"app_id": app_id, "app_secret": app_secret},
    )
    access_token = str(payload.get("tenant_access_token") or payload.get("data", {}).get("tenant_access_token") or "")
    if not access_token:
        raise FeishuInventoryError("飞书鉴权失败：没有取得 tenant_access_token")
    return access_token


def _spreadsheet_token(access_token: str) -> str:
    configured = os.environ.get("FEISHU_INVENTORY_SPREADSHEET_TOKEN", "").strip()
    if configured:
        return configured
    wiki_token = os.environ.get("FEISHU_INVENTORY_WIKI_TOKEN", DEFAULT_WIKI_TOKEN).strip()
    if not wiki_token:
        raise FeishuInventoryError("未配置 FEISHU_INVENTORY_SPREADSHEET_TOKEN 或 FEISHU_INVENTORY_WIKI_TOKEN")
    payload = _api_json(
        "GET",
        f"/open-apis/wiki/v2/spaces/get_node?{url_parse.urlencode({'token': wiki_token})}",
        access_token,
        None,
    )
    data = payload.get("data") or {}
    node = data.get("node") or data
    spreadsheet_token = str(node.get("obj_token") or node.get("objToken") or "")
    obj_type = str(node.get("obj_type") or node.get("objType") or "")
    if not spreadsheet_token or (obj_type and obj_type not in {"sheet", "spreadsheet"}):
        raise FeishuInventoryError("飞书库存表不是可写入的电子表格，或知识库节点解析失败")
    return spreadsheet_token


def _spreadsheet_meta(access_token: str, spreadsheet_token: str, sheet_id: str) -> dict[str, str]:
    payload = _api_json(
        "GET",
        f"/open-apis/sheets/v2/spreadsheets/{url_parse.quote(spreadsheet_token, safe='')}/metainfo",
        access_token,
        None,
    )
    data = payload.get("data") or {}
    properties = data.get("properties") or {}
    spreadsheet_title = str(properties.get("title") or "")
    sheet_title = ""
    for sheet in data.get("sheets") or []:
        current_id = str(sheet.get("sheetId") or sheet.get("sheet_id") or "")
        current_title = str(sheet.get("title") or "")
        if sheet_id in {current_id, current_title}:
            sheet_title = current_title
            break
    return {"spreadsheet_title": spreadsheet_title, "sheet_title": sheet_title}


def _verify_written_values(
    access_token: str,
    spreadsheet_token: str,
    sheet_id: str,
    headers: list[str],
    rows: list[list[Any]],
) -> int:
    read_range = f"{sheet_id}!A1:H{len(rows) + 1}"
    payload = _api_json(
        "GET",
        f"/open-apis/sheets/v2/spreadsheets/{url_parse.quote(spreadsheet_token, safe='')}/values/{url_parse.quote(read_range, safe='')}",
        access_token,
        None,
    )
    data = payload.get("data") or {}
    value_range = data.get("valueRange") or data.get("value_range") or {}
    values = value_range.get("values") or []
    if not values or values[0] != headers:
        raise FeishuInventoryError("飞书写入后读回校验失败：表头没有更新到目标工作表")
    verified_rows = max(0, len(values) - 1)
    if verified_rows < len(rows):
        raise FeishuInventoryError(f"飞书写入后读回校验失败：应写入 {len(rows)} 行，只读回 {verified_rows} 行")
    if rows and values[1][:2] != rows[0][:2]:
        raise FeishuInventoryError("飞书写入后读回校验失败：第一条库存数据和云端库存不一致")
    return verified_rows


def _api_json(method: str, path: str, access_token: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    req = url_request.Request(f"{FEISHU_API_BASE}{path}", data=body, headers=headers, method=method)
    try:
        with url_request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except url_error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise FeishuInventoryError(f"飞书 API HTTP {exc.code}: {detail[:500]}") from exc
    except (url_error.URLError, TimeoutError) as exc:
        raise FeishuInventoryError(f"飞书 API 网络失败：{exc}") from exc
    if not isinstance(result, dict) or int(result.get("code", 0) or 0) != 0:
        raise FeishuInventoryError(f"飞书 API 返回失败：{json.dumps(result, ensure_ascii=False)[:500]}")
    return result
