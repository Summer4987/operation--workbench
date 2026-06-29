from __future__ import annotations

import importlib.util
import json
import sys
import types
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
    assert "?." not in page.text


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
