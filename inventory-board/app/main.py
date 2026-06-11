from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
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
    if _is_public_order_request(request):
        return await call_next(request)
    if not password:
        return await call_next(request)

    authorization = request.headers.get("Authorization", "")
    prefix = "Basic "
    if authorization.startswith(prefix):
        import base64

        try:
            decoded = base64.b64decode(authorization[len(prefix) :]).decode("utf-8")
            _, supplied_password = decoded.split(":", 1)
            if secrets.compare_digest(supplied_password, password):
                return await call_next(request)
        except Exception:
            pass

    return Response(
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="Inventory Board"'},
        content="需要密码",
    )


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
    return FileResponse(STATIC_DIR / "order-submit.html")


@app.get("/api/summary")
def summary():
    items = inventory_summary()
    warning_count = sum(1 for item in items if float(item["balance"]) <= float(item["warning_threshold"]))
    return {
        "items": items,
        "stats": {
            "product_count": len(items),
            "warning_count": warning_count,
            "total_balance": sum(float(item["balance"]) for item in items),
            "inventory_value": sum(float(item["inventory_value"] or 0) for item in items),
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
    _require_public_order_token(request)
    return _read_promo_budget_overrides()


@app.post("/api/promo-budget-overrides")
async def save_promo_budget_overrides(request: Request, payload: dict):
    _require_public_order_token(request)
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
def order_file(filename: str):
    path = OUTPUT_DIR / Path(filename).name
    if not path.exists() or path.suffix.lower() not in {".xlsx", ".xlsm"}:
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(path, filename=path.name)


@app.get("/api/public-order/catalog")
def public_order_catalog_api(request: Request):
    _require_public_order_token(request)
    try:
        catalog = public_order_catalog()
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
    _reject_unavailable_order_items(list(payload.get("items") or []))
    try:
        result = generate_structured_outbound_order(
            store_name=str(payload.get("store_name", "")),
            items=list(payload.get("items") or []),
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
                "download_url": f"{_order_download_path(path.name)}?token={_public_order_token()}",
            }
        )
    return {"items": files}


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
    for store_name, store_payload in stores.items():
        if not isinstance(store_payload, dict):
            continue
        clean_store: dict[str, dict] = {}
        for platform_key in ["all", "饿了么", "美团"]:
            value = store_payload.get(platform_key)
            if not isinstance(value, dict):
                continue
            clean_budget = {}
            for budget_key in ["lunchBudget", "dinnerBudget"]:
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


def _request_token(request: Request) -> str:
    return request.query_params.get("token", "")


def _is_public_order_request(request: Request) -> bool:
    path = request.url.path
    if path == "/api/promo-budget-overrides":
        return secrets.compare_digest(_request_token(request), _public_order_token())
    if path == "/order-submit" or path.startswith("/api/public-order/") or path.startswith("/api/order/files/"):
        return secrets.compare_digest(_request_token(request), _public_order_token())
    return False


def _require_public_order_token(request: Request) -> None:
    if not secrets.compare_digest(_request_token(request), _public_order_token()):
        raise HTTPException(status_code=403, detail="链接无效")


def _public_download_url(request: Request, filename: str) -> str:
    base_url = str(request.base_url).rstrip("/")
    return f"{base_url}{_order_download_path(filename)}?token={_public_order_token()}"


def _order_download_path(filename: str) -> str:
    return f"/api/order/files/{quote(filename)}"


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
