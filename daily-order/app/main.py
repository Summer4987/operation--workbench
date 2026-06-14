from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

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
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)
app.mount("/daily-order/static", StaticFiles(directory=STATIC_DIR), name="daily-order-static")


@app.get("/daily-order/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


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
    stores = set(catalog_data.get("stores") or [])
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

    submitted_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    order_id = f"DO-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:6].upper()}"
    order = {
        "order_id": order_id,
        "store_name": store_name,
        "remark": remark,
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

    return {
        "status": "success",
        "order_id": order_id,
        "line_count": len(lines),
        "submitted_at": submitted_at,
    }


def _load_catalog() -> dict:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def _to_number(value) -> float:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return number if number > 0 else 0.0


def _safe_name(value: str) -> str:
    text = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "-", value).strip("-")
    return text[:40] or "store"


def _write_order_csv(path: Path, order: dict) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.writer(target)
        writer.writerow(["订单号", "提交时间", "门店", "配送方式", "分类", "SKU", "品名", "规格", "数量", "单位", "备注", "门店备注"])
        for item in order["items"]:
            writer.writerow(
                [
                    order["order_id"],
                    order["submitted_at"],
                    order["store_name"],
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
