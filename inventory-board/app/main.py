from __future__ import annotations

import hashlib
import html
import hmac
import base64
import json
import os
import re
import secrets
import shutil
import subprocess
import time
from urllib import request as url_request
from urllib.parse import quote
from decimal import Decimal
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from . import agent_inbox, agent_wecom
from .db import (
    connect,
    create_import,
    delivery_months,
    finish_import,
    inventory_flow_summary,
    inventory_warning_items,
    init_db,
    inventory_summary,
    now_iso,
    recent_imports,
    recent_movements,
    set_warning_threshold,
    store_delivery_summary,
    upsert_product,
)
from .order_generator import (
    OUTPUT_DIR,
    TEMPLATE_PATH,
    OrderParseError,
    generate_outbound_order,
    generate_structured_outbound_order,
    preview_wechat_order,
    public_order_catalog,
)
from .parser import ParseError, parse_inventory_file, parse_product_catalog
from .feishu_inventory import FeishuInventoryError, sync_inventory


BASE_DIR = Path(__file__).resolve().parents[1]
UPLOAD_DIR = BASE_DIR / "data" / "uploads"
STATIC_DIR = BASE_DIR / "static"
TEMPLATE_DIR = BASE_DIR / "data" / "templates"
PROMO_BUDGET_PATH = BASE_DIR / "data" / "promo_budget_overrides.json"
PUBLIC_ORDER_MIN_TOTAL_QUANTITY = 5
ORDER_FILE_DOWNLOAD_TTL_SECONDS = 7 * 24 * 60 * 60
AGENT_STATUS_PATH = Path(os.environ.get("AGENT_STATUS_PATH", "/var/www/html/operation-workbench/outputs/agent_mobile/latest.json"))
AGENT_RECENT_TASK_MAX_AGE_SECONDS = 24 * 60 * 60

app = FastAPI(title="Inventory Board")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def password_gate(request: Request, call_next):
    password = os.environ.get("INVENTORY_PASSWORD", "")
    if _is_public_request(request):
        return await call_next(request)
    if not password:
        return await call_next(request)
    if _operation_session_valid(request):
        return await call_next(request)

    if _basic_auth_valid(request):
        return await call_next(request)

    return Response(status_code=401, content="需要登录")


@app.on_event("startup")
def startup() -> None:
    init_db()
    seed_catalog()


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/order-submit")
def public_order_submit(request: Request):
    _require_public_order_token(request)
    account = _store_order_session(request) if _store_order_auth_enabled() else None
    if _store_order_auth_enabled() and not account:
        return Response(
            content=_store_order_login_page_html("熊小小日配订货", "/order-submit", request),
            media_type="text/html; charset=utf-8",
            headers={"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"},
        )
    if account:
        return Response(
            content=_order_submit_page_html(account),
            media_type="text/html; charset=utf-8",
            headers={"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"},
        )
    return FileResponse(
        STATIC_DIR / "order-submit.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"},
    )


@app.get("/login")
def operation_login_page(next: str = "/operation-workbench/"):
    return Response(content=_login_page_html(next), media_type="text/html; charset=utf-8")


@app.post("/api/auth/login")
async def operation_login(request: Request, payload: dict):
    username = str(payload.get("username") or "")
    password = str(payload.get("password") or "")
    if not secrets.compare_digest(username, _operation_auth_username()) or not secrets.compare_digest(password, os.environ.get("INVENTORY_PASSWORD", "")):
        raise HTTPException(status_code=401, detail="用户名或密码不正确")
    response = {"status": "success"}
    cookie = _sign_operation_session(username)
    result = Response(content=json.dumps(response, ensure_ascii=False), media_type="application/json")
    result.set_cookie(
        "operation_session",
        cookie,
        max_age=30 * 24 * 60 * 60,
        httponly=True,
        samesite="lax",
        secure=request.headers.get("x-forwarded-proto", request.url.scheme) == "https",
        path="/",
    )
    return result


@app.get("/api/auth/check")
def operation_auth_check(request: Request):
    if _operation_session_valid(request):
        return Response(status_code=204)
    raise HTTPException(status_code=401, detail="需要登录")


@app.get("/agent-wecom/callback")
def agent_wecom_verify(request: Request):
    settings = agent_wecom.callback_settings()
    if not agent_wecom.configured(settings):
        raise HTTPException(status_code=503, detail="企业微信 Agent 回调未配置")
    try:
        plain = agent_wecom.verify_url(
            msg_signature=request.query_params.get("msg_signature", ""),
            timestamp=request.query_params.get("timestamp", ""),
            nonce=request.query_params.get("nonce", ""),
            echostr=request.query_params.get("echostr", ""),
            settings=settings,
        )
    except agent_wecom.WeComCallbackError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return PlainTextResponse(plain)


@app.post("/agent-wecom/callback")
async def agent_wecom_callback(request: Request):
    settings = agent_wecom.callback_settings()
    if not agent_wecom.configured(settings):
        raise HTTPException(status_code=503, detail="企业微信 Agent 回调未配置")
    body = (await request.body()).decode("utf-8", "replace")
    try:
        response_xml = agent_wecom.handle_callback_post(
            body=body,
            msg_signature=request.query_params.get("msg_signature", ""),
            timestamp=request.query_params.get("timestamp", ""),
            nonce=request.query_params.get("nonce", ""),
            settings=settings,
        )
    except agent_wecom.WeComCallbackError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return Response(content=response_xml, media_type="application/xml; charset=utf-8")


def _require_agent_inbox_token(request: Request) -> None:
    token = request.query_params.get("token", "") or request.headers.get("x-agent-inbox-token", "")
    if not agent_inbox.token_valid(token):
        raise HTTPException(status_code=403, detail="invalid agent inbox token")


@app.get("/agent-wecom/inbox/pending")
def agent_inbox_pending(request: Request, limit: int = 5):
    _require_agent_inbox_token(request)
    return {"items": agent_inbox.pending_tasks(limit=limit)}


@app.post("/agent-wecom/inbox/claim")
async def agent_inbox_claim(request: Request, payload: dict):
    _require_agent_inbox_token(request)
    item = agent_inbox.claim_task(str(payload.get("id") or ""), worker=str(payload.get("worker") or "macmini"))
    if not item:
        raise HTTPException(status_code=404, detail="task not pending")
    return {"item": item}


@app.post("/agent-wecom/inbox/complete")
async def agent_inbox_complete(request: Request, payload: dict):
    _require_agent_inbox_token(request)
    item = agent_inbox.complete_task(
        str(payload.get("id") or ""),
        status=str(payload.get("status") or "failed"),
        result=payload.get("result") if isinstance(payload.get("result"), dict) else {},
    )
    if not item:
        raise HTTPException(status_code=404, detail="task not found")
    return {"item": item}


@app.get("/agent")
def agent_mobile_page():
    return Response(
        content=_agent_mobile_page_html(),
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"},
    )


@app.get("/agent/api/status")
def agent_mobile_status(request: Request, limit: int = 20):
    _require_agent_inbox_token(request)
    items = _agent_recent_visible_tasks(limit=limit)
    return {
        "generated_at": int(time.time()),
        "summary": _agent_task_summary(items),
        "queue_summary": agent_inbox.task_summary(),
        "mobile": _agent_mobile_status_payload(),
        "realtime": _agent_realtime_summary(),
        "items": [_public_agent_task(item) for item in items],
    }


@app.post("/agent/api/send")
async def agent_mobile_send(request: Request, payload: dict):
    _require_agent_inbox_token(request)
    text = " ".join(str(payload.get("text") or "").split())
    if not text:
        raise HTTPException(status_code=400, detail="消息不能为空")
    policy = agent_inbox.command_policy(text)
    if policy.get("intent") == "blocked_ordering" or not policy.get("enqueue"):
        return {
            "mode": "answer",
            "answer": agent_wecom.answer_agent_text(text),
            "policy": policy,
            "task": None,
        }
    item = agent_inbox.append_task(
        text=text,
        intent=str(policy.get("intent") or ""),
        execute=bool(policy.get("execute")),
        source="agent-mobile",
        sender=str(payload.get("sender") or "mobile"),
    )
    return {
        "mode": "queued",
        "answer": _agent_queue_answer(item),
        "policy": policy,
        "task": _public_agent_task(item),
    }


@app.get("/api/summary")
def summary():
    items = inventory_summary()
    warning_count = sum(1 for item in items if float(item["balance"]) <= float(item["warning_threshold"]))
    return {
        "items": [_public_inventory_item(item) for item in items],
        "stats": {
            "product_count": len(items),
            "warning_count": warning_count,
            "total_balance": sum(float(item["balance"]) for item in items),
        },
    }


