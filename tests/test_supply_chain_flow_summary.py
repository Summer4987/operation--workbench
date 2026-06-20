import importlib.util
import json
from pathlib import Path


def load_inventory_main():
    module_path = Path(__file__).resolve().parents[1] / "inventory-board" / "app" / "main.py"
    spec = importlib.util.spec_from_file_location("inventory_board_main_for_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


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
