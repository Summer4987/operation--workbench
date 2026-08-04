import json
from pathlib import Path


def test_chengdu_daily_order_catalog_excludes_frozen_shrimp():
    catalog_path = Path(__file__).resolve().parents[1] / "daily-order" / "app" / "catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    items = catalog["items"]

    assert all(item.get("category") != "冻品" for item in items)
    assert all(item.get("sku") != "CJ-020" for item in items)
    assert all(item.get("name") != "虾仁" for item in items)


def test_chengdu_order_catalog_removes_rice_skus():
    root = Path(__file__).resolve().parents[1]
    catalog = json.loads((root / "daily-order" / "app" / "catalog.json").read_text(encoding="utf-8"))
    removed_names = {"大米", "黑米", "燕麦米"}
    removed_skus = {"CWXXX0005", "CWXXX0006", "CWXXX0007", "TC-003", "TC-006", "TC-007"}

    assert all(item.get("name") not in removed_names for item in catalog["items"])
    assert all(item.get("sku") not in removed_skus for item in catalog["items"])


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


def test_order_pages_bust_static_cache_for_drink_category():
    root = Path(__file__).resolve().parents[1]
    expected_scripts = {
        "index.html": "app.js?v=20260701-compact-actions",
        "beijing-index.html": "app.js?v=20260629-store-check",
    }
    expected_styles = {
        "index.html": "styles.css?v=20260701-verified-badge-fix",
        "beijing-index.html": "styles.css?v=20260625-secondary-tabs",
    }
    for filename, expected_script in expected_scripts.items():
        html = (root / "daily-order" / "static" / filename).read_text(encoding="utf-8")

        assert expected_styles[filename] in html
        assert expected_script in html


def test_chengdu_order_page_shows_verified_store_after_login():
    root = Path(__file__).resolve().parents[1]
    html = (root / "daily-order" / "static" / "index.html").read_text(encoding="utf-8")
    app_js = (root / "daily-order" / "static" / "app.js").read_text(encoding="utf-8")
    styles = (root / "daily-order" / "static" / "styles.css").read_text(encoding="utf-8")

    assert 'id="verifiedStore"' in html
    assert "已校验门店" in app_js
    assert "renderVerifiedStore(singleStore)" in app_js
    assert 'els.storeName.hidden = true' in app_js
    assert 'closest(".store-field")?.setAttribute("hidden"' not in app_js
    assert ".verified-store" in styles


def test_daily_order_submit_page_keeps_bound_store_visible():
    html = (Path(__file__).resolve().parents[1] / "inventory-board" / "static" / "order-submit.html").read_text(
        encoding="utf-8"
    )

    assert "已校验门店" in html
    assert "verified-label" in html
    assert "payload.authenticated_store" in html
    assert "function normalizeStore" in html
    assert "function findStore" in html
    assert "?." not in html
    assert "els.store.hidden = true" in html
    assert "els.storeLabel.hidden = true" in html
    assert "els.storeBox.hidden = true" not in html


def test_daily_order_submit_page_has_order_history_panel():
    html = (Path(__file__).resolve().parents[1] / "inventory-board" / "static" / "order-submit.html").read_text(
        encoding="utf-8"
    )

    assert "查看已下单订单" in html
    assert "historyPanel" in html
    assert "/api/public-order/orders" in html
    assert "<details class=\"history-card\">" in html
    assert "order.items" in html
    assert "下载 Excel" in html


def test_daily_order_submit_page_shows_submit_message():
    html = (Path(__file__).resolve().parents[1] / "inventory-board" / "static" / "order-submit.html").read_text(
        encoding="utf-8"
    )
    message_rule = html.split(".message {", 1)[1].split("}", 1)[0]

    assert "display: block" in message_rule
    assert "display: none" not in message_rule


def test_admin_pages_bust_static_cache_for_sam_delivery_channel():
    root = Path(__file__).resolve().parents[1]
    for filename in ("admin.html", "beijing-admin.html"):
        html = (root / "daily-order" / "static" / filename).read_text(encoding="utf-8")

        assert "styles.css?v=20260625-secondary-tabs" in html
        assert "admin.js?v=20260625-sam-delivery" in html


def test_admin_sku_summary_is_static_without_expand_collapse():
    root = Path(__file__).resolve().parents[1]
    admin_js = (root / "daily-order" / "static" / "admin.js").read_text(encoding="utf-8")
    styles = (root / "daily-order" / "static" / "styles.css").read_text(encoding="utf-8")

    assert "<details" not in admin_js
    assert "<summary" not in admin_js
    assert "data-collapse-key" not in admin_js
    assert "items-panel-heading" in admin_js
    assert ".order-items-panel summary" not in styles
    assert ".channel-totals-panel summary" not in styles
    assert ".items-panel-heading" in styles


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


def test_chengdu_order_catalog_removes_legacy_packaging_bag_sku():
    root = Path(__file__).resolve().parents[1]
    catalog = json.loads((root / "daily-order" / "app" / "catalog.json").read_text(encoding="utf-8"))

    assert all(item.get("sku") != "CJ-044" for item in catalog["items"])
    assert all(item.get("name") != "打包袋" for item in catalog["items"])


def test_chengdu_order_catalog_has_taobao_delivery_bags():
    root = Path(__file__).resolve().parents[1]
    catalog = json.loads((root / "daily-order" / "app" / "catalog.json").read_text(encoding="utf-8"))
    by_name = {item["name"]: item for item in catalog["items"]}

    for name in ("自封袋", "塑料袋"):
        item = by_name[name]
        assert item["category"] == "耗材"
        assert item["source"] == "快递到店"
        assert item["purchase_channel"] == "淘宝"
        assert item["unit"] == "份"
        assert (root / "daily-order" / "static" / "images" / f"{item['sku']}.svg").exists()


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

    assert '["蔬菜", "禽蛋", "粮油", "酱汁", "饮品", "冻品", "工作餐"]' in app_js


