from __future__ import annotations

import csv
import base64
import hashlib
import hmac
import html
import io
import json
import os
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib import request as url_request

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles


BASE_DIR = Path(__file__).resolve().parents[1]
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"
SUBMISSION_DIR = DATA_DIR / "submissions"
ORDER_LINES_PATH = DATA_DIR / "order-lines.csv"
CATALOG_PATH = BASE_DIR / "app" / "catalog.json"
BEIJING_CATALOG_PATH = BASE_DIR / "app" / "catalog-beijing.json"
BEIJING_SUBMISSION_DIR = DATA_DIR / "beijing-submissions"
BEIJING_ORDER_LINES_PATH = DATA_DIR / "beijing-order-lines.csv"

app = FastAPI(title="Daily Order")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)
app.mount("/daily-order/static", StaticFiles(directory=STATIC_DIR), name="daily-order-static")


@app.get("/store-ops")
def store_ops_without_trailing_slash():
    return RedirectResponse(url="/store-ops/", status_code=307)


@app.get("/store-ops/")
def store_ops(request: Request):
    if _store_order_auth_enabled() and not _store_order_session(request):
        return Response(
            content=_store_order_login_page_html("熊小小门店订货系统", "/store-ops/"),
            media_type="text/html; charset=utf-8",
            headers={"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"},
        )
    return FileResponse(
        STATIC_DIR / "store-ops.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"},
    )


@app.get("/daily-order/store-ops")
def daily_order_store_ops_without_trailing_slash():
    return RedirectResponse(url="/daily-order/store-ops/", status_code=307)


@app.get("/daily-order/store-ops/")
def daily_order_store_ops(request: Request):
    if _store_order_auth_enabled() and not _store_order_session(request):
        return Response(
            content=_store_order_login_page_html("熊小小门店订货系统", "/daily-order/store-ops/"),
            media_type="text/html; charset=utf-8",
            headers={"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"},
        )
    return FileResponse(
        STATIC_DIR / "store-ops.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"},
    )


@app.get("/daily-order")
def index_without_trailing_slash():
    return RedirectResponse(url="/daily-order/", status_code=307)


@app.get("/daily-order/")
def index(request: Request):
    if _store_order_auth_enabled() and not _store_order_session(request):
        return Response(
            content=_store_order_login_page_html("熊小小成都门店订货", "/daily-order/"),
            media_type="text/html; charset=utf-8",
            headers={"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"},
        )
    return FileResponse(
        STATIC_DIR / "index.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"},
    )


@app.post("/daily-order/api/auth/login")
async def daily_order_login(request: Request, payload: dict):
    account = _verify_store_order_credentials(str(payload.get("username") or ""), str(payload.get("password") or ""))
    if not account:
        raise HTTPException(status_code=401, detail="用户名或密码不正确")
    result = Response(
        content=json.dumps({"status": "success", "store_name": account["store_name"]}, ensure_ascii=False),
        media_type="application/json",
    )
    result.set_cookie(
        "store_order_session",
        _sign_store_order_session(account["username"], account["store_name"], account.get("role", "store")),
        max_age=30 * 24 * 60 * 60,
        httponly=True,
        samesite="lax",
        secure=request.headers.get("x-forwarded-proto", request.url.scheme) == "https",
        path="/",
    )
    return result


@app.post("/daily-order/api/auth/logout")
def daily_order_logout(request: Request):
    result = Response(content=json.dumps({"status": "success"}, ensure_ascii=False), media_type="application/json")
    _clear_store_order_session_cookie(result, request)
    return result


@app.get("/daily-order/logout")
def daily_order_logout_page(request: Request):
    result = Response(
        content=_store_order_login_page_html("熊小小成都门店订货", "/daily-order/"),
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"},
    )
    _clear_store_order_session_cookie(result, request)
    return result


@app.get("/beijing-order/")
def beijing_index():
    return FileResponse(STATIC_DIR / "beijing-index.html")


@app.get("/beijing-order/admin")
def beijing_admin():
    return FileResponse(STATIC_DIR / "beijing-admin.html")


@app.get("/daily-order/admin")
def admin():
    return FileResponse(STATIC_DIR / "admin.html")


@app.get("/daily-order/api/catalog")
def catalog(request: Request):
    account = _require_store_order_auth(request)
    catalog_data = _load_catalog()
    if account and not _is_store_order_owner(account):
        catalog_data = _catalog_for_store(catalog_data, account["store_name"])
        stores = catalog_data.get("stores") or []
        verified_store = stores[0] if stores else {"name": account["store_name"], "address": "", "contact": "", "phone": ""}
        catalog_data["stores"] = stores or [verified_store]
        catalog_data["authenticated_store"] = verified_store
    return catalog_data


