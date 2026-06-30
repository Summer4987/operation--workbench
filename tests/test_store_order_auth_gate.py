from __future__ import annotations

import importlib.util
import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]


def load_daily_order_module():
    main_path = ROOT / "daily-order" / "app" / "main.py"
    spec = importlib.util.spec_from_file_location("daily_order_auth_gate_for_tests", main_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_inventory_module():
    package_name = "inventory_board_auth_gate_for_tests"
    package = types.ModuleType(package_name)
    package.__path__ = [str(ROOT / "inventory-board" / "app")]
    sys.modules[package_name] = package

    main_path = ROOT / "inventory-board" / "app" / "main.py"
    spec = importlib.util.spec_from_file_location(f"{package_name}.main", main_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"{package_name}.main"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_chengdu_daily_order_redirects_without_trailing_slash(monkeypatch):
    module = load_daily_order_module()
    monkeypatch.delenv("STORE_ORDER_ACCOUNTS_JSON", raising=False)
    monkeypatch.delenv("STORE_ORDER_ACCOUNTS_FILE", raising=False)

    client = TestClient(module.app, follow_redirects=False)
    response = client.get("/daily-order")

    assert response.status_code == 307
    assert response.headers["location"] == "/daily-order/"


def test_chengdu_daily_order_shows_login_when_auth_file_is_configured(tmp_path, monkeypatch):
    module = load_daily_order_module()
    monkeypatch.delenv("STORE_ORDER_ACCOUNTS_JSON", raising=False)
    monkeypatch.setenv("STORE_ORDER_ACCOUNTS_FILE", str(tmp_path / "missing-accounts.json"))

    client = TestClient(module.app)
    response = client.get("/daily-order/")

    assert response.status_code == 200
    assert "熊小小成都门店订货" in response.text
    assert "请输入门店账号密码" in response.text
    assert "/daily-order/api/auth/login" in response.text
    assert "viewport-fit=cover" in response.text
    assert "100dvh" in response.text
    assert "@media (max-width: 420px)" in response.text


def test_store_ops_shows_single_login_when_auth_file_is_configured(tmp_path, monkeypatch):
    module = load_daily_order_module()
    monkeypatch.delenv("STORE_ORDER_ACCOUNTS_JSON", raising=False)
    monkeypatch.setenv("STORE_ORDER_ACCOUNTS_FILE", str(tmp_path / "missing-accounts.json"))

    client = TestClient(module.app)
    response = client.get("/store-ops/")

    assert response.status_code == 200
    assert "熊小小门店订货系统" in response.text
    assert "请输入门店账号密码" in response.text
    assert "/daily-order/api/auth/login" in response.text
    assert 'const nextPath = "/store-ops/"' in response.text


def test_daily_order_submit_shows_login_when_auth_file_is_configured(tmp_path, monkeypatch):
    module = load_inventory_module()
    monkeypatch.delenv("STORE_ORDER_ACCOUNTS_JSON", raising=False)
    monkeypatch.setenv("STORE_ORDER_ACCOUNTS_FILE", str(tmp_path / "missing-accounts.json"))

    client = TestClient(module.app)
    response = client.get("/order-submit?token=xiongxiaoxiao-order")

    assert response.status_code == 200
    assert "熊小小日配订货" in response.text
    assert "请输入门店账号密码" in response.text
    assert "/api/public-order/auth/login" in response.text
    assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate"
    assert "viewport-fit=cover" in response.text
    assert "100dvh" in response.text
    assert "@media (max-height: 520px)" in response.text
    assert "login_at=${Date.now()}" in response.text


def test_operation_login_page_fits_small_screens():
    module = load_inventory_module()
    client = TestClient(module.app)
    response = client.get("/login")

    assert response.status_code == 200
    assert "熊小小业务中心" in response.text
    assert "viewport-fit=cover" in response.text
    assert "100dvh" in response.text
    assert "@media (max-width: 420px)" in response.text


def test_daily_order_submit_catalog_returns_authenticated_store(monkeypatch):
    module = load_inventory_module()
    monkeypatch.setenv(
        "STORE_ORDER_ACCOUNTS_JSON",
        json.dumps({"accounts": {"store-user": {"password": "secret", "store_name": "测试门店"}}}, ensure_ascii=False),
    )
    monkeypatch.setattr(module, "public_order_catalog", lambda: {"stores": [], "products": []})
    monkeypatch.setattr(module, "inventory_summary", lambda: [])

    client = TestClient(module.app)
    login = client.post(
        "/api/public-order/auth/login?token=xiongxiaoxiao-order",
        json={"username": "store-user", "password": "secret"},
    )
    assert login.status_code == 200

    response = client.get("/api/public-order/catalog?token=xiongxiaoxiao-order")

    assert response.status_code == 200
    payload = response.json()
    assert payload["authenticated_store"]["name"] == "测试门店"
    assert payload["stores"][0]["name"] == "测试门店"

    page = client.get("/order-submit?token=xiongxiaoxiao-order")
    assert page.status_code == 200
    assert page.headers["cache-control"] == "no-store, no-cache, must-revalidate"
    assert "已校验门店" in page.text
    assert "测试门店" in page.text
    assert "请核对当前账号对应门店后再下单" in page.text
    assert "?." not in page.text


def test_daily_order_submit_accepts_chengdu_session_cookie_for_owner(monkeypatch):
    daily_module = load_daily_order_module()
    inventory_module = load_inventory_module()
    accounts = {"accounts": {"owner": {"password": "secret", "role": "owner"}}}
    monkeypatch.setenv("STORE_ORDER_ACCOUNTS_JSON", json.dumps(accounts, ensure_ascii=False))
    monkeypatch.setattr(
        inventory_module,
        "public_order_catalog",
        lambda: {"stores": [{"name": "银泰城店"}, {"name": "金融城店"}], "products": []},
    )
    monkeypatch.setattr(inventory_module, "inventory_summary", lambda: [])

    cookie = daily_module._sign_store_order_session("owner", "", "owner")
    client = TestClient(inventory_module.app)
    response = client.get(
        "/api/public-order/catalog?token=xiongxiaoxiao-order",
        headers={"Cookie": f"store_order_session={cookie}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert "authenticated_store" not in payload
    assert [store["name"] for store in payload["stores"]] == ["银泰城店", "金融城店"]


def test_daily_order_submit_owner_page_keeps_store_selector(monkeypatch):
    module = load_inventory_module()
    monkeypatch.setenv(
        "STORE_ORDER_ACCOUNTS_JSON",
        json.dumps({"accounts": {"owner": {"password": "secret", "role": "owner"}}}, ensure_ascii=False),
    )

    client = TestClient(module.app)
    login = client.post(
        "/api/public-order/auth/login?token=xiongxiaoxiao-order",
        json={"username": "owner", "password": "secret"},
    )
    assert login.status_code == 200

    page = client.get("/order-submit?token=xiongxiaoxiao-order")

    assert page.status_code == 200
    assert "请核对当前账号对应门店后再下单" not in page.text
    assert '<select id="storeSelect"' in page.text


def test_daily_order_submit_logout_clears_store_session(monkeypatch):
    module = load_inventory_module()
    monkeypatch.setenv(
        "STORE_ORDER_ACCOUNTS_JSON",
        json.dumps({"accounts": {"store-user": {"password": "secret", "store_name": "测试门店"}}}, ensure_ascii=False),
    )
    monkeypatch.setattr(module, "public_order_catalog", lambda: {"stores": [], "products": []})
    monkeypatch.setattr(module, "inventory_summary", lambda: [])

    client = TestClient(module.app)
    login = client.post(
        "/api/public-order/auth/login?token=xiongxiaoxiao-order",
        json={"username": "store-user", "password": "secret"},
    )
    assert login.status_code == 200
    assert client.get("/api/public-order/catalog?token=xiongxiaoxiao-order").status_code == 200

    logout = client.post("/api/public-order/auth/logout?token=xiongxiaoxiao-order")

    assert logout.status_code == 200
    assert client.get("/api/public-order/catalog?token=xiongxiaoxiao-order").status_code == 401


def test_signed_daily_order_file_links_download_without_store_cookie(tmp_path, monkeypatch):
    module = load_inventory_module()
    monkeypatch.setenv(
        "STORE_ORDER_ACCOUNTS_JSON",
        json.dumps({"accounts": {"store-user": {"password": "secret", "store_name": "测试门店"}}}, ensure_ascii=False),
    )
    monkeypatch.setenv("INVENTORY_PASSWORD", "operation-secret")
    monkeypatch.setattr(module, "OUTPUT_DIR", tmp_path)
    order_file = tmp_path / "DO-TEST.xlsx"
    order_file.write_bytes(b"excel-bytes")

    client = TestClient(module.app)
    listing = client.get("/api/public-order/files?token=xiongxiaoxiao-order")

    assert listing.status_code == 200
    download_url = listing.json()["items"][0]["download_url"]
    assert "expires=" in download_url
    assert "sig=" in download_url

    download = client.get(download_url)
    assert download.status_code == 200
    assert download.content == b"excel-bytes"

    page = client.get(f"/order-file/{order_file.name}?{download_url.split('?', 1)[1]}")
    assert page.status_code == 200
    assert "下载 Excel 文件" in page.text

    blocked = client.get(f"/api/order/files/{order_file.name}?token=xiongxiaoxiao-order")
    assert blocked.status_code == 401


def test_daily_order_submit_hermes_message_includes_media_attachment():
    module = load_inventory_module()
    result = {
        "file": "/opt/inventory-board/data/order_outputs/熊小小牛排饭订单模板_20260630_120000.xlsx",
        "items": [
            {
                "store_name": "银泰城店",
                "product_name": "熊小小牛排饭-冷冻西兰花（冻）",
                "quantity": 6,
                "unit": "袋",
            }
        ],
    }

    message = module._order_submit_hermes_message(result, "熊小小牛排饭订单模板_20260630_120000.xlsx", "http://example.test/order-file.xlsx")

    assert "熊小小日配订货 Excel 已生成，文件见附件。" in message
    assert "门店：银泰城店" in message
    assert "冷冻西兰花（冻） 6袋" in message
    assert "下载：http://example.test/order-file.xlsx" in message
    assert "MEDIA:/opt/inventory-board/data/order_outputs/熊小小牛排饭订单模板_20260630_120000.xlsx" in message


def test_daily_order_submit_hermes_dry_run_writes_log_without_sending(tmp_path, monkeypatch):
    module = load_inventory_module()
    monkeypatch.setenv("ORDER_NOTIFY_TYPE", "hermes")
    monkeypatch.setenv("ORDER_NOTIFY_DRY_RUN", "1")
    monkeypatch.setenv("ORDER_NOTIFY_LOG_DIR", str(tmp_path))

    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("dry-run should not call Hermes")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    module._notify_order_submit(
        {
            "file": "/tmp/order.xlsx",
            "items": [{"store_name": "银泰城店", "product_name": "商品", "quantity": 1, "unit": "件"}],
        },
        "order.xlsx",
        "",
    )

    logs = list(tmp_path.glob("order-notify-dry-run-*.log"))
    assert not calls
    assert len(logs) == 1
    assert "MEDIA:/tmp/order.xlsx" in logs[0].read_text(encoding="utf-8")


def test_daily_order_submit_hermes_uses_configured_group_target(monkeypatch):
    module = load_inventory_module()
    monkeypatch.setenv("ORDER_NOTIFY_TYPE", "hermes")
    monkeypatch.delenv("ORDER_NOTIFY_DRY_RUN", raising=False)
    monkeypatch.setenv("ORDER_HERMES_BIN", "/usr/local/bin/hermes")
    monkeypatch.setenv("ORDER_HERMES_TARGET", "熊小小牛排饭-易代仓仓储配送群")

    calls = []

    class Completed:
        returncode = 0
        stdout = "ok"

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return Completed()

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module, "_write_order_notify_log", lambda status, text: None)

    module._notify_order_submit(
        {
            "file": "/tmp/order.xlsx",
            "items": [{"store_name": "银泰城店", "product_name": "商品", "quantity": 1, "unit": "件"}],
        },
        "order.xlsx",
        "",
    )

    assert calls[0][0][:4] == ["/usr/local/bin/hermes", "send", "--to", "熊小小牛排饭-易代仓仓储配送群"]
    assert "MEDIA:/tmp/order.xlsx" in calls[0][0][4]


def test_daily_order_history_filters_to_authenticated_store(tmp_path, monkeypatch):
    module = load_inventory_module()
    db_module = sys.modules["inventory_board_auth_gate_for_tests.db"]
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "inventory.sqlite3")
    module.init_db()
    monkeypatch.setenv(
        "STORE_ORDER_ACCOUNTS_JSON",
        json.dumps({"accounts": {"store-user": {"password": "secret", "store_name": "银泰城店"}}}, ensure_ascii=False),
    )
    monkeypatch.setenv("INVENTORY_PASSWORD", "operation-secret")

    with module.connect() as conn:
        yintai_id = module.create_import(
            conn,
            file_hash="hash-yintai",
            filename="银泰城日配.xlsx",
            movement_type="outbound",
            source="cloud_order",
        )
        other_id = module.create_import(
            conn,
            file_hash="hash-other",
            filename="其他门店日配.xlsx",
            movement_type="outbound",
            source="cloud_order",
        )
        for import_id, store_name, sku in ((yintai_id, "银泰城店", "SKU-1"), (other_id, "金融城店", "SKU-2")):
            conn.execute(
                """
                INSERT INTO movements (
                    import_file_id, row_key, movement_type, sku, name, spec, unit, warehouse, address, store_name,
                    quantity, signed_quantity, document_date, source_row, created_at
                )
                VALUES (?, ?, 'outbound', ?, ?, '', '斤', '', '', ?, 6, -6, '2026-06-29', 1, '2026-06-29T12:00:00+08:00')
                """,
                (import_id, f"row-{sku}", sku, sku, store_name),
            )
            module.finish_import(conn, import_id, status="success", line_count=1)

    client = TestClient(module.app)
    login = client.post(
        "/api/public-order/auth/login?token=xiongxiaoxiao-order",
        json={"username": "store-user", "password": "secret"},
    )
    assert login.status_code == 200

    response = client.get("/api/public-order/orders?token=xiongxiaoxiao-order")

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["filename"] for item in items] == ["银泰城日配.xlsx"]
    assert items[0]["total_quantity"] == 6
    assert items[0]["items"] == [
        {
            "sku": "SKU-1",
            "name": "SKU-1",
            "spec": "",
            "unit": "斤",
            "quantity": 6.0,
        }
    ]
    assert "expires=" in items[0]["download_url"]
    assert "sig=" in items[0]["download_url"]


def test_chengdu_catalog_returns_authenticated_store(monkeypatch):
    module = load_daily_order_module()
    monkeypatch.setenv(
        "STORE_ORDER_ACCOUNTS_JSON",
        json.dumps({"accounts": {"store-user": {"password": "secret", "store_name": "测试门店"}}}, ensure_ascii=False),
    )
    monkeypatch.setattr(module, "_load_catalog", lambda: {"stores": [], "items": []})

    client = TestClient(module.app)
    login = client.post("/daily-order/api/auth/login", json={"username": "store-user", "password": "secret"})
    assert login.status_code == 200

    response = client.get("/daily-order/api/catalog")

    assert response.status_code == 200
    payload = response.json()
    assert payload["authenticated_store"]["name"] == "测试门店"
    assert payload["stores"][0]["name"] == "测试门店"


def test_chengdu_owner_account_can_see_all_stores(monkeypatch):
    module = load_daily_order_module()
    monkeypatch.setenv(
        "STORE_ORDER_ACCOUNTS_JSON",
        json.dumps({"accounts": {"owner": {"password": "secret", "role": "owner"}}}, ensure_ascii=False),
    )
    monkeypatch.setattr(
        module,
        "_load_catalog",
        lambda path=module.CATALOG_PATH: {
            "stores": [{"name": "银泰城店"}, {"name": "金融城店"}],
            "items": [],
        },
    )

    client = TestClient(module.app)
    login = client.post("/daily-order/api/auth/login", json={"username": "owner", "password": "secret"})
    assert login.status_code == 200

    response = client.get("/daily-order/api/catalog")

    assert response.status_code == 200
    payload = response.json()
    assert "authenticated_store" not in payload
    assert [store["name"] for store in payload["stores"]] == ["银泰城店", "金融城店"]


def test_chengdu_owner_account_can_submit_for_selected_store(tmp_path, monkeypatch):
    module = load_daily_order_module()
    monkeypatch.setenv(
        "STORE_ORDER_ACCOUNTS_JSON",
        json.dumps({"accounts": {"owner": {"password": "secret", "role": "owner"}}}, ensure_ascii=False),
    )
    monkeypatch.setattr(module, "SUBMISSION_DIR", tmp_path / "submissions")
    monkeypatch.setattr(module, "ORDER_LINES_PATH", tmp_path / "order-lines.csv")
    monkeypatch.setattr(module, "_notify_order", lambda order: None)
    monkeypatch.setattr(module, "_notify_wechat_addon", lambda order: None)
    monkeypatch.setattr(
        module,
        "_load_catalog",
        lambda path=module.CATALOG_PATH: {
            "stores": [{"name": "银泰城店", "address": "成都银泰"}],
            "items": [
                {
                    "sku": "SKU-1",
                    "source": "测试",
                    "purchase_channel": "快驴",
                    "category": "食材",
                    "name": "测试商品",
                    "spec": "",
                    "unit": "袋",
                    "note": "",
                    "stock_status": "有货",
                }
            ],
        },
    )

    client = TestClient(module.app)
    login = client.post("/daily-order/api/auth/login", json={"username": "owner", "password": "secret"})
    assert login.status_code == 200

    response = client.post(
        "/daily-order/api/orders",
        json={"store_name": "银泰城店", "items": [{"sku": "SKU-1", "quantity": 2}]},
    )

    assert response.status_code == 200
    saved = json.loads(next((tmp_path / "submissions").glob("*.json")).read_text(encoding="utf-8"))
    assert saved["store_name"] == "银泰城店"


def test_chengdu_daily_order_logout_clears_store_session(monkeypatch):
    module = load_daily_order_module()
    monkeypatch.setenv(
        "STORE_ORDER_ACCOUNTS_JSON",
        json.dumps({"accounts": {"store-user": {"password": "secret", "store_name": "测试门店"}}}, ensure_ascii=False),
    )
    monkeypatch.setattr(module, "_load_catalog", lambda: {"stores": [], "items": []})

    client = TestClient(module.app)
    login = client.post("/daily-order/api/auth/login", json={"username": "store-user", "password": "secret"})
    assert login.status_code == 200
    assert client.get("/daily-order/api/catalog").status_code == 200

    logout = client.post("/daily-order/api/auth/logout")

    assert logout.status_code == 200
    assert client.get("/daily-order/api/catalog").status_code == 401


def test_chengdu_daily_order_logout_page_returns_login_and_clears_session(monkeypatch):
    module = load_daily_order_module()
    monkeypatch.setenv(
        "STORE_ORDER_ACCOUNTS_JSON",
        json.dumps({"accounts": {"store-user": {"password": "secret", "store_name": "测试门店"}}}, ensure_ascii=False),
    )
    monkeypatch.setattr(module, "_load_catalog", lambda: {"stores": [], "items": []})

    client = TestClient(module.app)
    login = client.post("/daily-order/api/auth/login", json={"username": "store-user", "password": "secret"})
    assert login.status_code == 200
    assert client.get("/daily-order/api/catalog").status_code == 200

    logout = client.get("/daily-order/logout")

    assert logout.status_code == 200
    assert "请输入门店账号密码" in logout.text
    assert "no-store" in logout.headers["cache-control"]
    assert client.get("/daily-order/api/catalog").status_code == 401


def test_wechat_addon_messages_keep_digest_format_and_mark_addon():
    module = load_daily_order_module()
    order = {
        "store_name": "测试门店",
        "items": [
            {"sku": "A", "name": "青菜", "unit": "斤", "quantity": 2, "purchase_channel": "四川鸿鹄微信群"},
            {"sku": "A", "name": "青菜", "unit": "斤", "quantity": 3, "purchase_channel": "四川鸿鹄微信群"},
            {"sku": "B", "name": "米饭", "unit": "袋", "quantity": 1, "purchase_channel": "快驴"},
        ],
    }

    shanghai = timezone(timedelta(hours=8))
    assert module._is_wechat_addon_time(datetime(2026, 6, 29, 18, 0, tzinfo=shanghai))
    assert module._is_wechat_addon_time(datetime(2026, 6, 29, 23, 59, tzinfo=shanghai))
    assert not module._is_wechat_addon_time(datetime(2026, 6, 29, 17, 59, tzinfo=shanghai))
    assert module._wechat_addon_messages(order) == ["【四川鸿鹄微信群 加单】\n测试门店：青菜 5斤"]