@app.post("/api/feishu/inventory-sync")
def feishu_inventory_sync():
    try:
        return sync_inventory(inventory_summary())
    except FeishuInventoryError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/imports")
def imports():
    return {"items": recent_imports()}


@app.get("/api/movements")
def movements():
    return {"items": recent_movements()}


@app.get("/api/store-deliveries")
def store_deliveries(month: Optional[str] = None):
    months = delivery_months()
    selected_month = month or (months[0] if months else "")
    return {
        "items": store_delivery_summary(selected_month if selected_month else None),
        "months": months,
        "selected_month": selected_month,
    }


@app.get("/api/inventory/flow")
def inventory_flow(month: Optional[str] = None, limit: int = 80):
    clean_month = (month or "").strip()[:7]
    clean_limit = max(1, min(int(limit or 80), 200))
    return inventory_flow_summary(clean_month or None, clean_limit)


@app.get("/api/inbound-template")
def inbound_template():
    path = _inbound_template_path()
    if path is None:
        raise HTTPException(status_code=404, detail="还没有配置入库模板文件")
    return FileResponse(path, filename=path.name)


@app.get("/api/inbound-template/status")
def inbound_template_status():
    path = _inbound_template_path()
    return {
        "available": bool(path),
        "filename": path.name if path else "",
        "download_url": "/api/inbound-template" if path else "",
        "expected_sheet": "Sheet1",
        "required_headers": ["商品编码", "商品名称", "物料规格", "到货数量", "单位"],
        "hint": (
            "可直接下载并填写入库模板。"
            if path
            else f"请把入库模板放到 {TEMPLATE_DIR / '入库模板.xlsx'}，或用 INVENTORY_TEMPLATE_PATH 指向现有模板目录。"
        ),
    }


@app.post("/api/inventory/warnings/notify")
def notify_daily_inventory_warnings(request: Request):
    _require_agent_inbox_token(request)
    return _notify_inventory_warning_daily(source="每日16:00库存预警汇总")


@app.get("/api/promo-budget-overrides")
def promo_budget_overrides(request: Request):
    _require_operation_auth(request)
    return _read_promo_budget_overrides()


@app.post("/api/promo-budget-overrides")
async def save_promo_budget_overrides(request: Request, payload: dict):
    _require_operation_auth(request)
    data = _validate_promo_budget_overrides(payload)
    PROMO_BUDGET_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROMO_BUDGET_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"status": "success", "data": data}