@app.get("/beijing-order/api/catalog")
def beijing_catalog():
    return _load_catalog(BEIJING_CATALOG_PATH)


@app.get("/daily-order/api/health")
def health():
    catalog_data = _load_catalog()
    return {"status": "ok", "item_count": len(catalog_data["items"])}


@app.get("/beijing-order/api/health")
def beijing_health():
    catalog_data = _load_catalog(BEIJING_CATALOG_PATH)
    return {"status": "ok", "item_count": len(catalog_data["items"])}


@app.post("/daily-order/api/orders")
async def submit_order(request: Request, payload: dict):
    account = _require_store_order_auth(request)
    bound_store_name = account["store_name"] if account and not _is_store_order_owner(account) else None
    return await _submit_order(request, payload, CATALOG_PATH, SUBMISSION_DIR, ORDER_LINES_PATH, "DO", True, bound_store_name)


@app.post("/beijing-order/api/orders")
async def submit_beijing_order(request: Request, payload: dict):
    return await _submit_order(request, payload, BEIJING_CATALOG_PATH, BEIJING_SUBMISSION_DIR, BEIJING_ORDER_LINES_PATH, "BJ", False)


async def _submit_order(request: Request, payload: dict, catalog_path: Path, submission_dir: Path, order_lines_path: Path, order_prefix: str, auto_process_wechat: bool, bound_store_name: str | None = None):
    catalog_data = _load_catalog(catalog_path)
    products = {item["sku"]: item for item in catalog_data["items"]}
    store_records = _store_records(catalog_data)
    stores = set(store_records)
    store_name = bound_store_name or str(payload.get("store_name") or "").strip()
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
        if not _is_orderable(product):
            raise HTTPException(status_code=400, detail=f"{product['name']} 当前库存为 0，暂时无法下单")
        min_quantity = _to_number(product.get("min_quantity"))
        if min_quantity > 0 and quantity < min_quantity:
            raise HTTPException(status_code=400, detail=f"{product['name']} 最少下单 {_format_number(min_quantity)}{product.get('unit', '')}")
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
    order_id = f"{order_prefix}-{submitted_time.strftime('%Y%m%d-%H%M%S')}-{submitted_time.strftime('%f')[:3]}"
    auto_processed_channels = _auto_processed_channels(lines) if auto_process_wechat else set()
    order_channels = set(_order_channels({"items": lines}))
    order = {
        "order_id": order_id,
        "store_name": store_name,
        "store_address": store_records.get(store_name, {}).get("address", ""),
        "remark": remark,
        "status": "processed" if auto_processed_channels and order_channels.issubset(auto_processed_channels) else "pending",
        "processed_at": now_iso() if auto_processed_channels and order_channels.issubset(auto_processed_channels) else "",
        "processed_channels": sorted(auto_processed_channels),
        "submitted_at": submitted_at,
        "client_host": request.client.host if request.client else "",
        "items": lines,
    }

    submission_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{order_id}_{_safe_name(store_name)}"
    json_path = submission_dir / f"{stem}.json"
    csv_path = submission_dir / f"{stem}.csv"
    json_path.write_text(json.dumps(order, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_order_csv(csv_path, order)
    _append_order_lines(order, order_lines_path)
    _notify_order(order)
    if auto_process_wechat and _is_wechat_addon_time(submitted_time):
        _notify_wechat_addon(order)

    return {
        "status": "success",
        "order_id": order_id,
        "line_count": len(lines),
        "submitted_at": submitted_at,
    }


@app.get("/daily-order/api/orders")
def recent_store_orders(request: Request, store_name: str, order_ids: str = ""):
    account = _require_store_order_auth(request)
    if account and not _is_store_order_owner(account):
        store_name = account["store_name"]
    return {"items": _public_store_orders(store_name, order_ids, SUBMISSION_DIR, CATALOG_PATH)}


@app.get("/beijing-order/api/orders")
def recent_beijing_store_orders(store_name: str, order_ids: str = ""):
    return {"items": _public_store_orders(store_name, order_ids, BEIJING_SUBMISSION_DIR, BEIJING_CATALOG_PATH)}


@app.get("/daily-order/api/admin/summary")
def admin_summary(request: Request, status: str = "pending", month: str = ""):
    _require_admin(request)
    return _admin_summary_from_sources(status, month, _daily_admin_sources())


@app.get("/beijing-order/api/admin/summary")
def beijing_admin_summary(request: Request, status: str = "pending", month: str = ""):
    _require_admin(request)
    return _admin_summary(status, month, BEIJING_SUBMISSION_DIR, BEIJING_CATALOG_PATH)


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


@app.get("/daily-order/api/admin/wechat-digest")
def admin_wechat_digest(request: Request, date: str = ""):
    _require_admin(request)
    day = _target_day(date)
    messages = _wechat_digest_messages(day)
    return {"date": day, "message": "\n\n".join(messages), "messages": messages, "has_orders": bool(messages)}


@app.post("/daily-order/api/admin/wechat-digest/send")
def send_admin_wechat_digest(request: Request, date: str = "", test: bool = False):
    _require_admin(request)
    day = _target_day(date)
    messages = _wechat_digest_messages(day)
    if not messages:
        return {"status": "empty", "date": day, "message": "", "messages": []}
    if test:
        messages = [f"【测试】微信群订货汇总格式预览\n{day}\n\n{message}" for message in messages]
    webhook = os.environ.get("DAILY_ORDER_WECHAT_NOTIFY_WEBHOOK", "").strip() or os.environ.get("DAILY_ORDER_NOTIFY_WEBHOOK", "").strip()
    if not webhook:
        raise HTTPException(status_code=400, detail="未配置企业微信 webhook")
    notify_type = os.environ.get("DAILY_ORDER_WECHAT_NOTIFY_TYPE", "").strip().lower() or os.environ.get("DAILY_ORDER_NOTIFY_TYPE", "wecom").strip().lower()
    for message in messages:
        _send_notify_text(webhook, notify_type, message, {"message_type": "wechat_daily_digest", "date": day})
    return {"status": "sent", "date": day, "message": "\n\n".join(messages), "messages": messages, "message_count": len(messages)}


@app.patch("/daily-order/api/admin/orders/{order_id}/status")
async def update_order_status(order_id: str, request: Request, payload: dict):
    _require_admin(request)
    return _update_order_status_from_sources(order_id, payload, _daily_admin_sources())


@app.patch("/beijing-order/api/admin/orders/{order_id}/status")
async def update_beijing_order_status(order_id: str, request: Request, payload: dict):
    _require_admin(request)
    return _update_order_status(order_id, payload, BEIJING_SUBMISSION_DIR, BEIJING_CATALOG_PATH)


@app.patch("/daily-order/api/admin/orders/{order_id}/channels/{channel}/status")
async def update_order_channel_status(order_id: str, channel: str, request: Request, payload: dict):
    _require_admin(request)
    return _update_order_channel_status_from_sources(order_id, channel, payload, _daily_admin_sources())


@app.patch("/beijing-order/api/admin/orders/{order_id}/channels/{channel}/status")
async def update_beijing_order_channel_status(order_id: str, channel: str, request: Request, payload: dict):
    _require_admin(request)
    return _update_order_channel_status(order_id, channel, payload, BEIJING_SUBMISSION_DIR, BEIJING_CATALOG_PATH)


@app.patch("/daily-order/api/admin/channels/{channel}/status")
async def update_channel_status(channel: str, request: Request, payload: dict, month: str = ""):
    _require_admin(request)
    return _update_channel_status_from_sources(channel, payload, month, _daily_admin_sources())


@app.patch("/beijing-order/api/admin/channels/{channel}/status")
async def update_beijing_channel_status(channel: str, request: Request, payload: dict, month: str = ""):
    _require_admin(request)
    return _update_channel_status(channel, payload, month, BEIJING_SUBMISSION_DIR, BEIJING_CATALOG_PATH)


def _daily_admin_sources() -> list[tuple[Path, Path]]:
    return [
        (SUBMISSION_DIR, CATALOG_PATH),
        (BEIJING_SUBMISSION_DIR, BEIJING_CATALOG_PATH),
    ]


def _admin_summary(status: str, month: str, submission_dir: Path, catalog_path: Path) -> dict:
    return _admin_summary_from_sources(status, month, [(submission_dir, catalog_path)])


def _admin_summary_from_sources(status: str, month: str, sources: list[tuple[Path, Path]]) -> dict:
    if status not in {"pending", "processed", "all"}:
        raise HTTPException(status_code=400, detail="状态不正确")
    month_scope = _target_month(month)
    all_orders = [
        order
        for submission_dir, catalog_path in sources
        for order in _read_orders(submission_dir, catalog_path)
        if _order_month(order) == month_scope
    ]
    all_orders.sort(key=lambda order: (order.get("submitted_at", ""), order.get("order_id", "")), reverse=True)
    orders = [_order_for_status(order, status) for order in all_orders]
    orders = [order for order in orders if order.get("items")]
    return {
        "status": status,
        "month": month_scope,
        "orders": orders,
        "channels": _channel_summary(orders),
        "stats": {
            "order_count": len(orders),
            "line_count": sum(len(order.get("items") or []) for order in orders),
            "pending_count": sum(1 for order in all_orders if _order_for_status(order, "pending").get("items")),
        },
    }


def _update_order_status(order_id: str, payload: dict, submission_dir: Path, catalog_path: Path) -> dict:
    return _update_order_status_from_sources(order_id, payload, [(submission_dir, catalog_path)])


def _update_order_status_from_sources(order_id: str, payload: dict, sources: list[tuple[Path, Path]]) -> dict:
    status = str(payload.get("status") or "").strip()
    if status not in {"pending", "processed"}:
        raise HTTPException(status_code=400, detail="状态不正确")
    path, catalog_path = _order_path_from_sources(order_id, sources)
    order = _normalize_order(json.loads(path.read_text(encoding="utf-8")), catalog_path)
    order["status"] = status
    order["processed_at"] = now_iso() if status == "processed" else ""
    order["processed_channels"] = _order_channels(order) if status == "processed" else []
    path.write_text(json.dumps(order, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_order_csv(path.with_suffix(".csv"), order)
    return {"status": "success", "order": _normalize_order(order, catalog_path)}


def _update_order_channel_status(order_id: str, channel: str, payload: dict, submission_dir: Path, catalog_path: Path) -> dict:
    return _update_order_channel_status_from_sources(order_id, channel, payload, [(submission_dir, catalog_path)])


def _update_order_channel_status_from_sources(order_id: str, channel: str, payload: dict, sources: list[tuple[Path, Path]]) -> dict:
    status = str(payload.get("status") or "").strip()
    if status not in {"pending", "processed"}:
        raise HTTPException(status_code=400, detail="状态不正确")
    channel = channel.strip()
    if not channel:
        raise HTTPException(status_code=400, detail="渠道不正确")
    path, catalog_path = _order_path_from_sources(order_id, sources)
    order = _normalize_order(json.loads(path.read_text(encoding="utf-8")), catalog_path)
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
    return {"status": "success", "order": _normalize_order(order, catalog_path), "channel": channel}


def _update_channel_status(channel: str, payload: dict, month: str, submission_dir: Path, catalog_path: Path) -> dict:
    return _update_channel_status_from_sources(channel, payload, month, [(submission_dir, catalog_path)])


def _update_channel_status_from_sources(channel: str, payload: dict, month: str, sources: list[tuple[Path, Path]]) -> dict:
    status = str(payload.get("status") or "").strip()
    if status not in {"pending", "processed"}:
        raise HTTPException(status_code=400, detail="状态不正确")
    channel = channel.strip()
    if not channel:
        raise HTTPException(status_code=400, detail="渠道不正确")
    month_scope = _target_month(month)
    changed = []
    for submission_dir, catalog_path in sources:
        for path in submission_dir.glob("*.json"):
            try:
                order = _normalize_order(json.loads(path.read_text(encoding="utf-8")), catalog_path)
            except Exception:
                continue
            if _order_month(order) != month_scope:
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
    return {"status": "success", "channel": channel, "month": month_scope, "order_count": len(changed), "order_ids": changed}


def _order_path_from_sources(order_id: str, sources: list[tuple[Path, Path]]) -> tuple[Path, Path]:
    for submission_dir, catalog_path in sources:
        path = _order_path(order_id, submission_dir)
        if path is not None:
            return path, catalog_path
    raise HTTPException(status_code=404, detail="订单不存在")


def _load_catalog(path: Path | None = None) -> dict:
    path = path or CATALOG_PATH
    return json.loads(path.read_text(encoding="utf-8"))


def _is_orderable(product: dict) -> bool:
    if product.get("orderable") is False:
        return False
    if "stock_quantity" in product and _to_number(product.get("stock_quantity")) <= 0:
        return False
    return True


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
    if source == "山姆配送":
        return "山姆配送"
    if source == "同城物流配送":
        return "微信群"
    if source == "厂家配送（2日内）":
        return "微信群"
    category = product.get("category")
    if category in {"耗材", "包材"}:
        return "拼多多"
    return "淘宝"


def _purchase_channel(product: dict) -> str:
    if product.get("force_purchase_channel") and product.get("purchase_channel"):
        return str(product["purchase_channel"])
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


def _target_day(value: str = "") -> str:
    value = (value or "").strip()
    return value if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) else datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")


def _target_month(value: str = "") -> str:
    value = (value or "").strip()
    return value if re.fullmatch(r"\d{4}-\d{2}", value) else datetime.now(timezone.utc).astimezone().strftime("%Y-%m")


def _order_day(order: dict) -> str:
    submitted_at = str(order.get("submitted_at") or "")
    return submitted_at[:10] if len(submitted_at) >= 10 else ""


def _order_month(order: dict) -> str:
    day = _order_day(order)
    return day[:7] if len(day) >= 7 else ""


def _read_orders(submission_dir: Path | None = None, catalog_path: Path | None = None) -> list[dict]:
    submission_dir = submission_dir or SUBMISSION_DIR
    catalog_path = catalog_path or CATALOG_PATH
    submission_dir.mkdir(parents=True, exist_ok=True)
    orders = []
    for path in submission_dir.glob("*.json"):
        try:
            orders.append(_normalize_order(json.loads(path.read_text(encoding="utf-8")), catalog_path))
        except Exception:
            continue
    orders.sort(key=lambda order: (order.get("submitted_at", ""), order.get("order_id", "")), reverse=True)
    return orders


def _public_store_orders(store_name: str, order_ids: str, submission_dir: Path, catalog_path: Path) -> list[dict]:
    clean_store_name = store_name.strip()
    if not clean_store_name:
        raise HTTPException(status_code=400, detail="请选择门店")
    allowed_ids = _public_order_id_set(order_ids)
    if not allowed_ids:
        return []
    orders = []
    for order in _read_orders(submission_dir, catalog_path):
        if order.get("store_name") != clean_store_name or order.get("order_id") not in allowed_ids:
            continue
        orders.append(_public_order_view(order))
    return orders


def _public_order_id_set(raw_order_ids: str) -> set[str]:
    ids: set[str] = set()
    for item in re.split(r"[,\s]+", raw_order_ids.strip()):
        clean = item.strip()[:80]
        if clean and re.fullmatch(r"[A-Za-z0-9_.:-]+", clean):
            ids.add(clean)
        if len(ids) >= 20:
            break
    return ids


def _public_order_view(order: dict) -> dict:
    return {
        "order_id": order.get("order_id") or "",
        "store_name": order.get("store_name") or "",
        "remark": order.get("remark") or "",
        "status": order.get("status") or "pending",
        "processed_at": order.get("processed_at") or "",
        "processed_channels": list(order.get("processed_channels") or []),
        "submitted_at": order.get("submitted_at") or "",
        "items": list(order.get("items") or []),
    }


def _normalize_order(order: dict, catalog_path: Path | None = None) -> dict:
    catalog_path = catalog_path or CATALOG_PATH
    order.setdefault("status", "pending")
    order.setdefault("processed_at", "")
    order.setdefault("store_address", "")
    products = {}
    if not order["store_address"] and order.get("store_name"):
        try:
            catalog_data = _load_catalog(catalog_path)
            products = {item["sku"]: item for item in catalog_data.get("items", [])}
            order["store_address"] = _store_records(catalog_data).get(order["store_name"], {}).get("address", "")
        except Exception:
            order["store_address"] = ""
    elif order.get("items"):
        try:
            products = {item["sku"]: item for item in _load_catalog(catalog_path).get("items", [])}
        except Exception:
            products = {}
    for item in order.get("items") or []:
        product = products.get(item.get("sku"), item)
        item["purchase_channel"] = _purchase_channel(product)
    channels = _order_channels(order)
    if "processed_channels" not in order:
        processed_channels = set(channels if order.get("status") == "processed" else [])
        order["processed_channels"] = sorted(processed_channels)
    else:
        processed_channels = set(order.get("processed_channels") or [])
        migrated_channels = {channel for channel in processed_channels if channel in channels}
        if "微信群" in processed_channels:
            migrated_channels.update(channel for channel in channels if "群" in channel or channel == "微信群")
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
    if item.get("purchase_channel"):
        return str(item["purchase_channel"])
    wechat_group = _wechat_group_channel(str(item.get("name") or ""), str(item.get("sku") or ""))
    if wechat_group:
        return wechat_group
    return item.get("purchase_channel") or _default_purchase_channel(item)


def _display_channel(channel: str) -> str:
    return "微信群" if "群" in channel else channel


def _matching_order_channels(channels: list[str], display_channel: str) -> set[str]:
    return {channel for channel in channels if channel == display_channel or _display_channel(channel) == display_channel}


def _channel_sort_key(channel: dict) -> tuple[int, str]:
    order = {"快驴": 0, "山姆配送": 1, "微信群": 2, "工作餐": 3, "淘宝": 4, "拼多多": 5, "京东": 6}
    name = str(channel.get("channel") or "")
    return (order.get(name, 99), name)


def _catalog_for_store(catalog_data: dict, store_name: str) -> dict:
    result = dict(catalog_data)
    stores = catalog_data.get("stores") or []
    if stores and isinstance(stores[0], dict):
        result["stores"] = [store for store in stores if store.get("name") == store_name]
    else:
        result["stores"] = [store for store in stores if str(store) == store_name]
    return result


def _store_order_accounts() -> dict[str, dict]:
    raw = os.environ.get("STORE_ORDER_ACCOUNTS_JSON", "").strip()
    if not raw:
        path = Path(os.environ.get("STORE_ORDER_ACCOUNTS_FILE", "/etc/store-order-accounts.json"))
        if path.exists():
            raw = path.read_text(encoding="utf-8")
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    accounts = payload.get("accounts") if isinstance(payload, dict) else payload
    if not isinstance(accounts, dict):
        return {}
    clean = {}
    for username, item in accounts.items():
        if not isinstance(item, dict):
            continue
        password = str(item.get("password") or "")
        store_name = str(item.get("store_name") or "")
        role = str(item.get("role") or "").strip().lower()
        all_stores = bool(item.get("all_stores")) or role in {"owner", "super", "admin"}
        if username and password and (store_name or all_stores):
            clean[str(username)] = {
                "username": str(username),
                "password": password,
                "store_name": store_name,
                "role": "owner" if all_stores else "store",
                "all_stores": all_stores,
            }
    return clean


def _store_order_auth_configured() -> bool:
    return bool(
        os.environ.get("STORE_ORDER_ACCOUNTS_JSON", "").strip()
        or os.environ.get("STORE_ORDER_ACCOUNTS_FILE", "").strip()
        or Path("/etc/store-order-accounts.json").exists()
    )


def _store_order_auth_enabled() -> bool:
    return _store_order_auth_configured() or bool(_store_order_accounts())


def _store_order_auth_secret() -> str:
    secret = os.environ.get("STORE_ORDER_AUTH_SECRET", "")
    if secret:
        return secret
    material = json.dumps(_store_order_accounts(), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _verify_store_order_credentials(username: str, password: str) -> dict | None:
    account = _store_order_accounts().get(username.strip())
    if not account:
        return None
    if not secrets.compare_digest(password, account["password"]):
        return None
    return account


def _is_store_order_owner(account: dict | None) -> bool:
    return bool(account and (account.get("all_stores") or account.get("role") in {"owner", "super", "admin"}))


def _sign_store_order_session(username: str, store_name: str, role: str = "store") -> str:
    expires = int(time.time()) + 30 * 24 * 60 * 60
    payload = base64.urlsafe_b64encode(
        json.dumps({"username": username, "store_name": store_name, "role": role, "expires": expires}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    signature = hmac.new(_store_order_auth_secret().encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def _store_order_session(request: Request) -> dict | None:
    cookie = request.cookies.get("store_order_session", "")
    if not cookie:
        return None
    try:
        payload, signature = cookie.rsplit(".", 1)
        data = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")).decode("utf-8"))
        username = str(data.get("username") or "")
        store_name = str(data.get("store_name") or "")
        expires = int(data.get("expires") or 0)
    except Exception:
        return None
    if expires < int(time.time()):
        return None
    account = _store_order_accounts().get(username)
    if not account or account["store_name"] != store_name:
        return None
    expected = hmac.new(_store_order_auth_secret().encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not secrets.compare_digest(signature, expected):
        return None
    return {
        "username": username,
        "store_name": store_name,
        "role": account.get("role", "store"),
        "all_stores": bool(account.get("all_stores")),
    }


def _require_store_order_auth(request: Request) -> dict | None:
    if not _store_order_auth_enabled():
        return None
    account = _store_order_session(request)
    if account:
        return account
    raise HTTPException(status_code=401, detail="需要门店登录")


def _clear_store_order_session_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(
        "store_order_session",
        path="/",
        samesite="lax",
        secure=request.headers.get("x-forwarded-proto", request.url.scheme) == "https",
    )


def _store_order_login_page_html(title: str, next_path: str) -> str:
    safe_title = html.escape(title, quote=True)
    safe_next = html.escape(next_path, quote=True)
    return f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
    <title>{safe_title}登录</title>
    <style>
      :root {{ color-scheme: light; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
      * {{ box-sizing: border-box; }}
      html {{ min-height: 100%; }}
      body {{ margin: 0; min-height: 100vh; min-height: 100dvh; display: grid; place-items: center; padding: max(16px, env(safe-area-inset-top)) max(16px, env(safe-area-inset-right)) max(16px, env(safe-area-inset-bottom)) max(16px, env(safe-area-inset-left)); background: #f6f7f4; color: #17201b; overflow-x: hidden; }}
      main {{ width: min(420px, 100%); max-height: calc(100dvh - 32px); overflow: auto; -webkit-overflow-scrolling: touch; padding: 26px; border: 1px solid #d9ded3; border-radius: 8px; background: #fff; box-shadow: 0 18px 44px rgba(22, 32, 27, .14); }}
      h1 {{ margin: 0 0 8px; font-size: 24px; line-height: 1.2; }}
      p {{ margin: 0 0 20px; color: #64705f; font-size: 14px; line-height: 1.5; }}
      form {{ display: grid; gap: 14px; }}
      label {{ display: grid; gap: 6px; color: #3f4c42; font-size: 13px; font-weight: 800; }}
      input {{ width: 100%; min-height: 44px; border: 1px solid #cfd8cc; border-radius: 8px; padding: 9px 12px; font: inherit; font-size: 16px; }}
      button {{ min-height: 44px; border: 0; border-radius: 8px; background: #2f6f4e; color: #fff; font: inherit; font-weight: 900; cursor: pointer; }}
      button:disabled {{ cursor: not-allowed; opacity: .65; }}
      .message {{ min-height: 20px; color: #b42318; font-size: 13px; font-weight: 800; }}
      @media (max-width: 420px) {{
        body {{ align-items: start; padding-top: max(12px, env(safe-area-inset-top)); }}
        main {{ padding: 20px; }}
        h1 {{ font-size: 22px; }}
        p {{ margin-bottom: 16px; }}
      }}
      @media (max-height: 520px) {{
        body {{ align-items: start; }}
        main {{ padding: 18px; }}
        form {{ gap: 10px; }}
        p {{ margin-bottom: 12px; }}
      }}
    </style>
  </head>
  <body>
    <main>
      <h1>{safe_title}</h1>
      <p>请输入门店账号密码。登录后会自动匹配门店。</p>
      <form id="loginForm">
        <label>账号<input name="username" autocomplete="username" required /></label>
        <label>密码<input name="password" type="password" autocomplete="current-password" required /></label>
        <button type="submit">登录</button>
        <div class="message" id="message"></div>
      </form>
    </main>
    <script>
      const nextPath = "{safe_next}";
      const form = document.querySelector("#loginForm");
      const message = document.querySelector("#message");
      form.addEventListener("submit", async (event) => {{
        event.preventDefault();
        const button = form.querySelector("button");
        button.disabled = true;
        message.textContent = "正在登录...";
        const data = Object.fromEntries(new FormData(form).entries());
        try {{
          const response = await fetch("/daily-order/api/auth/login", {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify(data),
          }});
          const payload = await response.json().catch(() => ({{}}));
          if (!response.ok) throw new Error(payload.detail || "登录失败");
          window.location.href = nextPath || "/daily-order/";
        }} catch (error) {{
          message.textContent = error.message || "登录失败";
        }} finally {{
          button.disabled = false;
        }}
      }});
    </script>
  </body>
</html>"""


def _auto_processed_channels(items: list[dict]) -> set[str]:
    return {_item_channel(item) for item in items if _display_channel(_item_channel(item)) == "微信群"}


def _channel_is_processed(order: dict, channel: str) -> bool:
    return channel in set(order.get("processed_channels") or [])


def _order_path(order_id: str, submission_dir: Path | None = None) -> Path | None:
    submission_dir = submission_dir or SUBMISSION_DIR
    safe_id = Path(order_id).name
    return next(submission_dir.glob(f"{safe_id}_*.json"), None)


def _channel_summary(orders: list[dict]) -> list[dict]:
    channels: dict[str, dict] = {}
    for order in orders:
        for item in order.get("items") or []:
            item_channel = item.get("purchase_channel") or _default_purchase_channel(item)
            channel_name = _display_channel(item_channel)
            channel = channels.setdefault(channel_name, {"channel": channel_name, "stores": {}, "orders": {}, "totals": {}})
            order_day = _order_day(order)
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
            aggregate_key = f"{order_day}||{order['store_name']}"
            channel_order = channel["orders"].setdefault(
                aggregate_key,
                {
                    "order_id": f"{order_day or '未记录日期'} {order['store_name']}",
                    "order_ids": [],
                    "order_day": order_day,
                    "store_name": order["store_name"],
                    "store_address": order.get("store_address", ""),
                    "submitted_at": order.get("submitted_at", ""),
                    "last_submitted_at": order.get("submitted_at", ""),
                    "remark": order.get("remark", ""),
                    "status": "processed",
                    "items": {},
                },
            )
            if order["order_id"] not in channel_order["order_ids"]:
                channel_order["order_ids"].append(order["order_id"])
            if str(order.get("submitted_at", "")) > str(channel_order.get("last_submitted_at", "")):
                channel_order["last_submitted_at"] = order.get("submitted_at", "")
                channel_order["submitted_at"] = order.get("submitted_at", "")
            if order.get("remark"):
                remarks = [remark for remark in str(channel_order.get("remark", "")).split("；") if remark]
                if order["remark"] not in remarks:
                    remarks.append(order["remark"])
                channel_order["remark"] = "；".join(remarks)
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
            if not _channel_is_processed(order, item_channel):
                line["status"] = "pending"
            order_line = channel_order["items"].setdefault(sku, {**line, "quantity": 0})
            order_line["quantity"] += float(item.get("quantity") or 0)
            if not _channel_is_processed(order, item_channel):
                order_line["status"] = "pending"
            total = channel["totals"].setdefault(sku, {**line, "quantity": 0})
            total["quantity"] += float(item.get("quantity") or 0)
            if not _channel_is_processed(order, item_channel):
                total["status"] = "pending"
    return sorted([
        {
            "channel": channel["channel"],
            "orders": [
                {**order, "items": list(order["items"].values())}
                for order in sorted(channel["orders"].values(), key=lambda item: (item.get("last_submitted_at", ""), item.get("order_id", "")), reverse=True)
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


def _notify_wechat_addon(order: dict) -> None:
    webhook = os.environ.get("DAILY_ORDER_WECHAT_NOTIFY_WEBHOOK", "").strip() or os.environ.get("DAILY_ORDER_NOTIFY_WEBHOOK", "").strip()
    if not webhook:
        return
    notify_type = os.environ.get("DAILY_ORDER_WECHAT_NOTIFY_TYPE", "").strip().lower() or os.environ.get("DAILY_ORDER_NOTIFY_TYPE", "wecom").strip().lower()
    for text in _wechat_addon_messages(order):
        _send_notify_text(webhook, notify_type, text, {"order": order, "message_type": "wechat_addon_order"})


def _wechat_digest_message(day: str) -> str:
    return "\n\n".join(_wechat_digest_messages(day))


def _wechat_digest_messages(day: str) -> list[str]:
    groups: dict[str, dict[str, dict[str, dict]]] = {}
    for order in _read_orders():
        if _order_day(order) != day:
            continue
        store_name = order.get("store_name") or "未命名门店"
        for item in order.get("items") or []:
            item_channel = _item_channel(item)
            if _display_channel(item_channel) != "微信群":
                continue
            stores = groups.setdefault(item_channel, {})
            items = stores.setdefault(store_name, {})
            item_key = f"{item.get('sku', '')}||{item.get('name', '')}||{item.get('unit', '')}"
            line = items.setdefault(
                item_key,
                {
                    "name": item.get("name", ""),
                    "unit": item.get("unit", ""),
                    "quantity": 0,
                },
            )
            line["quantity"] += _to_number(item.get("quantity"))
    messages = []
    for group_name in sorted(groups):
        lines = [f"【{group_name}】"]
        for store_name in sorted(groups[group_name]):
            item_text = "、".join(_plain_digest_line(item) for item in groups[group_name][store_name].values())
            lines.append(f"{store_name}：{item_text}")
        messages.append("\n".join(lines))
    return messages


def _plain_digest_line(item: dict) -> str:
    return f"{item.get('name', '')} {_format_number(item.get('quantity'))}{item.get('unit') or ''}"


def _is_wechat_addon_time(submitted_time: datetime) -> bool:
    return 18 <= submitted_time.hour < 24


def _wechat_addon_messages(order: dict) -> list[str]:
    groups: dict[str, dict[str, dict[str, dict]]] = {}
    store_name = order.get("store_name") or "未命名门店"
    for item in order.get("items") or []:
        item_channel = _item_channel(item)
        if _display_channel(item_channel) != "微信群":
            continue
        stores = groups.setdefault(item_channel, {})
        items = stores.setdefault(store_name, {})
        item_key = f"{item.get('sku', '')}||{item.get('name', '')}||{item.get('unit', '')}"
        line = items.setdefault(
            item_key,
            {
                "name": item.get("name", ""),
                "unit": item.get("unit", ""),
                "quantity": 0,
            },
        )
        line["quantity"] += _to_number(item.get("quantity"))
    messages = []
    for group_name in sorted(groups):
        lines = [f"【{group_name} 加单】"]
        for current_store_name in sorted(groups[group_name]):
            item_text = "、".join(_plain_digest_line(item) for item in groups[group_name][current_store_name].values())
            lines.append(f"{current_store_name}：{item_text}")
        messages.append("\n".join(lines))
    return messages


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
            "",
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


def _append_order_lines(order: dict, order_lines_path: Path | None = None) -> None:
    order_lines_path = order_lines_path or ORDER_LINES_PATH
    order_lines_path.parent.mkdir(parents=True, exist_ok=True)
    exists = order_lines_path.exists()
    with order_lines_path.open("a", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=ORDER_LINE_HEADERS)
        if not exists or order_lines_path.stat().st_size == 0:
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
