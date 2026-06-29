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
import time
from urllib import request as url_request
from urllib.parse import quote
from decimal import Decimal
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .db import (
    connect,
    create_import,
    delivery_months,
    finish_import,
    inventory_flow_summary,
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


BASE_DIR = Path(__file__).resolve().parents[1]
UPLOAD_DIR = BASE_DIR / "data" / "uploads"
STATIC_DIR = BASE_DIR / "static"
TEMPLATE_DIR = BASE_DIR / "data" / "templates"
PROMO_BUDGET_PATH = BASE_DIR / "data" / "promo_budget_overrides.json"
PUBLIC_ORDER_MIN_TOTAL_QUANTITY = 5

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
    if _store_order_auth_enabled() and not _store_order_session(request):
        return Response(content=_store_order_login_page_html("熊小小日配订货", "/order-submit", request), media_type="text/html; charset=utf-8")
    return FileResponse(STATIC_DIR / "order-submit.html")


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
    if secrets.compare_digest(_request_token(request), _public_order_token()):
        _require_store_order_auth(request)
    path = OUTPUT_DIR / Path(filename).name
    if not path.exists() or path.suffix.lower() not in {".xlsx", ".xlsm"}:
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(path, filename=path.name)


@app.get("/order-file/{filename}")
def public_order_file_page(request: Request, filename: str):
    _require_public_order_token(request)
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
        if account:
            catalog["stores"] = [store for store in catalog.get("stores", []) if store.get("name") == account["store_name"]]
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
            store_name=account["store_name"] if account else str(payload.get("store_name", "")),
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
    _require_store_order_auth(request)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    files = []
    for path in sorted(OUTPUT_DIR.glob("*.xlsx"), key=lambda item: item.stat().st_mtime, reverse=True):
        files.append(
            {
                "filename": path.name,
                "size": path.stat().st_size,
                "mtime": int(path.stat().st_mtime),
                "download_url": f"{_order_download_path(path.name)}?token={_public_order_token()}",
            }
        )
    return {"items": files}


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
        _sign_store_order_session(account["username"], account["store_name"]),
        max_age=30 * 24 * 60 * 60,
        httponly=True,
        samesite="lax",
        secure=request.headers.get("x-forwarded-proto", request.url.scheme) == "https",
        path="/",
    )
    return result


def seed_catalog() -> None:
    catalog_path = BASE_DIR / "app" / "catalog.json"
    if catalog_path.exists():
        products = json.loads(catalog_path.read_text(encoding="utf-8"))
    else:
        template = TEMPLATE_PATH if TEMPLATE_PATH.exists() else TEMPLATE_DIR / "熊小小牛排饭订单模板.xlsx"
        products = parse_product_catalog(template) if template.exists() else []
    with connect() as conn:
        for product in products:
            upsert_product(conn, **product)


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
    if path == "/order-submit" or path.startswith("/order-file/") or path.startswith("/api/public-order/") or path.startswith("/api/order/files/"):
        return secrets.compare_digest(_request_token(request), _public_order_token())
    return False


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
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>熊小小业务中心登录</title>
    <style>
      :root {{ color-scheme: light; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
      body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; background: #f4f7fb; color: #111827; }}
      main {{ width: min(420px, calc(100vw - 32px)); padding: 26px; border: 1px solid #dbe3ee; border-radius: 8px; background: #fff; box-shadow: 0 18px 50px rgba(15, 23, 42, 0.12); }}
      h1 {{ margin: 0 0 8px; font-size: 24px; line-height: 1.2; }}
      p {{ margin: 0 0 20px; color: #64748b; font-size: 14px; line-height: 1.5; }}
      form {{ display: grid; gap: 14px; }}
      label {{ display: grid; gap: 6px; color: #475569; font-size: 13px; font-weight: 800; }}
      input {{ min-height: 44px; border: 1px solid #cbd5e1; border-radius: 8px; padding: 9px 12px; font: inherit; font-size: 16px; }}
      button {{ min-height: 44px; border: 0; border-radius: 8px; background: #0f766e; color: #fff; font: inherit; font-weight: 900; cursor: pointer; }}
      button:disabled {{ cursor: not-allowed; opacity: .65; }}
      .message {{ min-height: 20px; color: #b91c1c; font-size: 13px; font-weight: 800; }}
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
        if username and password and store_name:
            clean[str(username)] = {"username": str(username), "password": password, "store_name": store_name}
    return clean


def _store_order_auth_enabled() -> bool:
    return bool(_store_order_accounts())


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


def _sign_store_order_session(username: str, store_name: str) -> str:
    expires = int(time.time()) + 30 * 24 * 60 * 60
    payload = base64.urlsafe_b64encode(
        json.dumps({"username": username, "store_name": store_name, "expires": expires}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
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
    return {"username": username, "store_name": store_name}


def _require_store_order_auth(request: Request) -> dict | None:
    if not _store_order_auth_enabled():
        return None
    account = _store_order_session(request)
    if account:
        return account
    raise HTTPException(status_code=401, detail="需要门店登录")


def _store_order_login_page_html(title: str, next_path: str, request: Request) -> str:
    token = html.escape(_request_token(request), quote=True)
    safe_title = html.escape(title, quote=True)
    safe_next = html.escape(next_path, quote=True)
    return f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{safe_title}登录</title>
    <style>
      :root {{ color-scheme: light; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
      body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; background: #f6f7f4; color: #17201b; }}
      main {{ width: min(420px, calc(100vw - 32px)); padding: 26px; border: 1px solid #d9ded3; border-radius: 8px; background: #fff; box-shadow: 0 18px 44px rgba(22, 32, 27, .14); }}
      h1 {{ margin: 0 0 8px; font-size: 24px; line-height: 1.2; }}
      p {{ margin: 0 0 20px; color: #64705f; font-size: 14px; line-height: 1.5; }}
      form {{ display: grid; gap: 14px; }}
      label {{ display: grid; gap: 6px; color: #3f4c42; font-size: 13px; font-weight: 800; }}
      input {{ min-height: 44px; border: 1px solid #cfd8cc; border-radius: 8px; padding: 9px 12px; font: inherit; font-size: 16px; }}
      button {{ min-height: 44px; border: 0; border-radius: 8px; background: #2f6f4e; color: #fff; font: inherit; font-weight: 900; cursor: pointer; }}
      button:disabled {{ cursor: not-allowed; opacity: .65; }}
      .message {{ min-height: 20px; color: #b42318; font-size: 13px; font-weight: 800; }}
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
          window.location.href = `${{nextPath}}?token=${{encodeURIComponent(token)}}`;
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
    return f"{base_url}/order-file/{quote(filename)}?token={_public_order_token()}"


def _public_file_download_url(request: Request, filename: str) -> str:
    base_url = str(request.base_url).rstrip("/")
    return f"{base_url}{_order_download_path(filename)}?token={_public_order_token()}"


def _order_download_path(filename: str) -> str:
    return f"/api/order/files/{quote(filename)}"


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


def _notify_order_submit(result: dict, filename: str, download_url: str = "") -> None:
    webhook = os.environ.get("ORDER_NOTIFY_WEBHOOK", "").strip()
    if not webhook:
        return
    notify_type = os.environ.get("ORDER_NOTIFY_TYPE", "feishu").strip().lower()

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