def test_sauce_items_exist_only_in_beijing_order_catalog():
    root = Path(__file__).resolve().parents[1]
    expected = [
        ("SAUCE-001", "拌饭汁", "10kg/箱"),
        ("SAUCE-002", "寿司调味汁", "10kg/箱"),
        ("SAUCE-003", "藤椒酱", "10kg/箱"),
        ("SAUCE-004", "双椒酱", "12kg/箱"),
        ("SAUCE-005", "拌鱼酱", "10kg/箱"),
    ]
    chengdu_catalog = json.loads((root / "daily-order" / "app" / "catalog.json").read_text(encoding="utf-8"))
    beijing_catalog = json.loads((root / "daily-order" / "app" / "catalog-beijing.json").read_text(encoding="utf-8"))
    sauce_items = [item for item in beijing_catalog["items"] if item.get("category") == "酱汁"]

    assert all(item.get("category") != "酱汁" for item in chengdu_catalog["items"])
    assert all(not str(item.get("sku", "")).startswith("SAUCE-") for item in chengdu_catalog["items"])
    assert [(item["sku"], item["name"], item["spec"]) for item in sauce_items] == expected
    assert all(item["source"] == "物流发货（5-7天）" for item in sauce_items)
    assert all(item["purchase_channel"] == "物流发货（5-7天）" for item in sauce_items)
    assert all(item.get("force_purchase_channel") is True for item in sauce_items)
    for item in sauce_items:
        assert (root / "daily-order" / "static" / "images" / f"{item['sku']}.svg").exists()


def test_drink_category_items_exist_in_chengdu_and_beijing_catalogs():
    root = Path(__file__).resolve().parents[1]
    beijing_catalog = json.loads((root / "daily-order" / "app" / "catalog-beijing.json").read_text(encoding="utf-8"))
    chengdu_catalog = json.loads((root / "daily-order" / "app" / "catalog.json").read_text(encoding="utf-8"))
    beijing_drink_items = [item for item in beijing_catalog["items"] if item.get("category") == "饮品"]
    chengdu_drink_items = [item for item in chengdu_catalog["items"] if item.get("category") == "饮品"]

    assert [(item["sku"], item["name"]) for item in beijing_drink_items] == [
        ("BJ-DRINK-001", "山姆矿泉水"),
        ("BJ-DRINK-002", "无糖可乐"),
        ("BJ-DRINK-003", "椰子水"),
    ]
    assert [(item["sku"], item["name"]) for item in chengdu_drink_items] == [
        ("CD-DRINK-001", "矿泉水"),
        ("CD-DRINK-002", "无糖可乐"),
        ("CD-DRINK-003", "椰子水"),
    ]

    beijing_by_name = {item["name"]: item for item in beijing_drink_items}
    assert beijing_by_name["山姆矿泉水"]["source"] == "山姆配送"
    assert beijing_by_name["山姆矿泉水"]["purchase_channel"] == "山姆配送"
    assert beijing_by_name["无糖可乐"]["source"] == "快驴配送"
    assert beijing_by_name["无糖可乐"]["purchase_channel"] == "快驴"
    assert beijing_by_name["椰子水"]["source"] == "山姆配送"
    assert beijing_by_name["椰子水"]["purchase_channel"] == "山姆配送"

    chengdu_by_name = {item["name"]: item for item in chengdu_drink_items}
    assert chengdu_by_name["矿泉水"]["source"] == "山姆配送（3日内）"
    assert chengdu_by_name["矿泉水"]["purchase_channel"] == "山姆配送"
    assert chengdu_by_name["无糖可乐"]["source"] == "快驴配送（次日达）"
    assert chengdu_by_name["无糖可乐"]["purchase_channel"] == "快驴"
    assert chengdu_by_name["椰子水"]["source"] == "山姆配送（3日内）"
    assert chengdu_by_name["椰子水"]["purchase_channel"] == "山姆配送"

    for item in beijing_drink_items + chengdu_drink_items:
        assert item.get("force_purchase_channel") is True
        assert item["unit"] == "箱"
        assert (root / "daily-order" / "static" / "images" / f"{item['sku']}.svg").exists()


def test_beijing_food_tabs_are_seven_even_columns():
    styles = (Path(__file__).resolve().parents[1] / "daily-order" / "static" / "styles.css").read_text(
        encoding="utf-8"
    )

    assert ".beijing-order-page .secondary-tabs" in styles
    assert "repeat(7, minmax(0, 1fr))" in styles
    assert "font-size: 16px;" in styles
    assert "font-size: 13px;" in styles


def test_sam_delivery_channel_is_available_in_admin_board():
    root = Path(__file__).resolve().parents[1]
    app_py = (root / "daily-order" / "app" / "main.py").read_text(encoding="utf-8")
    admin_js = (root / "daily-order" / "static" / "admin.js").read_text(encoding="utf-8")
    styles = (root / "daily-order" / "static" / "styles.css").read_text(encoding="utf-8")

    assert 'source == "山姆配送"' in app_py
    assert '"山姆配送": 1' in app_py
    assert '{ channel: "山姆配送", label: "山姆配送" }' in admin_js
    assert 'channel.includes("山姆")' in admin_js
    assert ".channel-card.tone-sam" in styles
