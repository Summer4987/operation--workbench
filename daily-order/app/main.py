from __future__ import annotations

import csv
import io
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib import request as url_request

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles


BASE_DIR = Path(__file__).resolve().parents[1]
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"
SUBMISSION_DIR = DATA_DIR / "submissions"
ORDER_LINES_PATH = DATA_DIR / "order-lines.csv"
CATALOG_PATH = BASE_DIR / "app" / "catalog.json"

app = FastAPI(title="Daily Order")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)
app.mount("/daily-order/static", StaticFiles(directory=STATIC_DIR), name="daily-order-static")


@app.get("/daily-order/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/daily-order/admin")
def admin():
    return FileResponse(STATIC_DIR / "admin.html")


@app.get("/daily-order/api/catalog")
def catalog():
    return _load_catalog()


@app.get("/daily-order/api/health")
def health():
    catalog_data = _load_catalog()
    return {"status": "ok", "item_count": len(catalog_data["items"])}


@app.post("/daily-order/api/orders")
async def submit_order(request: Request, payload: dict):
    catalog_data = _load_catalog()
    products = {item["sku"]: item for item in catalog_data["items"]}
    store_records = _store_records(catalog_data)
    stores = set(store_records)
    store_name = str(payload.get("store_name") or "").strip()
    remark = str(payload.get("remark") or "").strip()
    raw_items = payload.get("items") or []

    if not store_name:
        raise HTTPException(status_code=400, detail="请选择门店")
    if stores and store_name not in stores:
        raise HTTPException(status_code=400, detail="请选择有效门店")
    if not isinstance(raw_items, list):
        raise HTTPException(status_code=400, detail="订货明细格式不正确")

    lines = []
    for raw in raw_items:
        sku = str(raw.get("sku") or "").strip()
        product = products.get(sku)
        quantity = _to_number(raw.get("quantity"))
        if not product:
            continue
        line_note = product["note"]
        if sku == "MEAL-001":
            line_note = str(raw.get("note") or "").strip()
            if not line_note:
                raise HTTPException(status_code=400, detail="请填写工作餐内容")
            quantity = 1
        if quantity <= 0:
            continue
        lines.append(
            {
                "sku": sku,
                "source": product["source"],
                "purchase_channel": _purchase_channel(product),
                "category": product["category"],
                "name": product["name"],
                "spec": product["spec"],
                "unit": product["unit"],
                "note": line_note,
                "quantity": quantity,
            }
        )

    if not lines:
        raise HTTPException(status_code=400, detail="请至少填写一个订货数量")

    submitted_time = datetime.now(timezone.utc).astimezone()
    submitted_at = submitted_time.isoformat(timespec="seconds")
    order_id = f"DO-{submitted_time.strftime('%Y%m%d-%H%M%S')}-{submitted_time.strftime('%f')[:3]}"
    auto_processed_channels = _auto_processed_channels(lines)
    order = {
        "order_id": order_id,
        "store_name": store_name,
        "store_address": store_records.get(store_name, {}).get("address", ""),
        "remark": remark,
        "status": "processed" if auto_processed_channels and set(_order_channels({"items": lines})).issubset(auto_processed_channels) else "pending",
        "processed_at": now_iso() if auto_processed_channels and set(_order_channels({"items": lines})).issubset(auto_processed_channels) else "",
        "processed_channels": sorted(auto_processed_channels),
        "submitted_at": submitted_at,
        "client_host": request.client.host if request.client else "",
        "items": lines,
    }

    SUBMISSION_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"{order_id}_{_safe_name(store_name)}"
    json_path = SUBMISSION_DIR / f"{stem}.json"
    csv_path = SUBMISSION_DIR / f"{stem}.csv"
    json_path.write_text(json.dumps(order, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_order_csv(csv_path, order)
    _append_order_lines(order)
    _notify_order(order)
    _notify_wechat_groups(order)

    return {
        "status": "success",
        "order_id": order_id,
        "line_count": len(lines),
        "submitted_at": submitted_at,
    }


@app.get("/daily-order/api/orders")
def recent_store_orders(store_name: str):
    store_name = store_name.strip()
    if not store_name:
        raise HTTPException(status_code=400, detail="请选择门店")
    return {"items": [order for order in _read_orders() if order["store_name"] == store_name]}


@app.get("/daily-order/api/admin/summary")
def admin_summary(request: Request, status: str = "pending"):
    _require_admin(request)
    if status not in {"pending", "processed", "all"}:
        raise HTTPException(status_code=400, detail="状态不正确")
    all_orders = _read_orders()
    orders = [_order_for_status(order, status) for order in all_orders]
    orders = [order for order in orders if order.get("items")]
    return {
        "status": status,
        "orders": orders,
        "channels": _channel_summary(orders),
        "stats": {
            "order_count": len(orders),
            "line_count": sum(len(order.get("items") or []) for order in orders),
            "pending_count": sum(1 for order in all_orders if _order_for_status(order, "pending").get("items")),
        },
    }


@app.get("/daily-order/api/admin/order-lines")
def admin_order_lines(request: Request, month: str = ""):
    _require_admin(request)
    rows = _order_line_rows(month.strip())
    return {
        "month": month.strip(),
        "line_count": len(rows),
        "rows": rows,
        "totals": _order_line_totals(rows),
    }


@app.get("/daily-order/api/admin/order-lines.csv")
def admin_order_lines_csv(request: Request, month: str = ""):
    _require_admin(request)
    rows = _order_line_rows(month.strip())
    text = _rows_to_csv(ORDER_LINE_HEADERS, rows)
    filename = f"daily-order-lines-{month.strip() or 'all'}.csv"
    return Response(
        content=text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.patch("/daily-order/api/admin/orders/{order_id}/status")
async def update_order_status(order_id: str, request: Request, payload: dict):
    _require_admin(request)
    status = str(payload.get("status") or "").strip()
    if status not in {"pending", "processed"}:
        raise HTTPException(status_code=400, detail="状态不正确")
    path = _order_path(order_id)
    if path is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    order = _normalize_order(json.loads(path.read_text(encoding="utf-8")))
    order["status"] = status
    order["processed_at"] = now_iso() if status == "processed" else ""
    order["processed_channels"] = _order_channels(order) if status == "processed" else []
    path.write_text(json.dumps(order, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_order_csv(path.with_suffix(".csv"), order)
    return {"status": "success", "order": _normalize_order(order)}


@app.patch("/daily-order/api/admin/orders/{order_id}/channels/{channel}/status")
async def update_order_channel_status(order_id: str, channel: str, request: Request, payload: dict):
    _require_admin(request)
    status = str(payload.get("status") or "").strip()
    if status not in {"pending", "processed"}:
        raise HTTPException(status_code=400, detail="状态不正确")
    channel = channel.strip()
    if not channel:
        raise HTTPException(status_code=400, detail="渠道不正确")
    path = _order_path(order_id)
    if path is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    order = _normalize_order(json.loads(path.read_text(encoding="utf-8")))
    channels = _order_channels(order)
    target_channels = _matching_order_channels(channels, channel)
    if not target_channels:
        raise HTTPException(status_code=404, detail="该订单没有这个渠道")
    processed_channels = set(order.get("processed_channels") or [])
    if status == "processed":
        processed_channels.update(target_channels)
    else:
        processed_channels.difference_update(target_channels)
    order["processed_channels"] = sorted(processed_channels)
    order["status"] = "processed" if set(channels).issubset(processed_channels) else "pending"
    order["processed_at"] = now_iso() if order["status"] == "processed" else ""
    path.write_text(json.dumps(order, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_order_csv(path.with_suffix(".csv"), order)
    return {"status": "success", "order": _normalize_order(order), "channel": channel}


@app.patch("/daily-order/api/admin/channels/{channel}/status")
async def update_channel_status(channel: str, request: Request, payload: dict):
    _require_admin(request)
    status = str(payload.get("status") or "").strip()
    if status not in {"pending", "processed"}:
        raise HTTPException(status_code=400, detail="状态不正确")
    channel = channel.strip()
    if not channel:
        raise HTTPException(status_code=400, detail="渠道不正确")
    changed = []
    for path in SUBMISSION_DIR.glob("*.json"):
        try:
            order = _normalize_order(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
        channels = _order_channels(order)
        target_channels = _matching_order_channels(channels, channel)
        if not target_channels:
            continue
        processed_channels = set(order.get("processed_channels") or [])
        if status == "processed":
            processed_channels.update(target_channels)
        else:
            processed_channels.difference_update(target_channels)
        order["processed_channels"] = sorted(processed_channels)
        order["status"] = "processed" if set(channels).issubset(processed_channels) else "pending"
        order["processed_at"] = now_iso() if order["status"] == "processed" else ""
        path.write_text(json.dumps(order, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _write_order_csv(path.with_suffix(".csv"), order)
        changed.append(order["order_id"])
    return {"status": "success", "channel": channel, "order_count": len(changed), "order_ids": changed}


def _load_catalog() -> dict:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def _store_records(catalog_data: dict) -> dict[str, dict]:
    raw = catalog_data.get("stores") or []
    if raw and isinstance(raw[0], dict):
        return {str(item["name"]): item for item in raw if item.get("name")}
    addresses = {
        "金融城店": "四川省成都市武侯区石羊街道新街里6c区3楼3035号熊小小牛排饭",
        "银泰城店": "四川省成都市武侯区桂溪街道益州大道1999号成都银泰城悦坊6栋二层222熊小小牛排饭",
        "万象城店": "四川省成都市成华区万年场街道华润柒公馆双福一路58号一层附99号熊小小牛排饭",
        "保利中心店": "四川省成都市武侯区玉林街道保利中心东区C座一层熊小小牛排饭",
    }
    return {str(name): {"name": str(name), "address": addresses.get(str(name), "")} for name in raw}


def _default_purchase_channel(product: dict) -> str:
    source = product.get("source")
    if source == "快驴配送":
        return "快驴"
    if source == "同城物流配送":
        return "微信群"
    if source == "厂家配送（2日内）":
        return "微信群"
    category = product.get("category")
    if category in {"耗材", "包材"}:
        return "拼多多"
    return "淘宝"


def _purchase_channel(product: dict) -> str:
    name = str(product.get("name") or "")
    sku = str(product.get("sku") or "")
    wechat_group = _wechat_group_channel(name, sku)
    if wechat_group:
        return wechat_group
    return product.get("purchase_channel") or _default_purchase_channel(product)


def _wechat_group_channel(name: str, sku: str) -> str:
    if name == "大米" or "黑米" in name or "燕麦米" in name:
        return "大米群"
    if name == "虾仁" or sku == "CJ-020":
        return "虾仁群"
    if name == "辣白菜" or sku == "CJ-015":
        return "辣白菜群"
    if name in {"玉米淀粉盒", "餐具包", "餐具", "小塑料盒", "小塑料碗"} or sku in {"CJ-027", "CJ-030", "CJ-033"}:
        return "颂李包装群"
    if name in {"打包袋", "餐盒", "酱料盒"} or sku in {"CJ-038", "CJ-041", "CJ-044"}:
        return "四川鸿鹄包装群"
    return ""


def _to_number(value) -> float:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return number if number > 0 else 0.0


def _safe_name(value: str) -> str:
    text = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "-", value).strip("-")
    return text[:40] or "store"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _read_orders() -> list[dict]:
    SUBMISSION_DIR.mkdir(parents=True, exist_ok=True)
    orders = []
    for path in SUBMISSION_DIR.glob("*.json"):
        try:
            orders.append(_normalize_order(json.loads(path.read_text(encoding="utf-8"))))
        except Exception:
            continue
    orders.sort(key=lambda order: (order.get("submitted_at", ""), order.get("order_id", "")), reverse=True)
    return orders


def _normalize_order(order: dict) -> dict:
    order.setdefault("status", "pending")
    order.setdefault("processed_at", "")
    order.setdefault("store_address", "")
    products = {}
    if not order["store_address"] and order.get("store_name"):
        try:
            catalog_data = _load_catalog()
            products = {item["sku"]: item for item in catalog_data.get("items", [])}
            order["store_address"] = _store_records(catalog_data).get(order["store_name"], {}).get("address", "")
        except Exception:
            order["store_address"] = ""
    elif order.get("items"):
        try:
            products = {item["sku"]: item for item in _load_catalog().get("items", [])}
        except Exception:
            products = {}
    for item in order.get("items") or []:
        product = products.get(item.get("sku"), item)
        item["purchase_channel"] = _purchase_channel(product)
    channels = _order_channels(order)
    if "processed_channels" not in order:
        processed_channels = set(channels if order.get("status") == "processed" else [])
        processed_channels.update(_auto_processed_channels(order.get("items") or []))
        order["processed_channels"] = sorted(processed_channels)
    else:
        processed_channels = set(order.get("processed_channels") or [])
        migrated_channels = {channel for channel in processed_channels if channel in channels}
        if "微信群" in processed_channels:
            migrated_channels.update(channel for channel in channels if "群" in channel or channel == "微信群")
        migrated_channels.update(_auto_processed_channels(order.get("items") or []))
        if order.get("status") == "processed":
            migrated_channels.update(channels)
        order["processed_channels"] = sorted(migrated_channels)
    if channels and set(channels).issubset(set(order.get("processed_channels") or [])):
        order["status"] = "processed"
        order["processed_at"] = order.get("processed_at") or now_iso()
    return order


def _order_for_status(order: dict, status: str) -> dict:
    if status == "all":
        return order
    scoped = {**order}
    scoped["items"] = [
        item
        for item in order.get("items") or []
        if _channel_is_processed(order, item.get("purchase_channel") or _default_purchase_channel(item)) == (status == "processed")
    ]
    return scoped


def _order_channels(order: dict) -> list[str]:
    return sorted({_item_channel(item) for item in order.get("items") or []})


def _item_channel(item: dict) -> str:
    wechat_group = _wechat_group_channel(str(item.get("name") or ""), str(item.get("sku") or ""))
    if wechat_group:
        return wechat_group
    return item.get("purchase_channel") or _default_purchase_channel(item)


def _display_channel(channel: str) -> str:
    return "微信群" if "群" in channel else channel


def _matching_order_channels(channels: list[str], display_channel: str) -> set[str]:
    return {channel for channel in channels if channel == display_channel or _display_channel(channel) == display_channel}


def _channel_sort_key(channel: dict) -> tuple[int, str]:
    order = {"快驴": 0, "微信群": 1, "工作餐": 2, "淘宝": 3, "拼多多": 4, "京东": 5}
    name = str(channel.get("channel") or "")
    return (order.get(name, 99), name)


def _auto_processed_channels(items: list[dict]) -> set[str]:
    return {_item_channel(item) for item in items if _display_channel(_item_channel(item)) == "微信群"}


def _channel_is_processed(order: dict, channel: str) -> bool:
    return channel in set(order.get("processed_channels") or [])


def _order_path(order_id: str) -> Path | None:
    safe_id = Path(order_id).name
    return next(SUBMISSION_DIR.glob(f"{safe_id}_*.json"), None)


def _channel_summary(orders: list[dict]) -> list[dict]:
    channels: dict[str, dict] = {}
    for order in orders:
        for item in order.get("items") or []:
            item_channel = item.get("purchase_channel") or _default_purchase_channel(item)
            channel_name = _display_channel(item_channel)
            channel = channels.setdefault(channel_name, {"channel": channel_name, "stores": {}, "orders": {}, "totals": {}})
            store = channel["stores"].setdefault(
                order["store_name"],
                {
                    "store_name": order["store_name"],
                    "store_address": order.get("store_address", ""),
                    "orders": [],
                    "items": {},
                },
            )
            store["orders"].append(order["order_id"])
            channel_order = channel["orders"].setdefault(
                order["order_id"],
                {
                    "order_id": order["order_id"],
                    "store_name": order["store_name"],
                    "store_address": order.get("store_address", ""),
                    "submitted_at": order.get("submitted_at", ""),
                    "remark": order.get("remark", ""),
                    "status": "processed",
                    "items": {},
                },
            )
            if not _channel_is_processed(order, item_channel):
                channel_order["status"] = "pending"
            sku = item["sku"]
            line = store["items"].setdefault(
                sku,
                {
                    "sku": sku,
                    "name": item["name"],
                    "spec": item.get("spec", ""),
                    "unit": item.get("unit", ""),
                    "note": item.get("note", ""),
                    "purchase_channel": item_channel,
                    "status": "processed" if _channel_is_processed(order, item_channel) else "pending",
                    "quantity": 0,
                },
            )
            line["quantity"] += float(item.get("quantity") or 0)
            order_line = channel_order["items"].setdefault(sku, {**line, "quantity": 0})
            order_line["quantity"] += float(item.get("quantity") or 0)
            total = channel["totals"].setdefault(sku, {**line, "quantity": 0})
            total["quantity"] += float(item.get("quantity") or 0)
    return sorted([
        {
            "channel": channel["channel"],
            "orders": [
                {**order, "items": list(order["items"].values())}
                for order in sorted(channel["orders"].values(), key=lambda item: (item.get("submitted_at", ""), item.get("order_id", "")), reverse=True)
            ],
            "stores": [
                {**store, "orders": sorted(set(store["orders"])), "items": list(store["items"].values())}
                for store in channel["stores"].values()
            ],
            "totals": list(channel["totals"].values()),
        }
        for channel in channels.values()
    ], key=_channel_sort_key)


def _require_admin(request: Request) -> None:
    token = os.environ.get("DAILY_ORDER_ADMIN_TOKEN", "daily-order-admin")
    supplied = request.query_params.get("token", "")
    if supplied != token:
        raise HTTPException(status_code=403, detail="后台链接无效")


def _notify_order(order: dict) -> None:
    webhook = os.environ.get("DAILY_ORDER_NOTIFY_WEBHOOK", "").strip()
    if not webhook:
        return
    notify_type = os.environ.get("DAILY_ORDER_NOTIFY_TYPE", "generic").strip().lower()
    text = _order_message(order)
    _send_notify_text(webhook, notify_type, text, {"order": order})


def _notify_wechat_groups(order: dict) -> None:
    webhook = os.environ.get("DAILY_ORDER_WECHAT_NOTIFY_WEBHOOK", "").strip() or os.environ.get("DAILY_ORDER_NOTIFY_WEBHOOK", "").strip()
    if not webhook:
        return
    notify_type = os.environ.get("DAILY_ORDER_WECHAT_NOTIFY_TYPE", "").strip().lower() or os.environ.get("DAILY_ORDER_NOTIFY_TYPE", "wecom").strip().lower()
    for text in _wechat_group_messages(order):
        _send_notify_text(webhook, notify_type, text, {"order": order, "message_type": "wechat_group_order"})


def _send_notify_text(webhook: str, notify_type: str, text: str, extra_payload: dict | None = None) -> None:
    if notify_type == "wecom":
        payload = {"msgtype": "text", "text": {"content": text}}
    elif notify_type == "feishu":
        payload = {"msg_type": "text", "content": {"text": text}}
    elif notify_type == "dingtalk":
        payload = {"msgtype": "text", "text": {"content": text}}
    else:
        payload = {"text": text, **(extra_payload or {})}
    try:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = url_request.Request(webhook, data=body, headers={"Content-Type": "application/json"})
        url_request.urlopen(req, timeout=8).read()
    except Exception:
        pass


def _wechat_group_messages(order: dict) -> list[str]:
    groups: dict[str, dict[str, dict]] = {}
    for item in order.get("items") or []:
        item_channel = _item_channel(item)
        if _display_channel(item_channel) != "微信群":
            continue
        stores = groups.setdefault(item_channel, {})
        store_key = f"{order.get('store_name', '')}||{order.get('store_address', '')}"
        store = stores.setdefault(
            store_key,
            {
                "store_name": order.get("store_name") or "未命名门店",
                "store_address": order.get("store_address") or "未填写地址",
                "items": {},
            },
        )
        item_key = f"{item.get('name', '')}||{item.get('spec', '')}||{item.get('unit', '')}||{item.get('note', '')}"
        line = store["items"].setdefault(
            item_key,
            {
                "name": item.get("name", ""),
                "spec": item.get("spec", ""),
                "unit": item.get("unit", ""),
                "note": item.get("note", ""),
                "quantity": 0,
            },
        )
        line["quantity"] += _to_number(item.get("quantity"))
    return [_wechat_group_message_text(group_name, list(stores.values())) for group_name, stores in groups.items()]


def _wechat_group_message_text(group_name: str, stores: list[dict]) -> str:
    sections = [f"【{group_name}】"]
    for store in stores:
        lines = [
            f"{store['store_name']}（{store['store_address']}）",
            *[_plain_order_line(item) for item in store["items"].values()],
        ]
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


def _plain_order_line(item: dict) -> str:
    spec = f" {item.get('spec')}" if item.get("spec") else ""
    note = f" · {item.get('note')}" if item.get("note") else ""
    return f"{item.get('name', '')}{spec}{note} {_format_number(item.get('quantity'))}{item.get('unit') or ''}"


def _format_number(value) -> str:
    number = _to_number(value)
    return str(int(number)) if number.is_integer() else f"{number:.2f}"


def _order_message(order: dict) -> str:
    message = os.environ.get("DAILY_ORDER_NOTIFY_MESSAGE", "").strip()
    if message:
        return f"{message}\n门店：{order.get('store_name') or '未命名门店'}"
    channels = sorted({item.get("purchase_channel", "") for item in order.get("items") or [] if item.get("purchase_channel")})
    lines = [
        f"新订货订单：{order['store_name']}",
        f"订单号：{order['order_id']}",
        f"渠道：{'、'.join(channels) if channels else '未分类'}",
    ]
    for item in (order.get("items") or [])[:8]:
        spec = f" {item.get('spec')}" if item.get("spec") else ""
        lines.append(f"- {item['name']}{spec} {item['quantity']}{item.get('unit', '')}")
    return "\n".join(lines)


ORDER_LINE_HEADERS = ["订单号", "提交时间", "月份", "状态", "门店", "地址", "采购渠道", "配送方式", "分类", "SKU", "品名", "规格", "数量", "单位", "备注", "门店备注"]


def _order_line_row(order: dict, item: dict) -> dict:
    submitted_at = order.get("submitted_at", "")
    return {
        "订单号": order.get("order_id", ""),
        "提交时间": submitted_at,
        "月份": submitted_at[:7],
        "状态": order.get("status", "pending"),
        "门店": order.get("store_name", ""),
        "地址": order.get("store_address", ""),
        "采购渠道": item.get("purchase_channel", ""),
        "配送方式": item.get("source", ""),
        "分类": item.get("category", ""),
        "SKU": item.get("sku", ""),
        "品名": item.get("name", ""),
        "规格": item.get("spec", ""),
        "数量": item.get("quantity", 0),
        "单位": item.get("unit", ""),
        "备注": item.get("note", ""),
        "门店备注": order.get("remark", ""),
    }


def _order_line_rows(month: str = "") -> list[dict]:
    rows = [
        _order_line_row(order, item)
        for order in _read_orders()
        for item in order.get("items") or []
        if not month or str(order.get("submitted_at", "")).startswith(month)
    ]
    rows.sort(key=lambda row: (row["提交时间"], row["订单号"], row["SKU"]), reverse=True)
    return rows


def _order_line_totals(rows: list[dict]) -> list[dict]:
    totals: dict[tuple[str, str, str, str, str], float] = {}
    for row in rows:
        key = (row["采购渠道"], row["门店"], row["SKU"], row["品名"], row["单位"])
        totals[key] = totals.get(key, 0.0) + _to_number(row["数量"])
    return [
        {"采购渠道": channel, "门店": store, "SKU": sku, "品名": name, "单位": unit, "数量": quantity}
        for (channel, store, sku, name, unit), quantity in sorted(totals.items())
    ]


def _rows_to_csv(headers: list[str], rows: list[dict]) -> str:
    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.DictWriter(output, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def _append_order_lines(order: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    exists = ORDER_LINES_PATH.exists()
    with ORDER_LINES_PATH.open("a", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=ORDER_LINE_HEADERS)
        if not exists or ORDER_LINES_PATH.stat().st_size == 0:
            writer.writeheader()
        for item in order.get("items") or []:
            writer.writerow(_order_line_row(order, item))


def _write_order_csv(path: Path, order: dict) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.writer(target)
        writer.writerow(["订单号", "提交时间", "状态", "门店", "地址", "采购渠道", "配送方式", "分类", "SKU", "品名", "规格", "数量", "单位", "备注", "门店备注"])
        for item in order["items"]:
            writer.writerow(
                [
                    order["order_id"],
                    order["submitted_at"],
                    order.get("status", "pending"),
                    order["store_name"],
                    order.get("store_address", ""),
                    item.get("purchase_channel", ""),
                    item["source"],
                    item["category"],
                    item["sku"],
                    item["name"],
                    item["spec"],
                    item["quantity"],
                    item["unit"],
                    item["note"],
                    order["remark"],
                ]
            )
