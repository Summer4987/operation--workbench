import importlib
import json
import sys
from pathlib import Path


def load_inventory_main():
    app_root = Path(__file__).resolve().parents[1] / "inventory-board"
    if str(app_root) not in sys.path:
        sys.path.insert(0, str(app_root))
    return importlib.import_module("app.main")


def load_inventory_order_generator():
    app_root = Path(__file__).resolve().parents[1] / "inventory-board"
    if str(app_root) not in sys.path:
        sys.path.insert(0, str(app_root))
    return importlib.import_module("app.order_generator")


def test_production_note_splits_clear_factory_balance(monkeypatch, tmp_path):
    module = load_inventory_main()
    manifest = tmp_path / "supply_chain_flow.jsonl"
    monkeypatch.setattr(module, "SUPPLY_CHAIN_FLOW_MANIFEST", manifest)
    entry = {
        "id": "sample",
        "created_at": "2026-06-20T00:00:00",
        "date": "2026-06-20",
        "event_type": "生产",
        "lot_id": "20260620-调理鸡胸肉",
        "product_name": "调理鸡胸肉",
        "item_type": "成品",
        "factory": "",
        "quantity": 67,
        "unit": "件",
        "unit_cost": 249.12,
        "total_amount": 16691.04,
        "payable_amount": 16691.04,
        "paid_amount": 16691.04,
        "receivable_amount": 0,
        "received_amount": 0,
        "settlement_status": "部分已结算",
        "payment_status": "已付给工厂",
        "production_status": "工厂已生产完成",
        "from_location": "",
        "to_location": "工厂暂存",
        "counterparty": "",
        "note": "6月20日工厂生产出调理鸡胸肉一共67件 北京仓发35件 北京直营店发5件 成都仓发27件 所有货款已支付 工厂库存清零",
        "sync_status": "cloud_saved",
    }
    manifest.write_text(json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")

    summary = module._supply_chain_flow_summary()

    lot = summary["items"][0]
    assert lot["factory_quantity"] == 0
    assert lot["out_quantity"] == 67
    assert summary["factory_completed_items"] == []
    locations = {item["location"]: item["quantity"] for item in lot["locations"]}
    assert locations == {"北京仓": 35, "北京直营店": 5, "成都仓": 27}


def test_public_order_rejects_below_minimum_quantity():
    module = load_inventory_main()

    try:
        module._reject_public_order_below_minimum(
            [
                {"sku": "调理鸡胸肉", "quantity": 2},
                {"sku": "牛五花", "quantity": 2},
            ]
        )
    except module.HTTPException as exc:
        assert exc.status_code == 400
        assert "满 5 件" in exc.detail
        assert "当前合计 4 件" in exc.detail
    else:
        raise AssertionError("Expected below-minimum public order to be rejected")


def test_public_order_allows_minimum_quantity():
    module = load_inventory_main()

    module._reject_public_order_below_minimum(
        [
            {"sku": "调理鸡胸肉", "quantity": 3},
            {"sku": "牛五花", "quantity": 2},
        ]
    )


def test_public_order_catalog_excludes_frozen_and_shrimp(tmp_path):
    module = load_inventory_order_generator()
    catalog = module.public_order_catalog(template_path=tmp_path / "missing-template.xlsx")

    names = [item["name"] for item in catalog["products"]]
    assert names == ["寿司调味汁", "双椒酱", "拌饭汁"]
    assert all("冻" not in name for name in names)
    assert all("虾仁" not in name for name in names)


def test_public_order_rejects_removed_frozen_sku():
    module = load_inventory_order_generator()
    products_by_sku = {
        "LDXXX0007": module.Product(
            sku="LDXXX0007",
            name="熊小小牛排饭-冷冻虾仁（冻）",
            spec="10kg/箱",
            unit="件",
            warehouse="成都易代仓",
            aliases=(),
        )
    }

    try:
        module._reject_removed_public_order_items([{"sku": "LDXXX0007", "quantity": 5}], products_by_sku)
    except module.OrderParseError as exc:
        assert "已从日常订货链接移除" in str(exc)
        assert "冷冻虾仁" in str(exc)
    else:
        raise AssertionError("Expected removed frozen SKU to be rejected")
