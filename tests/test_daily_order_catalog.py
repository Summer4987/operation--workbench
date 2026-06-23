import json
from pathlib import Path


def test_chengdu_daily_order_catalog_excludes_frozen_shrimp():
    catalog_path = Path(__file__).resolve().parents[1] / "daily-order" / "app" / "catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    items = catalog["items"]

    assert all(item.get("category") != "冻品" for item in items)
    assert all(item.get("sku") != "CJ-020" for item in items)
    assert all(item.get("name") != "虾仁" for item in items)


def test_beijing_daily_order_adds_broccoli_and_spinach_between_potato_and_tomato():
    root = Path(__file__).resolve().parents[1]
    catalog_path = root / "daily-order" / "app" / "catalog-beijing.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    vegetables = [item for item in catalog["items"] if item.get("category") == "蔬菜"]
    names = [item["name"] for item in vegetables]

    potato_index = names.index("土豆")
    assert names[potato_index : potato_index + 4] == ["土豆", "西兰花", "菠菜", "圣女果"]

    by_name = {item["name"]: item for item in vegetables}
    assert by_name["西兰花"]["source"] == "快驴配送"
    assert by_name["菠菜"]["source"] == "快驴配送"
    assert by_name["西兰花"]["image"] == "/daily-order/static/images/BJ-KL-010.svg"
    assert by_name["菠菜"]["image"] == "/daily-order/static/images/BJ-KL-010B.svg"
    assert (root / "daily-order" / "static" / "images" / "BJ-KL-010.svg").exists()
    assert (root / "daily-order" / "static" / "images" / "BJ-KL-010B.svg").exists()


def test_beijing_order_page_hides_store_selector():
    root = Path(__file__).resolve().parents[1]
    beijing_html = (root / "daily-order" / "static" / "beijing-index.html").read_text(encoding="utf-8")
    chengdu_html = (root / "daily-order" / "static" / "index.html").read_text(encoding="utf-8")

    assert '<body class="beijing-order-page">' in beijing_html
    assert '<div class="store-field" hidden>' in beijing_html
    assert '<body class="beijing-order-page">' not in chengdu_html
    assert '<div class="store-field" hidden>' not in chengdu_html


def test_packaging_order_groups_bowls_before_starch_boxes():
    root = Path(__file__).resolve().parents[1]
    for filename in ("catalog.json", "catalog-beijing.json"):
        catalog_path = root / "daily-order" / "app" / filename
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        packaging_names = [item["name"] for item in catalog["items"] if item.get("category") == "包材"]
        soup_bowl_index = packaging_names.index("汤碗")

        assert packaging_names[soup_bowl_index : soup_bowl_index + 4] == [
            "汤碗",
            "小塑料碗",
            "酱料盒",
            "玉米淀粉盒",
        ]
