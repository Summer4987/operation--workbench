import json
from pathlib import Path


def test_chengdu_daily_order_catalog_excludes_frozen_shrimp():
    catalog_path = Path(__file__).resolve().parents[1] / "daily-order" / "app" / "catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    items = catalog["items"]

    assert all(item.get("category") != "冻品" for item in items)
    assert all(item.get("sku") != "CJ-020" for item in items)
    assert all(item.get("name") != "虾仁" for item in items)
