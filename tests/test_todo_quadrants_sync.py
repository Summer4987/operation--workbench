from __future__ import annotations

import importlib.util
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
MAIN_PATH = ROOT / "daily-order" / "app" / "main.py"


def load_daily_order_module():
    spec = importlib.util.spec_from_file_location("daily_order_todo_sync_for_tests", MAIN_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_todo_quadrants_sync_requires_token(tmp_path, monkeypatch):
    module = load_daily_order_module()
    monkeypatch.setattr(module, "TODO_QUADRANTS_PATH", tmp_path / "todo-quadrants.json")

    client = TestClient(module.app)
    response = client.get("/daily-order/api/todo-quadrants?token=wrong")

    assert response.status_code == 403


def test_todo_quadrants_sync_round_trips_items(tmp_path, monkeypatch):
    module = load_daily_order_module()
    monkeypatch.setattr(module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(module, "TODO_QUADRANTS_PATH", tmp_path / "todo-quadrants.json")

    client = TestClient(module.app)
    empty = client.get("/daily-order/api/todo-quadrants?token=xiongxiaoxiao-todo-sync")
    assert empty.status_code == 200
    assert empty.json() == {"updated_at": "", "items": []}

    payload = {
        "items": [
            {
                "id": "8C627A5D-6521-4E1D-B6F1-11A0CECBDE6B",
                "title": "补充平台待办",
                "category": "platform",
                "quadrant": "importantUrgent",
                "is_completed": False,
                "created_at": "2026-08-06T10:00:00Z",
                "updated_at": "2026-08-06T10:05:00Z",
                "completed_at": "",
            }
        ]
    }
    saved = client.put("/daily-order/api/todo-quadrants?token=xiongxiaoxiao-todo-sync", json=payload)
    assert saved.status_code == 200
    assert saved.json()["updated_at"]
    assert saved.json()["items"][0]["title"] == "补充平台待办"

    fetched = client.get("/daily-order/api/todo-quadrants?token=xiongxiaoxiao-todo-sync")
    assert fetched.status_code == 200
    assert fetched.json() == saved.json()
