from __future__ import annotations

import importlib.util
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
    assert "viewport-fit=cover" in response.text
    assert "100dvh" in response.text
    assert "@media (max-height: 520px)" in response.text


def test_operation_login_page_fits_small_screens():
    module = load_inventory_module()
    client = TestClient(module.app)
    response = client.get("/login")

    assert response.status_code == 200
    assert "熊小小业务中心" in response.text
    assert "viewport-fit=cover" in response.text
    assert "100dvh" in response.text
    assert "@media (max-width: 420px)" in response.text
