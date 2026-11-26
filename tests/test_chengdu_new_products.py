import importlib
import io
import json
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook
from test_store_order_auth_gate import load_inventory_module, load_daily_order_module

ROOT = Path(__file__).resolve().parents[1]
PRODUCTS = {
    "LDXXX00015": ("冷冻牛肝菌", "8kg/箱"),
    "LDXXX00016": ("安格斯牛肉丁", "16kg/箱"),
    "CWXXX00010": ("混合豉油拌饭汁", "10kg/箱"),
    "CWXXX00011": ("腌辣椒汁", "10kg/箱"),
}


def test_new_supply_products_seed_zero_and_export_wecom_attachment(tmp_path, monkeypatch):
    module = load_inventory_module()
    db = importlib.import_module(module.__package__ + ".db")
    generator = importlib.import_module(module.__package__ + ".order_generator")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "inventory.sqlite3")
    db.init_db()
    module.seed_catalog()
    balances = {row["sku"]: row for row in db.inventory_summary()}
    for sku, (name, spec) in PRODUCTS.items():
        assert balances[sku]["balance"] == 0
        assert balances[sku]["name"] == name
        assert balances[sku]["spec"] == spec
    book = Workbook()
    book.active.title = "客户订单填写"
    book.active.append(["存货编码", "名称", "规格", "单位", "数量"])
    goods = book.create_sheet("货品信息")
    goods.append(["货品编号", "货品名称", "体积", "重量", "规格", "条码", "主条码", "单位", "仓库"])
    template = tmp_path / "template.xlsx"
    book.save(template)
    catalog = generator.public_order_catalog(template)
    public = {row["sku"]: row for row in catalog["products"]}
    for sku, (name, spec) in PRODUCTS.items():
        assert public[sku] == {"sku": sku, "name": name, "spec": spec, "unit": "件"}
    result = generator.generate_structured_outbound_order("银泰城店", [{"sku": sku, "quantity": 2} for sku in PRODUCTS], template, tmp_path / "out")
    exported = load_workbook(result["file"])
    lines = list(exported["客户订单填写"].values)[1:5]
    assert [(row[0], row[1], row[2], row[3], row[4]) for row in lines] == [(sku, name, spec, "件", 2) for sku, (name, spec) in PRODUCTS.items()]
    goods_rows = list(exported["货品信息"].values)[1:]
    assert {row[0] for row in goods_rows} == set(PRODUCTS)
    assert all(row[5] == row[0] and row[8] == "成都易代仓" for row in goods_rows)
    calls = []
    def send(req, **kwargs):
        calls.append(req)
        return io.BytesIO(json.dumps({"errcode": 0, "media_id": "test-order"}).encode())
    monkeypatch.setenv("ORDER_NOTIFY_TYPE", "wecom")
    monkeypatch.setenv("ORDER_NOTIFY_WEBHOOK", "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test-only")
    monkeypatch.setattr(module.url_request, "urlopen", send)
    monkeypatch.setattr(module, "_write_order_notify_log", lambda *args: None)
    module._notify_order_submit(result, Path(result["file"]).name)
    assert len(calls) == 3
    assert all(name in json.loads(calls[0].data)["text"]["content"] for name, _ in PRODUCTS.values())
    uploaded = calls[1].data.split(b"\r\n\r\n", 1)[1].rsplit(b"\r\n--", 1)[0]
    assert uploaded == Path(result["file"]).read_bytes()
    assert json.loads(calls[2].data)["msgtype"] == "file"


def test_crispy_onion_order_routes_to_taobao(tmp_path, monkeypatch):
    module = load_daily_order_module()
    monkeypatch.setattr(module, "_store_order_auth_enabled", lambda: False)
    monkeypatch.setattr(module, "SUBMISSION_DIR", tmp_path / "orders")
    monkeypatch.setattr(module, "ORDER_LINES_PATH", tmp_path / "lines.csv")
    monkeypatch.setattr(module, "_notify_order", lambda *args: None)
    product = next(row for row in module._load_catalog()["items"] if row["sku"] == "KD-067")
    assert (product["name"], product["category"], product["unit"], product["source"]) == ("洋葱酥", "调料", "盒", "快递到店")
    assert (ROOT / product["image"].lstrip("/")).exists()
    response = TestClient(module.app).post("/daily-order/api/orders", json={"store_name": "银泰城店", "items": [{"sku": "KD-067", "quantity": 3}]})
    assert response.status_code == 200, response.text
    saved = json.loads(next((tmp_path / "orders").glob("*.json")).read_text())
    line = saved["items"][0]
    assert (line["name"], line["unit"], line["purchase_channel"], line["quantity"]) == ("洋葱酥", "盒", "淘宝", 3)
    assert "淘宝" not in saved.get("processed_channels", [])