@app.post("/api/import")
async def import_file(movement_type: str = Form(...), file: UploadFile = File(...)):
    if movement_type not in {"inbound", "outbound"}:
        raise HTTPException(status_code=400, detail="请选择入库或出库")
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="请上传 Excel 文件")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    saved_path = UPLOAD_DIR / f"{now_iso().replace(':', '-')}_{Path(file.filename).name}"
    with saved_path.open("wb") as target:
        shutil.copyfileobj(file.file, target)

    file_hash = _sha256(saved_path)
    try:
        lines = parse_inventory_file(saved_path, movement_type)
    except ParseError as exc:
        with connect() as conn:
            import_id = create_import(
                conn,
                file_hash=file_hash,
                filename=file.filename,
                movement_type=movement_type,
                source="manual_upload",
            )
            if import_id:
                finish_import(conn, import_id, status="failed", line_count=0, message=str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with connect() as conn:
        unknown_skus = _unknown_import_skus(conn, lines)
        if unknown_skus:
            message = f"导入文件包含未知 SKU，请先维护商品资料后再导入：{', '.join(unknown_skus)}"
            import_id = create_import(
                conn,
                file_hash=file_hash,
                filename=file.filename,
                movement_type=movement_type,
                source="manual_upload",
            )
            if import_id:
                finish_import(conn, import_id, status="failed", line_count=0, message=message)
            raise HTTPException(status_code=400, detail=message)

        import_id = create_import(
            conn,
            file_hash=file_hash,
            filename=file.filename,
            movement_type=movement_type,
            source="manual_upload",
        )
        if import_id is None:
            return {"status": "duplicate", "message": "这个文件已经导入过，不会重复计算库存。"}

        inserted = 0
        for line in lines:
            upsert_product(
                conn,
                sku=line.sku,
                name=line.name or line.sku,
                spec=line.spec,
                unit=line.unit,
                warehouse=line.warehouse,
            )
            signed_quantity = line.quantity if movement_type == "inbound" else -line.quantity
            row_key = f"{file_hash}:{line.row_number}:{line.sku}:{line.quantity}"
            conn.execute(
                """
                INSERT OR IGNORE INTO movements (
                    import_file_id, row_key, movement_type, sku, name, spec, unit, warehouse, address, store_name,
                    quantity, signed_quantity, document_date, source_row, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    import_id,
                    row_key,
                    movement_type,
                    line.sku,
                    line.name or line.sku,
                    line.spec,
                    line.unit,
                    line.warehouse,
                    line.address,
                    line.store_name,
                    float(line.quantity),
                    float(signed_quantity),
                    line.document_date,
                    line.row_number,
                    now_iso(),
                ),
            )
            inserted += 1
        finish_import(conn, import_id, status="success", line_count=inserted)

    _notify_inventory_warning_for_skus(
        {line.sku for line in lines},
        source="库存入库导入" if movement_type == "inbound" else "库存出库导入",
    )
    return {"status": "success", "line_count": inserted}


@app.patch("/api/products/{sku}/warning")
async def update_warning(sku: str, payload: dict):
    try:
        threshold = Decimal(str(payload.get("warning_threshold", "")))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="预警值必须是数字") from exc
    if threshold < 0:
        raise HTTPException(status_code=400, detail="预警值不能小于 0")
    if not set_warning_threshold(sku, threshold):
        raise HTTPException(status_code=404, detail="没有找到这个商品")
    _notify_inventory_warning_for_skus({sku}, source="库存预警值调整")
    return {"status": "success"}


@app.post("/api/order/preview")
async def order_preview(payload: dict):
    try:
        return preview_wechat_order(str(payload.get("text", "")))
    except OrderParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/order/generate")
async def order_generate(payload: dict):
    try:
        result = generate_outbound_order(str(payload.get("text", "")))
    except OrderParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    filename = Path(result["file"]).name
    result["download_url"] = _order_download_path(filename)
    return result


@app.get("/api/order/files/{filename}")
def order_file(request: Request, filename: str):
    if secrets.compare_digest(_request_token(request), _public_order_token()) and not _order_file_download_signature_valid(request, filename):
        _require_store_order_auth(request)
    path = OUTPUT_DIR / Path(filename).name
    if not path.exists() or path.suffix.lower() not in {".xlsx", ".xlsm"}:
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(path, filename=path.name)


@app.get("/order-file/{filename}")
def public_order_file_page(request: Request, filename: str):
    _require_public_order_token(request)
    if request.query_params.get("sig") and not _order_file_download_signature_valid(request, filename):
        _require_store_order_auth(request)
    path = OUTPUT_DIR / Path(filename).name
    if not path.exists() or path.suffix.lower() not in {".xlsx", ".xlsm"}:
        raise HTTPException(status_code=404, detail="文件不存在")
    download_url = _public_file_download_url(request, path.name)
    page_url = _public_order_file_page_url(request, path.name)
    return Response(
        content=_order_file_page_html(path.name, download_url, page_url),
        media_type="text/html; charset=utf-8",
    )


@app.get("/api/public-order/catalog")
def public_order_catalog_api(request: Request):
    _require_public_order_token(request)
    account = _require_store_order_auth(request)
    try:
        catalog = public_order_catalog()
        if account and not _is_store_order_owner(account):
            stores = [store for store in catalog.get("stores", []) if store.get("name") == account["store_name"]]
            verified_store = stores[0] if stores else {"name": account["store_name"], "address": "", "contact": "", "phone": ""}
            catalog["stores"] = stores or [verified_store]
            catalog["authenticated_store"] = verified_store
        balances = {item["sku"]: float(item["balance"]) for item in inventory_summary()}
        for product in catalog.get("products", []):
            balance = balances.get(product["sku"], 0.0)
            product["stock"] = balance
            product["available"] = balance > 0
        return catalog
    except OrderParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/public-order/submit")
async def public_order_submit_api(request: Request, payload: dict):
    _require_public_order_token(request)
    account = _require_store_order_auth(request)
    items = list(payload.get("items") or [])
    _reject_public_order_below_minimum(items)
    _reject_unavailable_order_items(items)
    try:
        result = generate_structured_outbound_order(
            store_name=account["store_name"] if account and not _is_store_order_owner(account) else str(payload.get("store_name", "")),
            items=items,
        )
    except OrderParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    filename = Path(result["file"]).name
    _record_generated_outbound(result, filename)
    download_url = _public_download_url(request, filename)
    _notify_order_submit(result, filename, download_url)
    return {
        "status": "success",
        "line_count": result["line_count"],
        "filename": filename,
        "download_url": download_url,
    }


def _public_order_total_quantity(items: list) -> float:
    return sum(max(_to_float(item.get("quantity", 0)), 0.0) for item in items)


def _public_inventory_item(item: dict) -> dict:
    allowed_keys = {
        "sku",
        "name",
        "spec",
        "unit",
        "warehouse",
        "warning_threshold",
        "balance",
        "last_inbound_at",
        "last_outbound_at",
    }
    return {key: item.get(key) for key in allowed_keys if key in item}


def _reject_public_order_below_minimum(items: list) -> None:
    total_quantity = _public_order_total_quantity(items)
    if total_quantity < PUBLIC_ORDER_MIN_TOTAL_QUANTITY:
        total_text = int(total_quantity) if total_quantity.is_integer() else round(total_quantity, 2)
        raise HTTPException(
            status_code=400,
            detail=f"日配订货满 {PUBLIC_ORDER_MIN_TOTAL_QUANTITY} 件才可以提交，当前合计 {total_text} 件",
        )


def _reject_unavailable_order_items(items: list) -> None:
    balances = {item["sku"]: float(item["balance"]) for item in inventory_summary()}
    blocked = []
    for item in items:
        sku = str(item.get("sku", ""))
        quantity = _to_float(item.get("quantity", 0))
        if quantity > 0 and balances.get(sku, 0.0) <= 0:
            blocked.append(sku)
    if blocked:
        raise HTTPException(status_code=400, detail=f"以下商品库存为 0，暂不可下单：{', '.join(blocked)}")


def _unknown_import_skus(conn, lines: list) -> list[str]:
    skus = sorted({str(line.sku).strip() for line in lines if str(line.sku).strip()})
    if not skus:
        return []
    placeholders = ",".join("?" for _ in skus)
    rows = conn.execute(f"SELECT sku FROM products WHERE sku IN ({placeholders})", skus).fetchall()
    known = {row["sku"] for row in rows}
    return [sku for sku in skus if sku not in known]


def _to_float(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


@app.get("/api/public-order/files")
def public_order_files(request: Request):
    _require_public_order_token(request)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    files = []
    for path in sorted(OUTPUT_DIR.glob("*.xlsx"), key=lambda item: item.stat().st_mtime, reverse=True):
        files.append(
            {
                "filename": path.name,
                "size": path.stat().st_size,
                "mtime": int(path.stat().st_mtime),
                "download_url": _signed_order_file_download_path(path.name),
            }
        )
    return {"items": files}


@app.get("/api/public-order/orders")
def public_store_order_history(request: Request):
    _require_public_order_token(request)
    account = _require_store_order_auth(request)
    store_name = account["store_name"] if account and not _is_store_order_owner(account) else str(request.query_params.get("store_name") or "")
    return {"items": _public_store_order_history(request, store_name)}


@app.post("/api/public-order/auth/login")
async def public_order_login(request: Request, payload: dict):
    _require_public_order_token(request)
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


@app.post("/api/public-order/auth/logout")
def public_order_logout(request: Request):
    _require_public_order_token(request)
    result = Response(content=json.dumps({"status": "success"}, ensure_ascii=False), media_type="application/json")
    result.delete_cookie(
        "store_order_session",
        path="/",
        samesite="lax",
        secure=request.headers.get("x-forwarded-proto", request.url.scheme) == "https",
    )
    return result


def seed_catalog() -> None:
    catalog_path = BASE_DIR / "app" / "catalog.json"
    if catalog_path.exists():
        products = json.loads(catalog_path.read_text(encoding="utf-8"))
    else:
        template = TEMPLATE_PATH if TEMPLATE_PATH.exists() else TEMPLATE_DIR / "熊小小牛排饭订单模板.xlsx"
        products = parse_product_catalog(template) if template.exists() else []
    product_fields = {"sku", "name", "spec", "unit", "warehouse", "unit_cost"}
    with connect() as conn:
        for product in products:
            upsert_product(conn, **{key: value for key, value in product.items() if key in product_fields})
            _seed_initial_inventory_balance(conn, product)


def _seed_initial_inventory_balance(conn, product: dict) -> None:
    quantity = _to_float(product.get("initial_balance"))
    sku = str(product.get("sku") or "").strip()
    if not sku or quantity <= 0:
        return
    file_hash = f"seed-initial-stock:{sku}:{quantity:g}"
    import_id = create_import(
        conn,
        file_hash=file_hash,
        filename=f"{sku}-initial-stock",
        movement_type="inbound",
        source="catalog_seed",
    )
    if import_id is None:
        return
    conn.execute(
        """
        INSERT OR IGNORE INTO movements (
            import_file_id, row_key, movement_type, sku, name, spec, unit, warehouse, address, store_name,
            quantity, signed_quantity, document_date, source_row, created_at
        )
        VALUES (?, ?, 'inbound', ?, ?, ?, ?, ?, '', '', ?, ?, '', 0, ?)
        """,
        (
            import_id,
            f"{file_hash}:1",
            sku,
            product.get("name") or sku,
            product.get("spec", ""),
            product.get("unit", ""),
            product.get("warehouse", ""),
            quantity,
            quantity,
            now_iso(),
        ),
    )
    finish_import(conn, import_id, status="success", line_count=1, message="catalog initial stock")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _public_order_token() -> str:
    return os.environ.get("ORDER_FORM_TOKEN", "xiongxiaoxiao-order")


def _inbound_template_path() -> Path | None:
    candidates = [
        TEMPLATE_DIR / "入库模板.xlsx",
        TEMPLATE_DIR / "入库模板.xlsm",
        TEMPLATE_DIR / "库存入库模板.xlsx",
        TEMPLATE_DIR / "库存入库模板.xlsm",
    ]
    return next((path for path in candidates if path.exists()), None)


def _read_promo_budget_overrides() -> dict:
    if not PROMO_BUDGET_PATH.exists():
        return {"stores": {}}
    try:
        return _validate_promo_budget_overrides(json.loads(PROMO_BUDGET_PATH.read_text(encoding="utf-8")))
    except Exception:
        return {"stores": {}}


def _validate_promo_budget_overrides(payload: dict) -> dict:
    stores = payload.get("stores") if isinstance(payload, dict) else {}
    if not isinstance(stores, dict):
        raise HTTPException(status_code=400, detail="预算配置格式不正确")
    clean: dict[str, dict] = {"stores": {}}
    weekend_preset = payload.get("weekendPreset") if isinstance(payload, dict) else None
    if isinstance(weekend_preset, dict):
        clean["weekendPreset"] = _validate_weekend_preset(weekend_preset)
    for calendar_key in ["chinaHolidays", "chinaAdjustedWorkdays"]:
        calendar = payload.get(calendar_key) if isinstance(payload, dict) else None
        if isinstance(calendar, dict):
            clean[calendar_key] = {
                str(date): str(label.get("name") if isinstance(label, dict) else label)
                for date, label in calendar.items()
                if re.match(r"^\d{4}-\d{2}-\d{2}$", str(date))
            }
        elif isinstance(calendar, list):
            clean[calendar_key] = {
                str(date): "中国法定节假日"
                for date in calendar
                if re.match(r"^\d{4}-\d{2}-\d{2}$", str(date))
            }
    for store_name, store_payload in stores.items():
        if not isinstance(store_payload, dict):
            continue
        clean_store: dict[str, dict] = {}
        for platform_key in ["all", "饿了么", "美团"]:
            value = store_payload.get(platform_key)
            if not isinstance(value, dict):
                continue
            clean_budget = {}
            for budget_key in ["lunchBudget", "dinnerBudget", "weekendLunchBudget", "weekendDinnerBudget"]:
                raw = value.get(budget_key)
                if raw in {None, ""}:
                    continue
                try:
                    budget = int(Decimal(str(raw)))
                except Exception as exc:
                    raise HTTPException(status_code=400, detail=f"{store_name} 的预算必须是数字") from exc
                if budget <= 0 or budget > 9999:
                    raise HTTPException(status_code=400, detail=f"{store_name} 的预算超出范围")
                clean_budget[budget_key] = budget
            if clean_budget:
                clean_store[platform_key] = clean_budget
        if clean_store:
            clean["stores"][str(store_name)] = clean_store
    return clean


def _validate_weekend_preset(payload: dict) -> dict:
    clean: dict[str, object] = {}
    if "enabled" in payload:
        clean["enabled"] = bool(payload.get("enabled"))
    if payload.get("name"):
        clean["name"] = str(payload.get("name"))
    if isinstance(payload.get("activeDays"), list):
        active_days = []
        for raw in payload.get("activeDays", []):
            try:
                day = int(raw)
            except Exception:
                continue
            if 0 <= day <= 6:
                active_days.append(day)
        if active_days:
            clean["activeDays"] = sorted(set(active_days))
    for key in ["lunchMultiplier", "dinnerMultiplier", "minBudget", "roundTo"]:
        raw = payload.get(key)
        if raw in {None, ""}:
            continue
        try:
            value = Decimal(str(raw))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"周末预设 {key} 必须是数字") from exc
        if value <= 0 or value > 9999:
            raise HTTPException(status_code=400, detail=f"周末预设 {key} 超出范围")
        clean[key] = float(value) if value % 1 else int(value)
    if payload.get("notes"):
        clean["notes"] = str(payload.get("notes"))
    return clean


def _request_token(request: Request) -> str:
    return request.query_params.get("token", "")


def _is_public_request(request: Request) -> bool:
    path = request.url.path
    if path == "/login" or path == "/api/auth/login" or path == "/api/auth/check":
        return True
    if path == "/agent" or path.startswith("/agent/api/"):
        return True
    if path == "/agent-wecom/callback":
        return True
    if path.startswith("/agent-wecom/inbox/"):
        return True
    if path == "/api/inventory/warnings/notify":
        return True
    if path == "/order-submit" or path.startswith("/order-file/") or path.startswith("/api/public-order/") or path.startswith("/api/order/files/"):
        return secrets.compare_digest(_request_token(request), _public_order_token())
    return False


def _public_agent_task(item: dict) -> dict[str, object]:
    result = item.get("result") if isinstance(item.get("result"), dict) else {}
    command_payload = result.get("command_payload") if isinstance(result.get("command_payload"), dict) else {}
    queue_notification = result.get("queue_notification") if isinstance(result.get("queue_notification"), dict) else {}
    answer = str(command_payload.get("answer") or result.get("output_tail") or "").strip()
    return {
        "id": str(item.get("id") or ""),
        "created_at": int(item.get("created_at") or 0),
        "updated_at": int(item.get("updated_at") or 0),
        "status": str(item.get("status") or ""),
        "text": str(item.get("text") or ""),
        "intent": str(item.get("intent") or ""),
        "execute": bool(item.get("execute")),
        "source": str(item.get("source") or ""),
        "attempts": int(item.get("attempts") or 0),
        "worker": str(item.get("worker") or ""),
        "returncode": result.get("returncode"),
        "answer": answer[-1200:],
        "notified": bool(queue_notification.get("delivered")),
    }


def _operation_workbench_root() -> Path:
    configured = os.environ.get("OPERATION_WORKBENCH_DIR") or os.environ.get("OPERATION_CLOUD_REMOTE_DIR")
    if configured:
        return Path(configured)
    cloud_root = Path("/var/www/html/operation-workbench")
    if cloud_root.exists():
        return cloud_root
    return BASE_DIR.parent


def _read_json_file(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _agent_mobile_status_payload() -> dict[str, object]:
    payload = _read_json_file(AGENT_STATUS_PATH)
    if not payload:
        return {
            "generated_at": "",
            "summary": {},
            "data_freshness": {"task_runs_stale": True, "warning": "暂未读到 Agent 手机入口数据。"},
            "answers": [],
        }
    return {
        "generated_at": str(payload.get("generated_at") or ""),
        "summary": payload.get("summary") if isinstance(payload.get("summary"), dict) else {},
        "data_freshness": payload.get("data_freshness") if isinstance(payload.get("data_freshness"), dict) else {},
        "answers": payload.get("answers") if isinstance(payload.get("answers"), list) else [],
    }


def _agent_recent_visible_tasks(limit: int = 20) -> list[dict]:
    cutoff = int(time.time()) - AGENT_RECENT_TASK_MAX_AGE_SECONDS
    visible = []
    for item in agent_inbox.recent_tasks(limit=50):
        updated_at = int(item.get("updated_at") or item.get("created_at") or 0)
        status = str(item.get("status") or "")
        if updated_at >= cutoff or status in {"pending", "running"}:
            visible.append(item)
    return visible[: max(1, min(int(limit or 20), 50))]


def _agent_task_summary(items: list[dict]) -> dict[str, int]:
    counts = {"pending": 0, "running": 0, "success": 0, "failed": 0, "canceled": 0, "recovered": 0, "total": 0}
    for item in items:
        if not isinstance(item, dict):
            continue
        counts["total"] += 1
        status = str(item.get("status") or "")
        if status in counts:
            counts[status] += 1
    return counts


def _agent_realtime_summary() -> dict[str, object]:
    payload = _read_json_file(_operation_workbench_root() / "outputs" / "realtime_order_income" / "latest.json")
    if not payload:
        return {"status": "missing", "message": "暂未发布实时采集明细。", "stores": []}
    stores = []
    for item in payload.get("stores") or []:
        if not isinstance(item, dict):
            continue
        platforms = item.get("platforms") if isinstance(item.get("platforms"), dict) else {}
        stores.append(
            {
                "store": str(item.get("store") or ""),
                "orders": int(float(item.get("orders") or 0)),
                "income": round(float(item.get("income") or 0), 2),
                "platforms": {
                    str(platform): {
                        "orders": int(float(detail.get("orders") or 0)),
                        "income": round(float(detail.get("income") or 0), 2),
                    }
                    for platform, detail in platforms.items()
                    if isinstance(detail, dict)
                },
            }
        )
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    return {
        "status": str(payload.get("status") or ""),
        "generated_at": str(payload.get("generated_at") or ""),
        "store_count": int(summary.get("store_count") or len(stores)),
        "platform_store_count": int(summary.get("platform_store_count") or 0),
        "total_orders": int(float(summary.get("total_orders") or 0)),
        "total_income": round(float(summary.get("total_income") or 0), 2),
        "stores": stores,
    }


def _agent_queue_answer(item: dict) -> str:
    intent = str(item.get("intent") or "")
    labels = {
        "budget_commit": "真实预算提交流程",
        "budget_preview": "预算预览/安全计划，不会直接提交预算",
        "meituan_spend_inspection": "美团推广余量/实时消耗只读巡检，不会修改预算或出价",
        "refresh_status": "刷新 Agent 状态和手机入口数据",
        "publish_mobile": "发布手机入口和工作台数据",
        "execute_non_ordering": "执行允许的非订货动作",
    }
    action = labels.get(intent, "执行允许的 Agent 动作")
    return f"已收到，已加入 Mac mini 队列：{action}。队列编号：{str(item.get('id') or '')[:8]}。完成后会通过企业微信通知结果。"


def _agent_mobile_page_html() -> str:
    return r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
  <title>熊小小运营 Agent</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --text: #18212f;
      --muted: #6b7280;
      --line: #d8dde6;
      --accent: #1769e0;
      --accent-strong: #0f54bd;
      --ok: #0b7a45;
      --warn: #9a5b00;
      --bad: #b42318;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    .shell {
      min-height: 100vh;
      height: 100vh;
      height: 100dvh;
      display: grid;
      grid-template-rows: auto auto auto auto minmax(0, 1fr) auto auto;
      max-width: 880px;
      margin: 0 auto;
      background: var(--panel);
    }
    header {
      padding: calc(14px + env(safe-area-inset-top)) 16px 12px;
      border-bottom: 1px solid var(--line);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }
    h1 { margin: 0; font-size: 18px; line-height: 1.2; }
    .sub { margin-top: 4px; color: var(--muted); font-size: 12px; }
    .badge {
      padding: 6px 9px;
      border: 1px solid var(--line);
      border-radius: 999px;
      color: var(--muted);
      font-size: 12px;
      white-space: nowrap;
    }
    .token {
      padding: 12px 16px;
      border-bottom: 1px solid var(--line);
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
      background: #fbfcfe;
    }
    input, textarea, button {
      font: inherit;
    }
    input, textarea {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 11px 12px;
      outline: none;
      background: #fff;
      color: var(--text);
    }
    textarea { min-height: 48px; resize: none; line-height: 1.35; }
    button {
      border: 0;
      border-radius: 8px;
      padding: 11px 14px;
      background: var(--accent);
      color: #fff;
      font-weight: 650;
      cursor: pointer;
    }
    button:active { background: var(--accent-strong); }
    button.secondary {
      background: #eef2f7;
      color: #243042;
      border: 1px solid var(--line);
    }
    .chips {
      display: flex;
      gap: 8px;
      overflow-x: auto;
      padding: 12px 16px;
      border-bottom: 1px solid var(--line);
    }
    .chips button {
      white-space: nowrap;
      background: #eef5ff;
      color: #174ea6;
      border: 1px solid #c6ddff;
      padding: 9px 11px;
      flex: 0 0 auto;
    }
    .messages {
      padding: 16px;
      overflow: auto;
      min-height: 0;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .realtime {
      border-bottom: 1px solid var(--line);
      padding: 10px 16px;
      background: #fff;
      display: grid;
      gap: 8px;
      font-size: 13px;
    }
    .realtime-head {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      color: var(--muted);
    }
    .realtime-stores {
      display: flex;
      gap: 8px;
      overflow-x: auto;
      padding-bottom: 2px;
    }
    .realtime-store {
      min-width: 112px;
      border: 1px solid #e1e6ef;
      border-radius: 8px;
      padding: 8px 9px;
      background: #fbfcfe;
      display: grid;
      gap: 4px;
    }
    .realtime-store strong { font-size: 13px; }
    .realtime-store span { color: var(--muted); font-size: 12px; white-space: nowrap; }
    .msg {
      max-width: 88%;
      border-radius: 12px;
      padding: 11px 12px;
      line-height: 1.45;
      font-size: 15px;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .me { align-self: flex-end; background: #dfeeff; }
    .agent { align-self: flex-start; background: #f0f2f5; }
    .meta { display: block; margin-top: 6px; color: var(--muted); font-size: 11px; }
    .tasks {
      border-top: 1px solid var(--line);
      background: #fbfcfe;
      padding: 10px 16px;
      max-height: 24vh;
      overflow: auto;
    }
    .task {
      display: grid;
      gap: 4px;
      padding: 10px 0;
      border-bottom: 1px solid #edf0f5;
      font-size: 13px;
    }
    .task:last-child { border-bottom: 0; }
    .row { display: flex; justify-content: space-between; gap: 12px; }
    .status-success { color: var(--ok); }
    .status-failed { color: var(--bad); }
    .status-running, .status-pending { color: var(--warn); }
    .composer {
      padding: 10px 16px calc(10px + env(safe-area-inset-bottom));
      border-top: 1px solid var(--line);
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
      background: var(--panel);
    }
    .hidden { display: none; }
    @media (min-width: 720px) {
      body { padding: 18px; }
      .shell {
        border: 1px solid var(--line);
        border-radius: 10px;
        min-height: calc(100vh - 36px);
        height: calc(100vh - 36px);
        overflow: hidden;
      }
    }
  </style>
</head>
<body>
  <main class="shell">
    <header>
      <div>
        <h1>熊小小运营 Agent</h1>
        <div class="sub" id="summary">等待连接</div>
      </div>
      <div class="badge" id="connection">未连接</div>
    </header>
    <section class="token" id="tokenBox">
      <input id="tokenInput" autocomplete="off" placeholder="输入 Agent token" />
      <button id="saveToken" type="button">连接</button>
    </section>
    <section class="chips">
      <button type="button" data-command="任务正常吗">任务状态</button>
      <button type="button" data-command="今天哪里失败">今日失败</button>
      <button type="button" data-command="哪些任务可以补跑">可补跑</button>
      <button type="button" data-command="巡检美团实时消耗">一键查余量</button>
    </section>
    <section class="realtime" id="realtime"></section>
    <section class="messages" id="messages"></section>
    <section class="tasks" id="tasks"></section>
    <form class="composer" id="composer">
      <textarea id="text" placeholder="直接问 Agent，比如：今天哪里失败？"></textarea>
      <button type="submit">发送</button>
    </form>
  </main>
  <script>
    const AGENT_PAGE_VERSION = "20260721-date-scoped-status";
    const tokenFromUrl = new URLSearchParams(location.search).get("token") || "";
    function loadStoredValue(key, fallback = "") {
      try {
        return localStorage.getItem(key) || fallback;
      } catch (error) {
        return fallback;
      }
    }
    function loadStoredMessages() {
      try {
        const version = localStorage.getItem("xiongAgentPageVersion") || "";
        if (version !== AGENT_PAGE_VERSION) {
          localStorage.setItem("xiongAgentPageVersion", AGENT_PAGE_VERSION);
          localStorage.removeItem("xiongAgentMessages");
          return [];
        }
        const value = localStorage.getItem("xiongAgentMessages") || "[]";
        const messages = JSON.parse(value);
        return Array.isArray(messages) ? messages : [];
      } catch (error) {
        try { localStorage.removeItem("xiongAgentMessages"); } catch (_ignored) {}
        return [];
      }
    }
    const state = {
      token: tokenFromUrl || loadStoredValue("xiongAgentToken"),
      messages: loadStoredMessages(),
      seenAnswers: new Set(),
      seededMobileAnswer: false,
    };
    const els = {
      tokenBox: document.getElementById("tokenBox"),
      tokenInput: document.getElementById("tokenInput"),
      saveToken: document.getElementById("saveToken"),
      messages: document.getElementById("messages"),
      tasks: document.getElementById("tasks"),
      realtime: document.getElementById("realtime"),
      text: document.getElementById("text"),
      composer: document.getElementById("composer"),
      summary: document.getElementById("summary"),
      connection: document.getElementById("connection"),
    };
    function saveMessages() {
      try {
        localStorage.setItem("xiongAgentMessages", JSON.stringify(state.messages.slice(-80)));
      } catch (error) {
        state.messages = state.messages.slice(-20);
      }
    }
    function addMessage(role, text, meta = "") {
      state.messages.push({role, text, meta, ts: Date.now()});
      saveMessages();
      renderMessages();
    }
    function renderMessages() {
      els.messages.innerHTML = state.messages.slice(-60).map(item => `
        <div class="msg ${item.role === "me" ? "me" : "agent"}">${escapeHtml(item.text)}${item.meta ? `<span class="meta">${escapeHtml(item.meta)}</span>` : ""}</div>
      `).join("");
      els.messages.scrollTop = els.messages.scrollHeight;
    }
    function escapeHtml(value) {
      return String(value || "").replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
    }
    function fmtTime(ts) {
      if (!ts) return "";
      const date = new Date(ts * 1000);
      return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
    }
    function setToken(token) {
      state.token = token.trim();
      if (state.token) {
        try { localStorage.setItem("xiongAgentToken", state.token); } catch (error) {}
      }
      els.tokenInput.value = state.token;
      els.tokenBox.classList.toggle("hidden", Boolean(state.token));
    }
    async function api(path, options = {}) {
      if (!state.token) throw new Error("missing-token");
      const joiner = path.includes("?") ? "&" : "?";
      const response = await fetch(`${path}${joiner}token=${encodeURIComponent(state.token)}`, {
        ...options,
        headers: {"Content-Type": "application/json", ...(options.headers || {})},
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || `HTTP ${response.status}`);
      return payload;
    }
    async function refresh() {
      if (!state.token) {
        els.connection.textContent = "未连接";
        return;
      }
      try {
        const payload = await api("/agent/api/status?limit=20");
        els.connection.textContent = "已连接";
        const summary = payload.summary || {};
        els.summary.textContent = `待处理 ${summary.pending || 0}，运行中 ${summary.running || 0}，成功 ${summary.success || 0}，失败 ${summary.failed || 0}，已恢复 ${summary.recovered || 0}，已取消 ${summary.canceled || 0}`;
        seedMobileAnswer(payload.mobile || {});
        renderRealtime(payload.realtime || {});
        renderTasks(payload.items || []);
      } catch (error) {
        els.connection.textContent = "连接失败";
        els.summary.textContent = error.message === "missing-token" ? "请先输入 token" : error.message;
      }
    }
    function seedMobileAnswer(mobile) {
      if (state.seededMobileAnswer || state.messages.length > 1) return;
      const answers = Array.isArray(mobile.answers) ? mobile.answers : [];
      const problem = answers.find(item => item && item.id === "problems");
      const status = answers.find(item => item && item.id === "status");
      const answer = (problem && problem.answer) || (status && status.answer) || "";
      if (!answer) return;
      state.seededMobileAnswer = true;
      addMessage("agent", answer, mobile.generated_at ? `Agent 状态 ${mobile.generated_at}` : "Agent 状态");
    }
    function renderRealtime(realtime) {
      const stores = Array.isArray(realtime.stores) ? realtime.stores : [];
      if (!stores.length) {
        els.realtime.innerHTML = `<div class="realtime-head"><strong>加盟店实时采集</strong><span>${escapeHtml(realtime.message || "暂无明细")}</span></div>`;
        return;
      }
      const cards = stores.map(store => `
        <div class="realtime-store">
          <strong>${escapeHtml(store.store)}</strong>
          <span>${Number(store.orders || 0)} 单</span>
          <span>${Number(store.income || 0).toFixed(2)} 元</span>
        </div>
      `).join("");
      els.realtime.innerHTML = `
        <div class="realtime-head">
          <strong>加盟店实时采集</strong>
          <span>${escapeHtml(realtime.generated_at || "")} · ${Number(realtime.platform_store_count || 0)} 个平台门店</span>
        </div>
        <div class="realtime-stores">${cards}</div>
      `;
    }
    function renderTasks(items) {
      els.tasks.innerHTML = items.map(item => {
        const shortId = (item.id || "").slice(0, 8);
        const answer = item.answer ? `<div>${escapeHtml(item.answer)}</div>` : "";
        if (item.answer && !state.seenAnswers.has(item.id) && (item.status === "success" || item.status === "failed")) {
          state.seenAnswers.add(item.id);
          addMessage("agent", item.answer, `${shortId} · ${statusText(item.status)}`);
        }
        return `<div class="task">
          <div class="row"><strong>${escapeHtml(item.text || "Agent 命令")}</strong><span class="status-${escapeHtml(item.status)}">${statusText(item.status)}</span></div>
          <div class="row"><span>${escapeHtml(shortId)} · ${escapeHtml(item.intent || "")}</span><span>${fmtTime(item.updated_at || item.created_at)}</span></div>
          ${answer}
        </div>`;
      }).join("");
    }
    function statusText(status) {
      return {pending:"等待中", running:"执行中", success:"完成", failed:"失败", recovered:"已恢复", canceled:"已取消"}[status] || status || "未知";
    }
    async function send(text) {
      const clean = text.trim();
      if (!clean) return;
      addMessage("me", clean);
      els.text.value = "";
      try {
        const payload = await api("/agent/api/send", {method: "POST", body: JSON.stringify({text: clean})});
        addMessage("agent", payload.answer || "已收到。", payload.task ? `队列 ${(payload.task.id || "").slice(0, 8)}` : "即时回答");
        await refresh();
      } catch (error) {
        addMessage("agent", `发送失败：${error.message}`);
      }
    }
    els.saveToken.addEventListener("click", () => { setToken(els.tokenInput.value); refresh(); });
    els.composer.addEventListener("submit", event => { event.preventDefault(); send(els.text.value); });
    document.querySelectorAll("[data-command]").forEach(btn => btn.addEventListener("click", () => send(btn.dataset.command || "")));
    setToken(state.token);
    if (!state.messages.length) addMessage("agent", "我在。你可以问任务状态、今日失败，也可以点一键查余量。预算设置不放在手机快捷按钮里，订货相关动作会被拦截。");
    renderMessages();
    refresh();
    setInterval(refresh, 5000);
  </script>
</body>
</html>"""


def _operation_auth_username() -> str:
    return os.environ.get("OPERATION_AUTH_USERNAME", "summer")


def _operation_auth_secret() -> str:
    return os.environ.get("OPERATION_AUTH_SECRET", os.environ.get("INVENTORY_PASSWORD", ""))


def _sign_operation_session(username: str) -> str:
    expires = int(time.time()) + 30 * 24 * 60 * 60
    payload = f"{username}:{expires}"
    signature = hmac.new(_operation_auth_secret().encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}:{signature}"


def _operation_session_valid(request: Request) -> bool:
    cookie = request.cookies.get("operation_session", "")
    if not cookie:
        return False
    try:
        username, expires_text, signature = cookie.rsplit(":", 2)
        expires = int(expires_text)
    except Exception:
        return False
    if username != _operation_auth_username() or expires < int(time.time()):
        return False
    payload = f"{username}:{expires}"
    expected = hmac.new(_operation_auth_secret().encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return secrets.compare_digest(signature, expected)


def _login_page_html(next_path: str) -> str:
    safe_next = html.escape(next_path or "/operation-workbench/", quote=True)
    return f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
    <title>熊小小业务中心登录</title>
    <style>
      :root {{ color-scheme: light; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
      * {{ box-sizing: border-box; }}
      html {{ min-height: 100%; }}
      body {{ margin: 0; min-height: 100vh; min-height: 100dvh; display: grid; place-items: center; padding: max(16px, env(safe-area-inset-top)) max(16px, env(safe-area-inset-right)) max(16px, env(safe-area-inset-bottom)) max(16px, env(safe-area-inset-left)); background: #f4f7fb; color: #111827; overflow-x: hidden; }}
      main {{ width: min(420px, 100%); max-height: calc(100dvh - 32px); overflow: auto; -webkit-overflow-scrolling: touch; padding: 26px; border: 1px solid #dbe3ee; border-radius: 8px; background: #fff; box-shadow: 0 18px 50px rgba(15, 23, 42, 0.12); }}
      h1 {{ margin: 0 0 8px; font-size: 24px; line-height: 1.2; }}
      p {{ margin: 0 0 20px; color: #64748b; font-size: 14px; line-height: 1.5; }}
      form {{ display: grid; gap: 14px; }}
      label {{ display: grid; gap: 6px; color: #475569; font-size: 13px; font-weight: 800; }}
      input {{ width: 100%; min-height: 44px; border: 1px solid #cbd5e1; border-radius: 8px; padding: 9px 12px; font: inherit; font-size: 16px; }}
      button {{ min-height: 44px; border: 0; border-radius: 8px; background: #0f766e; color: #fff; font: inherit; font-weight: 900; cursor: pointer; }}
      button:disabled {{ cursor: not-allowed; opacity: .65; }}
      .message {{ min-height: 20px; color: #b91c1c; font-size: 13px; font-weight: 800; }}
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
      <h1>熊小小业务中心</h1>
      <p>请输入账号密码。登录后，本设备 30 天内保持有效。</p>
      <form id="loginForm">
        <label>用户名<input name="username" autocomplete="username" required /></label>
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
          const response = await fetch("/api/auth/login", {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify(data),
          }});
          const payload = await response.json().catch(() => ({{}}));
          if (!response.ok) throw new Error(payload.detail || "登录失败");
          window.location.href = nextPath || "/operation-workbench/";
        }} catch (error) {{
          message.textContent = error.message || "登录失败";
        }} finally {{
          button.disabled = false;
        }}
      }});
    </script>
  </body>
</html>"""


def _require_public_order_token(request: Request) -> None:
    if not secrets.compare_digest(_request_token(request), _public_order_token()):
        raise HTTPException(status_code=403, detail="链接无效")


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


def _order_submit_page_html(account: dict) -> str:
    page = (STATIC_DIR / "order-submit.html").read_text(encoding="utf-8")
    if _is_store_order_owner(account):
        return page
    store_name = html.escape(str(account.get("store_name") or ""), quote=False)
    store_info = f"""<div id="storeInfo" class="store-info" style="display:block">
          <span class="verified-label">已校验门店</span>
          <strong>{store_name}</strong>
          <div>请核对当前账号对应门店后再下单。</div>
        </div>"""
    return page.replace('<div id="storeInfo" class="store-info"></div>', store_info, 1)


def _public_store_order_history(request: Request, store_name: str, limit: int = 20) -> list[dict]:
    clean_store = str(store_name or "").strip()
    if not clean_store:
        return []
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT
                f.id,
                f.filename,
                f.created_at,
                f.line_count,
                COUNT(m.id) AS item_count,
                COALESCE(SUM(m.quantity), 0) AS total_quantity
            FROM import_files f
            JOIN movements m ON m.import_file_id = f.id
            WHERE f.source = 'cloud_order'
              AND f.movement_type = 'outbound'
              AND m.store_name = ?
            GROUP BY f.id, f.filename, f.created_at, f.line_count
            ORDER BY f.id DESC
            LIMIT ?
            """,
            (clean_store, limit),
        ).fetchall()
        order_items = {}
        for row in rows:
            order_items[int(row["id"])] = [
                dict(item)
                for item in conn.execute(
                    """
                    SELECT sku, name, spec, unit, quantity
                    FROM movements
                    WHERE import_file_id = ?
                      AND movement_type = 'outbound'
                      AND store_name = ?
                    ORDER BY source_row, id
                    """,
                    (int(row["id"]), clean_store),
                ).fetchall()
            ]
    items = []
    for row in rows:
        filename = str(row["filename"] or "")
        row_id = int(row["id"])
        items.append(
            {
                "order_id": filename,
                "filename": filename,
                "created_at": row["created_at"] or "",
                "line_count": int(row["line_count"] or row["item_count"] or 0),
                "item_count": int(row["item_count"] or 0),
                "total_quantity": float(row["total_quantity"] or 0),
                "items": order_items.get(row_id, []),
                "download_url": _public_order_file_page_url(request, filename),
            }
        )
    return items


def _store_order_login_page_html(title: str, next_path: str, request: Request) -> str:
    token = html.escape(_request_token(request), quote=True)
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
      const token = "{token}";
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
          const response = await fetch(`/api/public-order/auth/login?token=${{encodeURIComponent(token)}}`, {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify(data),
          }});
          const payload = await response.json().catch(() => ({{}}));
          if (!response.ok) throw new Error(payload.detail || "登录失败");
          window.location.href = `${{nextPath}}?token=${{encodeURIComponent(token)}}&login_at=${{Date.now()}}`;
        }} catch (error) {{
          message.textContent = error.message || "登录失败";
        }} finally {{
          button.disabled = false;
        }}
      }});
    </script>
  </body>
</html>"""


def _require_operation_auth(request: Request) -> None:
    if _operation_session_valid(request) or _basic_auth_valid(request):
        return
    raise HTTPException(status_code=401, detail="需要登录")


def _basic_auth_valid(request: Request) -> bool:
    password = os.environ.get("INVENTORY_PASSWORD", "")
    if not password:
        return False
    authorization = request.headers.get("Authorization", "")
    prefix = "Basic "
    if not authorization.startswith(prefix):
        return False
    import base64

    try:
        decoded = base64.b64decode(authorization[len(prefix) :]).decode("utf-8")
        supplied_username, supplied_password = decoded.split(":", 1)
    except Exception:
        return False
    return secrets.compare_digest(supplied_username, _operation_auth_username()) and secrets.compare_digest(supplied_password, password)


def _public_download_url(request: Request, filename: str) -> str:
    return _public_order_file_page_url(request, filename)


def _public_order_file_page_url(request: Request, filename: str) -> str:
    base_url = str(request.base_url).rstrip("/")
    return f"{base_url}/order-file/{quote(filename)}?token={quote(_public_order_token())}"


def _public_file_download_url(request: Request, filename: str) -> str:
    base_url = str(request.base_url).rstrip("/")
    return f"{base_url}{_signed_order_file_download_path(filename)}"


def _order_download_path(filename: str) -> str:
    return f"/api/order/files/{quote(filename)}"


def _signed_order_file_download_path(filename: str) -> str:
    return f"{_order_download_path(filename)}?{_signed_order_file_query(filename)}"


def _signed_order_file_query(filename: str) -> str:
    expires = int(time.time()) + int(os.environ.get("ORDER_FILE_DOWNLOAD_TTL_SECONDS", ORDER_FILE_DOWNLOAD_TTL_SECONDS))
    signature = _sign_order_file_download(filename, expires)
    return f"token={quote(_public_order_token())}&expires={expires}&sig={signature}"


def _sign_order_file_download(filename: str, expires: int) -> str:
    safe_name = Path(filename).name
    payload = f"{safe_name}:{int(expires)}"
    return hmac.new(_order_file_download_secret().encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _order_file_download_signature_valid(request: Request, filename: str) -> bool:
    try:
        expires = int(request.query_params.get("expires") or 0)
    except ValueError:
        return False
    if expires < int(time.time()):
        return False
    supplied = request.query_params.get("sig", "")
    if not supplied:
        return False
    expected = _sign_order_file_download(filename, expires)
    return secrets.compare_digest(supplied, expected)


def _order_file_download_secret() -> str:
    return os.environ.get("ORDER_FILE_DOWNLOAD_SECRET") or _operation_auth_secret()


def _order_file_page_html(filename: str, download_url: str, page_url: str) -> str:
    safe_filename = html.escape(filename)
    safe_download_url = html.escape(download_url, quote=True)
    page_url_json = json.dumps(page_url, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>订单文件下载</title>
    <style>
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        min-height: 100vh;
        display: grid;
        place-items: center;
        padding: 24px;
        background: #f6f8fb;
        color: #172033;
        font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Segoe UI", sans-serif;
      }}
      main {{
        width: min(520px, 100%);
        padding: 22px;
        background: #fff;
        border: 1px solid #e1e7ef;
        border-radius: 8px;
        box-shadow: 0 10px 28px rgba(15, 23, 42, 0.08);
      }}
      h1 {{ margin: 0 0 10px; font-size: 22px; }}
      p {{ margin: 0 0 16px; color: #5b6678; line-height: 1.6; word-break: break-all; }}
      a, button {{
        width: 100%;
        min-height: 46px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        margin-top: 10px;
        border-radius: 8px;
        border: 1px solid #0f766e;
        background: #0f766e;
        color: #fff;
        font: inherit;
        font-weight: 700;
        text-decoration: none;
      }}
      button {{
        background: #fff;
        color: #0f766e;
      }}
      small {{ display: block; margin-top: 14px; color: #7a8494; line-height: 1.5; }}
    </style>
  </head>
  <body>
    <main>
      <h1>订单文件下载</h1>
      <p>{safe_filename}</p>
      <a href="{safe_download_url}" download>下载 Excel 文件</a>
      <button type="button" id="copyButton">复制下载页链接</button>
      <small>如果企微下载文件后再次进入没有文件转发按钮，请返回这页后用右上角转发，或复制链接发给同事。</small>
    </main>
    <script>
      const pageUrl = {page_url_json};
      document.querySelector("#copyButton").addEventListener("click", async () => {{
        try {{
          await navigator.clipboard.writeText(pageUrl);
          document.querySelector("#copyButton").textContent = "已复制";
        }} catch (error) {{
          window.prompt("复制这个链接", pageUrl);
        }}
      }});
    </script>
  </body>
</html>"""


def _record_generated_outbound(result: dict, filename: str) -> None:
    path = Path(result["file"])
    file_hash = _sha256(path)
    with connect() as conn:
        import_id = create_import(
            conn,
            file_hash=file_hash,
            filename=filename,
            movement_type="outbound",
            source="cloud_order",
        )
        if import_id is None:
            return

        inserted = 0
        for index, item in enumerate(result.get("items") or [], start=1):
            sku = str(item.get("sku", "")).strip()
            quantity = Decimal(str(item.get("quantity", "0")))
            if not sku or quantity <= 0:
                continue
            upsert_product(
                conn,
                sku=sku,
                name=str(item.get("product_name") or sku),
                spec=str(item.get("spec") or ""),
                unit=str(item.get("unit") or ""),
                warehouse=str(item.get("warehouse") or ""),
            )
            row_key = f"{file_hash}:generated:{index}:{sku}:{quantity}"
            conn.execute(
                """
                INSERT OR IGNORE INTO movements (
                    import_file_id, row_key, movement_type, sku, name, spec, unit, warehouse, address, store_name,
                    quantity, signed_quantity, document_date, source_row, created_at
                )
                VALUES (?, ?, 'outbound', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    import_id,
                    row_key,
                    sku,
                    str(item.get("product_name") or sku),
                    str(item.get("spec") or ""),
                    str(item.get("unit") or ""),
                    str(item.get("warehouse") or ""),
                    str(item.get("address") or ""),
                    str(item.get("store_name") or ""),
                    float(quantity),
                    -float(quantity),
                    now_iso()[:10],
                    index + 1,
                    now_iso(),
                ),
            )
            inserted += 1
        finish_import(conn, import_id, status="success", line_count=inserted)
    _notify_inventory_warning_for_skus(
        {str(item.get("sku") or "").strip() for item in result.get("items") or []},
        source="熊小小日配订货出库",
    )


def _notify_order_submit(result: dict, filename: str, download_url: str = "") -> None:
    notify_type = os.environ.get("ORDER_NOTIFY_TYPE", "feishu").strip().lower()
    if notify_type == "hermes":
        _notify_order_submit_with_hermes(result, filename, download_url)
        return

    webhook = os.environ.get("ORDER_NOTIFY_WEBHOOK", "").strip()
    if not webhook:
        return

    items = result.get("items") or []
    store_name = items[0].get("store_name", "未知门店") if items else "未知门店"
    lines = [
        f"{item.get('product_name', item.get('sku', '商品')).replace('熊小小牛排饭-', '')} {item.get('quantity', '')}{item.get('unit', '')}"
        for item in items
    ]
    text = "\n".join(
        [
            "有新的门店订货提交",
            f"门店：{store_name}",
            f"明细：{len(items)} 行",
            *lines,
            f"文件：{filename}",
            f"下载：{download_url}" if download_url else "",
        ]
    )
    if notify_type in {"wecom", "wechat_work", "企业微信", "企微"}:
        body = {"msgtype": "text", "text": {"content": text}}
    else:
        body = {"msg_type": "text", "content": {"text": text}}
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = url_request.Request(webhook, data=payload, method="POST", headers={"Content-Type": "application/json"})
    try:
        url_request.urlopen(req, timeout=6).read()
    except Exception:
        pass


def _notify_inventory_warning_for_skus(skus: set[str], source: str) -> None:
    warning_items = inventory_warning_items(skus)
    if not warning_items:
        return
    text = _inventory_warning_message(warning_items, source)
    _write_inventory_warning_log("deferred", f"已延迟到每日16:00汇总推送。\n\n{text}")


def _all_inventory_warning_items() -> list[dict]:
    return [
        item
        for item in inventory_summary()
        if float(item.get("balance") or 0) <= float(item.get("warning_threshold") or 0)
    ]


def _notify_inventory_warning_daily(source: str = "每日16:00库存预警汇总") -> dict:
    warning_items = _all_inventory_warning_items()
    if not warning_items:
        return {"status": "clear", "warning_count": 0, "message": "当前没有仓库库存预警，无需推送。"}
    return _send_inventory_warning_items(warning_items, source)


def _send_inventory_warning_items(warning_items: list[dict], source: str) -> dict:
    text = _inventory_warning_message(warning_items, source)
    notify_type = _inventory_warning_notify_type()
    if notify_type == "hermes":
        delivered = _notify_inventory_warning_with_hermes(text)
        return {
            "status": "sent" if delivered else "failed",
            "warning_count": len(warning_items),
            "message": "库存预警汇总已推送。" if delivered else "库存预警汇总推送失败。",
        }
    webhook = _inventory_warning_webhook()
    if not webhook:
        _write_inventory_warning_log("skipped", text)
        return {"status": "skipped", "warning_count": len(warning_items), "message": "库存预警通知通道未配置。"}
    if notify_type in {"wecom", "wechat_work", "企业微信", "企微"}:
        body = {"msgtype": "text", "text": {"content": text}}
    else:
        body = {"msg_type": "text", "content": {"text": text}}
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = url_request.Request(webhook, data=payload, method="POST", headers={"Content-Type": "application/json"})
    try:
        url_request.urlopen(req, timeout=6).read()
        _write_inventory_warning_log("sent", text)
        return {"status": "sent", "warning_count": len(warning_items), "message": "库存预警汇总已推送。"}
    except Exception as exc:
        _write_inventory_warning_log("failed", f"{type(exc).__name__}: {exc}\n\n{text}")
        return {"status": "failed", "warning_count": len(warning_items), "message": f"库存预警汇总推送失败：{exc}"}


def _inventory_warning_message(items: list[dict], source: str) -> str:
    title = "【熊小小仓库库存预警】"
    lines = [title, f"来源：{source}", f"触发 SKU：{len(items)} 个"]
    for item in items[:12]:
        name = str(item.get("name") or item.get("sku") or "").replace("熊小小牛排饭-", "")
        balance = _format_quantity(item.get("balance"))
        threshold = _format_quantity(item.get("warning_threshold"))
        unit = str(item.get("unit") or "")
        warehouse = str(item.get("warehouse") or "")
        suffix = f"｜{warehouse}" if warehouse else ""
        lines.append(f"- {name}（{item.get('sku')}）：库存 {balance}{unit}，预警值 {threshold}{unit}{suffix}")
    if len(items) > 12:
        lines.append(f"... 还有 {len(items) - 12} 个 SKU，请打开仓库管理查看。")
    return "\n".join(lines)


def _inventory_warning_webhook() -> str:
    direct = os.environ.get("INVENTORY_WARNING_NOTIFY_WEBHOOK", "").strip()
    if direct:
        return direct
    for key in ("ORDER_NOTIFY_WEBHOOK", "OPS_NOTIFY_WEBHOOK"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    config_path = Path(os.environ.get("OPS_NOTIFY_CONFIG", str(BASE_DIR.parent / "config" / "ops_notify.json"))).expanduser()
    try:
        config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    except Exception:
        config = {}
    return str(config.get("webhook") or "").strip()


def _inventory_warning_notify_type() -> str:
    for key in ("INVENTORY_WARNING_NOTIFY_TYPE", "ORDER_NOTIFY_TYPE", "OPS_NOTIFY_TYPE"):
        value = os.environ.get(key, "").strip().lower()
        if value:
            return value
    config_path = Path(os.environ.get("OPS_NOTIFY_CONFIG", str(BASE_DIR.parent / "config" / "ops_notify.json"))).expanduser()
    try:
        config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    except Exception:
        config = {}
    return str(config.get("type") or "wecom").strip().lower()


def _write_inventory_warning_log(status: str, text: str) -> None:
    log_dir = Path(os.environ.get("INVENTORY_WARNING_NOTIFY_LOG_DIR", str(BASE_DIR / "data" / "notify_logs"))).expanduser()
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = now_iso().replace(":", "").replace("+", "_")
        (log_dir / f"inventory-warning-{status}-{timestamp}.log").write_text(text + "\n", encoding="utf-8")
    except Exception:
        pass


def _notify_inventory_warning_with_hermes(text: str) -> bool:
    if os.environ.get("INVENTORY_WARNING_NOTIFY_DRY_RUN", "").strip().lower() in {"1", "true", "yes", "on"}:
        _write_inventory_warning_log("dry-run", text)
        return True

    hermes_bin = Path(os.environ.get("ORDER_HERMES_BIN", "~/.local/bin/hermes")).expanduser()
    target = os.environ.get("INVENTORY_WARNING_HERMES_TARGET", os.environ.get("ORDER_HERMES_TARGET", "")).strip()
    if not target:
        _write_inventory_warning_log("failed", "INVENTORY_WARNING_HERMES_TARGET 和 ORDER_HERMES_TARGET 均为空，已跳过库存预警发送")
        return False
    try:
        completed = subprocess.run(
            [str(hermes_bin), "send", "--to", target, text],
            check=False,
            cwd=str(BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=90,
        )
    except Exception as exc:
        _write_inventory_warning_log("failed", f"{type(exc).__name__}: {exc}\n\n{text}")
        return False

    status = "sent" if completed.returncode == 0 else "failed"
    output = (completed.stdout or "").strip()
    _write_inventory_warning_log(status, f"target={target}\nreturncode={completed.returncode}\noutput={output}\n\n{text}")
    return completed.returncode == 0


def _format_quantity(value) -> str:
    number = _to_float(value)
    return str(int(number)) if number.is_integer() else f"{number:.2f}".rstrip("0").rstrip(".")


def _notify_order_submit_with_hermes(result: dict, filename: str, download_url: str = "") -> None:
    message = _order_submit_hermes_message(result, filename, download_url)
    if os.environ.get("ORDER_NOTIFY_DRY_RUN", "").strip().lower() in {"1", "true", "yes", "on"}:
        _write_order_notify_log("dry-run", message)
        return

    hermes_bin = Path(os.environ.get("ORDER_HERMES_BIN", "~/.local/bin/hermes")).expanduser()
    target = os.environ.get("ORDER_HERMES_TARGET", "熊小小牛排饭-易代仓仓储配送群").strip()
    if not target:
        _write_order_notify_log("failed", "ORDER_HERMES_TARGET 为空，已跳过 Hermes 发送")
        return
    try:
        completed = subprocess.run(
            [str(hermes_bin), "send", "--to", target, message],
            check=False,
            cwd=str(BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=90,
        )
    except Exception as exc:
        _write_order_notify_log("failed", f"{type(exc).__name__}: {exc}\n\n{message}")
        return

    status = "sent" if completed.returncode == 0 else "failed"
    output = (completed.stdout or "").strip()
    _write_order_notify_log(status, f"target={target}\nreturncode={completed.returncode}\noutput={output}\n\n{message}")


def _order_submit_hermes_message(result: dict, filename: str, download_url: str = "") -> str:
    items = result.get("items") or []
    store_name = items[0].get("store_name", "未知门店") if items else "未知门店"
    file_path = str(result.get("file") or "")
    lines = [
        f"{item.get('product_name', item.get('sku', '商品')).replace('熊小小牛排饭-', '')} {item.get('quantity', '')}{item.get('unit', '')}"
        for item in items
    ]
    message_lines = [
        "熊小小日配订货 Excel 已生成，文件见附件。",
        f"门店：{store_name}",
        f"明细：{len(items)} 行",
        *lines,
        f"文件：{filename}",
    ]
    if download_url:
        message_lines.append(f"下载：{download_url}")
    if file_path:
        message_lines.extend([f"文件路径：{file_path}", f"MEDIA:{file_path}"])
    return "\n".join(message_lines)


def _write_order_notify_log(status: str, text: str) -> None:
    log_dir = Path(os.environ.get("ORDER_NOTIFY_LOG_DIR", str(BASE_DIR / "data" / "notify_logs"))).expanduser()
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = now_iso().replace(":", "").replace("+", "_")
        (log_dir / f"order-notify-{status}-{timestamp}.log").write_text(text + "\n", encoding="utf-8")
    except Exception:
        pass
