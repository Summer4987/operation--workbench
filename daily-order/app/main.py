from __future__ import annotations

import csv
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib import request as url_request

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


BASE_DIR = Path(__file__).resolve().parents[1]
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"
SUBMISSION_DIR = DATA_DIR / "submissions"
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
        if not product or quantity <= 0:
            continue
        lines.append(
            {
                "sku": sku,
                "source": product["source"],
                "purchase_channel": product.get("purchase_channel") or _default_purchase_channel(product),
                "category": product["category"],
                "name": product["name"],
                "spec": product["spec"],
                "unit": product["unit"],
                "note": product["note"],
                "quantity": quantity,
            }
        )

    if not lines:
        raise HTTPException(status_code=400, detail="请至少填写一个订货数量")

    submitted_time = datetime.now(timezone.utc).astimezone()
    submitted_at = submitted_time.isoformat(timespec="seconds")
    order_id = f"DO-{submitted_time.strftime('%Y%m%d-%H%M%S')}-{submitted_time.strftime('%f')[:3]}"
    order = {
        "order_id": order_id,
        "store_name": store_name,
        "store_address": store_records.get(store_name, {}).get("address", ""),
        "remark": remark,
        "status": "pending",
        "processed_at": "",
        "processed_channels": [],
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
    _notify_order(order)

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
        if channel not in channels:
            continue
        processed_channels = set(order.get("processed_channels") or [])
        if status == "processed":
            processed_channels.add(channel)
        else:
            processed_channels.discard(channel)
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
        item.setdefault("purchase_channel", product.get("purchase_channel") or _default_purchase_channel(product))
    if "processed_channels" not in order:
        order["processed_channels"] = _order_channels(order) if order.get("status") == "processed" else []
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
    return item.get("purchase_channel") or _default_purchase_channel(item)


def _channel_is_processed(order: dict, channel: str) -> bool:
    return channel in set(order.get("processed_channels") or [])


def _order_path(order_id: str) -> Path | None:
    safe_id = Path(order_id).name
    return next(SUBMISSION_DIR.glob(f"{safe_id}_*.json"), None)


def _channel_summary(orders: list[dict]) -> list[dict]:
    channels: dict[str, dict] = {}
    for order in orders:
        for item in order.get("items") or []:
            channel_name = item.get("purchase_channel") or _default_purchase_channel(item)
            channel = channels.setdefault(channel_name, {"channel": channel_name, "stores": {}, "totals": {}})
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
            sku = item["sku"]
            line = store["items"].setdefault(
                sku,
                {
                    "sku": sku,
                    "name": item["name"],
                    "spec": item.get("spec", ""),
                    "unit": item.get("unit", ""),
                    "quantity": 0,
                },
            )
            line["quantity"] += float(item.get("quantity") or 0)
            total = channel["totals"].setdefault(sku, {**line, "quantity": 0})
            total["quantity"] += float(item.get("quantity") or 0)
    return [
        {
            "channel": channel["channel"],
            "stores": [
                {**store, "orders": sorted(set(store["orders"])), "items": list(store["items"].values())}
                for store in channel["stores"].values()
            ],
            "totals": list(channel["totals"].values()),
        }
        for channel in channels.values()
    ]


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
    if notify_type == "wecom":
        payload = {"msgtype": "text", "text": {"content": text}}
    elif notify_type == "feishu":
        payload = {"msg_type": "text", "content": {"text": text}}
    elif notify_type == "dingtalk":
        payload = {"msgtype": "text", "text": {"content": text}}
    else:
        payload = {"text": text, "order": order}
    try:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = url_request.Request(webhook, data=body, headers={"Content-Type": "application/json"})
        url_request.urlopen(req, timeout=8).read()
    except Exception:
        pass


def _order_message(order: dict) -> str:
    message = os.environ.get("DAILY_ORDER_NOTIFY_MESSAGE", "").strip()
    if message:
        return message
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
