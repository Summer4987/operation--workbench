from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
MAIN_PATH = ROOT / "daily-order" / "app" / "main.py"


def load_daily_order_module():
    spec = importlib.util.spec_from_file_location("daily_order_main_for_tests", MAIN_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def write_order(
    submission_dir: Path,
    order_id: str,
    submitted_at: str,
    quantity: int,
    processed: bool = True,
    store_name: str = "银泰城店",
) -> Path:
    order = {
        "order_id": order_id,
        "store_name": store_name,
        "store_address": "测试地址",
        "remark": "",
        "status": "processed" if processed else "pending",
        "processed_channels": ["快驴"] if processed else [],
        "processed_at": submitted_at if processed else "",
        "submitted_at": submitted_at,
        "client_host": "203.0.113.9",
        "items": [
            {
                "sku": "KL-001",
                "source": "快驴配送",
                "purchase_channel": "快驴",
                "category": "蔬菜",
                "name": "洋葱",
                "spec": "",
                "unit": "斤",
                "note": "",
                "quantity": quantity,
            }
        ],
    }
    path = submission_dir / f"{order_id}_{store_name}.json"
    path.write_text(json.dumps(order, ensure_ascii=False), encoding="utf-8")
    return path


def test_admin_summary_filters_orders_to_requested_month(tmp_path, monkeypatch):
    module = load_daily_order_module()
    submission_dir = tmp_path / "submissions"
    submission_dir.mkdir()
    monkeypatch.setattr(module, "SUBMISSION_DIR", submission_dir)

    write_order(submission_dir, "DO-JUN", "2026-06-15T10:00:00+08:00", 10)
    write_order(submission_dir, "DO-MAY", "2026-05-31T10:00:00+08:00", 99)

    client = TestClient(module.app)
    response = client.get("/daily-order/api/admin/summary?status=processed&month=2026-06&token=daily-order-admin")

    assert response.status_code == 200
    payload = response.json()
    assert payload["month"] == "2026-06"
    assert payload["stats"]["order_count"] == 1
    assert payload["channels"][0]["totals"][0]["quantity"] == 10


def test_channel_status_update_only_touches_requested_month(tmp_path, monkeypatch):
    module = load_daily_order_module()
    submission_dir = tmp_path / "submissions"
    submission_dir.mkdir()
    monkeypatch.setattr(module, "SUBMISSION_DIR", submission_dir)

    june_path = write_order(submission_dir, "DO-JUN", "2026-06-15T10:00:00+08:00", 10, processed=False)
    may_path = write_order(submission_dir, "DO-MAY", "2026-05-31T10:00:00+08:00", 99, processed=False)

    client = TestClient(module.app)
    response = client.patch(
        "/daily-order/api/admin/channels/%E5%BF%AB%E9%A9%B4/status?month=2026-06&token=daily-order-admin",
        json={"status": "processed"},
    )

    assert response.status_code == 200
    assert response.json()["order_ids"] == ["DO-JUN"]
    assert json.loads(june_path.read_text(encoding="utf-8"))["processed_channels"] == ["快驴"]
    assert json.loads(may_path.read_text(encoding="utf-8"))["processed_channels"] == []


def test_daily_admin_summary_includes_beijing_orders(tmp_path, monkeypatch):
    module = load_daily_order_module()
    submission_dir = tmp_path / "submissions"
    beijing_submission_dir = tmp_path / "beijing-submissions"
    submission_dir.mkdir()
    beijing_submission_dir.mkdir()
    monkeypatch.setattr(module, "SUBMISSION_DIR", submission_dir)
    monkeypatch.setattr(module, "BEIJING_SUBMISSION_DIR", beijing_submission_dir)

    write_order(submission_dir, "DO-JUN", "2026-06-15T10:00:00+08:00", 10, processed=False)
    write_order(beijing_submission_dir, "BJ-JUN", "2026-06-16T10:00:00+08:00", 6, processed=False, store_name="朝阳门店")

    client = TestClient(module.app)
    response = client.get("/daily-order/api/admin/summary?status=pending&month=2026-06&token=daily-order-admin")

    assert response.status_code == 200
    payload = response.json()
    assert payload["stats"]["order_count"] == 2
    assert [order["order_id"] for order in payload["orders"]] == ["BJ-JUN", "DO-JUN"]


def test_daily_channel_status_update_can_process_beijing_order(tmp_path, monkeypatch):
    module = load_daily_order_module()
    submission_dir = tmp_path / "submissions"
    beijing_submission_dir = tmp_path / "beijing-submissions"
    submission_dir.mkdir()
    beijing_submission_dir.mkdir()
    monkeypatch.setattr(module, "SUBMISSION_DIR", submission_dir)
    monkeypatch.setattr(module, "BEIJING_SUBMISSION_DIR", beijing_submission_dir)

    beijing_path = write_order(
        beijing_submission_dir,
        "BJ-JUN",
        "2026-06-16T10:00:00+08:00",
        6,
        processed=False,
        store_name="朝阳门店",
    )

    client = TestClient(module.app)
    response = client.patch(
        "/daily-order/api/admin/channels/%E5%BF%AB%E9%A9%B4/status?month=2026-06&token=daily-order-admin",
        json={"status": "processed"},
    )

    assert response.status_code == 200
    assert response.json()["order_ids"] == ["BJ-JUN"]
    assert json.loads(beijing_path.read_text(encoding="utf-8"))["processed_channels"] == ["快驴"]


def test_public_store_order_history_requires_remembered_order_ids(tmp_path, monkeypatch):
    module = load_daily_order_module()
    submission_dir = tmp_path / "submissions"
    submission_dir.mkdir()
    monkeypatch.setattr(module, "SUBMISSION_DIR", submission_dir)

    write_order(submission_dir, "DO-KNOWN", "2026-06-15T10:00:00+08:00", 10)
    write_order(submission_dir, "DO-OTHER", "2026-06-15T11:00:00+08:00", 6)

    client = TestClient(module.app)
    response = client.get("/daily-order/api/orders?store_name=%E9%93%B6%E6%B3%B0%E5%9F%8E%E5%BA%97")
    assert response.status_code == 200
    assert response.json()["items"] == []

    response = client.get(
        "/daily-order/api/orders?store_name=%E9%93%B6%E6%B3%B0%E5%9F%8E%E5%BA%97&order_ids=DO-KNOWN"
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["order_id"] for item in items] == ["DO-KNOWN"]
    assert "client_host" not in items[0]
    assert items[0]["items"][0]["name"] == "洋葱"


def test_order_notification_includes_details_even_with_custom_prefix(monkeypatch):
    module = load_daily_order_module()
    monkeypatch.setenv("DAILY_ORDER_NOTIFY_MESSAGE", "有门店下单啦！")
    order = {
        "order_id": "DO-TEST",
        "store_name": "银泰城店",
        "submitted_at": "2026-07-01T10:30:00+08:00",
        "items": [
            {
                "purchase_channel": "快驴",
                "name": "西兰花",
                "spec": "",
                "quantity": 100,
                "unit": "件",
            }
        ],
    }

    message = module._order_message(order)

    assert "有门店下单啦！" in message
    assert "门店：银泰城店" in message
    assert "订单号：DO-TEST" in message
    assert "渠道：快驴" in message
    assert "- 西兰花 100件" in message


def test_order_lines_can_filter_by_exact_date(tmp_path, monkeypatch):
    module = load_daily_order_module()
    submission_dir = tmp_path / "submissions"
    submission_dir.mkdir()
    monkeypatch.setattr(module, "SUBMISSION_DIR", submission_dir)

    write_order(submission_dir, "DO-JULY-1", "2026-07-01T10:00:00+08:00", 10)
    write_order(submission_dir, "DO-JULY-2", "2026-07-02T10:00:00+08:00", 99)

    rows = module._order_line_rows(date="2026-07-01")

    assert [row["订单号"] for row in rows] == ["DO-JULY-1"]


def test_order_lines_xlsx_endpoint_returns_excel_file(tmp_path, monkeypatch):
    module = load_daily_order_module()
    submission_dir = tmp_path / "submissions"
    submission_dir.mkdir()
    monkeypatch.setattr(module, "SUBMISSION_DIR", submission_dir)
    write_order(submission_dir, "DO-JULY-1", "2026-07-01T10:00:00+08:00", 10)

    client = TestClient(module.app)
    response = client.get("/daily-order/api/admin/order-lines.xlsx?date=2026-07-01&token=daily-order-admin")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert response.content.startswith(b"PK")
    assert b"xl/worksheets/sheet1.xml" in response.content


def test_daily_excel_send_uses_dedicated_wecom_message(tmp_path, monkeypatch):
    module = load_daily_order_module()
    submission_dir = tmp_path / "submissions"
    submission_dir.mkdir()
    monkeypatch.setattr(module, "SUBMISSION_DIR", submission_dir)
    monkeypatch.setenv("DAILY_ORDER_NOTIFY_WEBHOOK", "http://example.invalid/webhook")
    write_order(submission_dir, "DO-JULY-1", "2026-07-01T10:00:00+08:00", 10)
    calls = []
    monkeypatch.setattr(module, "_send_notify_text", lambda webhook, notify_type, text, extra_payload=None: calls.append((webhook, notify_type, text, extra_payload)) or True)

    result = module._send_daily_excel_link("2026-07-01")

    assert result["status"] == "sent"
    assert result["line_count"] == 1
    assert calls[0][1] == "wecom"
    assert "日配订货 Excel 已生成" in calls[0][2]
    assert "order-lines.xlsx" in calls[0][2]


def test_wechat_digest_send_does_not_attach_excel_link(tmp_path, monkeypatch):
    module = load_daily_order_module()
    submission_dir = tmp_path / "submissions"
    submission_dir.mkdir()
    monkeypatch.setattr(module, "SUBMISSION_DIR", submission_dir)
    monkeypatch.setenv("DAILY_ORDER_NOTIFY_WEBHOOK", "http://example.invalid/webhook")
    write_order(submission_dir, "DO-WECHAT", "2026-07-01T10:00:00+08:00", 2, store_name="银泰城店")
    path = next(submission_dir.glob("DO-WECHAT_*.json"))
    order = json.loads(path.read_text(encoding="utf-8"))
    order["items"][0]["purchase_channel"] = "大米群"
    order["items"][0]["name"] = "大米"
    order["items"][0]["unit"] = "袋"
    path.write_text(json.dumps(order, ensure_ascii=False), encoding="utf-8")
    calls = []
    monkeypatch.setattr(module, "_send_notify_text", lambda webhook, notify_type, text, extra_payload=None: calls.append(text) or True)

    client = TestClient(module.app)
    response = client.post("/daily-order/api/admin/wechat-digest/send?date=2026-07-01&token=daily-order-admin")

    assert response.status_code == 200
    payload = response.json()
    assert "excel" not in payload
    assert calls
    assert all("order-lines.xlsx" not in text for text in calls)
