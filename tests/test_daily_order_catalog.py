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
    assert '<input id="storeName" type="hidden" />' in beijing_html
    assert '<label for="storeName">门店名称</label>' not in beijing_html
    assert '<select id="storeName" required>' not in beijing_html
    assert '<body class="beijing-order-page">' not in chengdu_html
    assert '<div class="store-field" hidden>' not in chengdu_html


def test_beijing_order_history_button_sits_in_topbar():
    beijing_html = (Path(__file__).resolve().parents[1] / "daily-order" / "static" / "beijing-index.html").read_text(
        encoding="utf-8"
    )
    topbar = beijing_html.split("</header>", 1)[0]
    store_panel = beijing_html.split('<section class="store-panel">', 1)[1].split("</section>", 1)[0]

    assert "查看已下单订单" in topbar
    assert "toggleOrdersButton" in topbar
    assert "toggleOrdersButton" not in store_panel


def test_admin_sku_summary_keeps_expanded_state_across_refreshes():
    root = Path(__file__).resolve().parents[1]
    admin_js = (root / "daily-order" / "static" / "admin.js").read_text(encoding="utf-8")

    assert "expandedPanels: new Set()" in admin_js
    assert "data-collapse-key" in admin_js
    assert "state.expandedPanels.add" in admin_js
    assert "state.expandedPanels.has(collapseKey)" in admin_js


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


def test_condiment_and_supply_categories_are_grouped_by_delivery_source():
    root = Path(__file__).resolve().parents[1]
    expected = {
        "调料": ["快递到店", "快驴配送"],
        "耗材": ["快驴配送", "快递到店"],
    }
    for filename in ("catalog.json", "catalog-beijing.json"):
        catalog_path = root / "daily-order" / "app" / filename
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        for category, source_order in expected.items():
            sources = [item["source"] for item in catalog["items"] if item.get("category") == category]
            positions = [source_order.index(source) for source in sources if source in source_order]

            assert positions == sorted(positions)


def test_sauce_category_is_available_in_food_tabs():
    app_js = (Path(__file__).resolve().parents[1] / "daily-order" / "static" / "app.js").read_text(encoding="utf-8")

    assert '["蔬菜", "禽蛋", "粮油", "酱汁", "冻品", "工作餐"]' in app_js


def test_sauce_items_exist_in_store_order_catalogs():
    root = Path(__file__).resolve().parents[1]
    expected = [
        ("SAUCE-001", "拌饭汁", "10kg/箱"),
        ("SAUCE-002", "寿司调味汁", "10kg/箱"),
        ("SAUCE-003", "藤椒酱", "10kg/箱"),
        ("SAUCE-004", "双椒酱", "12kg/箱"),
        ("SAUCE-005", "拌鱼酱", "10kg/箱"),
    ]
    for filename in ("catalog.json", "catalog-beijing.json"):
        catalog_path = root / "daily-order" / "app" / filename
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        sauce_items = [item for item in catalog["items"] if item.get("category") == "酱汁"]

        assert [(item["sku"], item["name"], item["spec"]) for item in sauce_items] == expected
        assert all(item["source"] == "物流发货（5-7天）" for item in sauce_items)
        assert all(item["purchase_channel"] == "物流发货（5-7天）" for item in sauce_items)
        assert all(item.get("force_purchase_channel") is True for item in sauce_items)
        for item in sauce_items:
            assert (root / "daily-order" / "static" / "images" / f"{item['sku']}.svg").exists()
