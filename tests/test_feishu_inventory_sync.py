from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "inventory-board" / "app" / "feishu_inventory.py"


def load_module():
    spec = importlib.util.spec_from_file_location("feishu_inventory_for_test", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sync_inventory_reads_back_written_rows(monkeypatch):
    module = load_module()
    monkeypatch.setenv("FEISHU_INVENTORY_SHEET_ID", "iuWHGo")
    monkeypatch.setattr(module, "_tenant_access_token", lambda: "tenant-token")
    monkeypatch.setattr(module, "_spreadsheet_token", lambda token: "spreadsheet-token")

    def fake_api_json(method, path, access_token, payload):
        if path.endswith("/metainfo"):
            return {
                "code": 0,
                "data": {
                    "properties": {"title": "库存同步"},
                    "sheets": [{"sheetId": "iuWHGo", "title": "成都仓库存"}],
                },
            }
        if path.endswith("/values_batch_update"):
            assert method == "POST"
            assert payload["valueRanges"][0]["range"] == "iuWHGo!A1:H2"
            return {"code": 0}
        if "/values/" in path:
            return {
                "code": 0,
                "data": {
                    "valueRange": {
                        "values": [
                            ["商品编码", "商品名称", "规格", "单位", "仓库", "库存余额", "预警值", "同步时间"],
                            ["SKU-1", "牛排", "1kg", "件", "成都仓", 8, 3, "2026-08-21T10:00:00+08:00"],
                        ]
                    }
                },
            }
        raise AssertionError(path)

    monkeypatch.setattr(module, "_api_json", fake_api_json)

    result = module.sync_inventory(
        [
            {
                "sku": "SKU-1",
                "name": "牛排",
                "spec": "1kg",
                "unit": "件",
                "warehouse": "成都仓",
                "balance": 8,
                "warning_threshold": 3,
            }
        ]
    )

    assert result["status"] == "success"
    assert result["row_count"] == 1
    assert result["verified_row_count"] == 1
    assert result["spreadsheet_title"] == "库存同步"
    assert result["sheet_title"] == "成都仓库存"


def test_sync_inventory_rejects_unverified_write(monkeypatch):
    module = load_module()
    monkeypatch.setenv("FEISHU_INVENTORY_SHEET_ID", "iuWHGo")
    monkeypatch.setattr(module, "_tenant_access_token", lambda: "tenant-token")
    monkeypatch.setattr(module, "_spreadsheet_token", lambda token: "spreadsheet-token")

    def fake_api_json(method, path, access_token, payload):
        if path.endswith("/metainfo"):
            return {"code": 0, "data": {"properties": {"title": "库存同步"}, "sheets": []}}
        if path.endswith("/values_batch_update"):
            return {"code": 0}
        if "/values/" in path:
            return {"code": 0, "data": {"valueRange": {"values": [["旧表头"]]}}}
        raise AssertionError(path)

    monkeypatch.setattr(module, "_api_json", fake_api_json)

    with pytest.raises(module.FeishuInventoryError, match="读回校验失败"):
        module.sync_inventory([{"sku": "SKU-1", "name": "牛排"}])
