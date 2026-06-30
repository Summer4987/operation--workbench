from __future__ import annotations

import argparse
import importlib.util
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_delivery_module():
    script = ROOT / "inventory-board" / "scripts" / "deliver_order_outputs_with_hermes.py"
    spec = importlib.util.spec_from_file_location("daily_order_hermes_delivery_for_tests", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def args(tmp_path, **overrides):
    values = {
        "server": "http://example.test",
        "token": "token",
        "output_dir": str(tmp_path / "orders"),
        "state_path": str(tmp_path / "state.json"),
        "log_dir": str(tmp_path / "logs"),
        "hermes_bin": "/usr/local/bin/hermes",
        "sender": "hermes",
        "wechat_gui_bin": str(tmp_path / "wechat_gui_sender.py"),
        "target": "熊小小牛排饭-易代仓仓储配送群",
        "latest": 20,
        "init_baseline": False,
        "dry_run": False,
        "json": True,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def sample_item(filename="熊小小牛排饭订单模板_20260630_120000.xlsx"):
    return {
        "filename": filename,
        "size": 12,
        "mtime": 1782796489,
        "download_url": "/api/order/files/order.xlsx?token=token",
    }


def test_init_baseline_marks_existing_files_without_download_or_send(tmp_path, monkeypatch):
    module = load_delivery_module()
    item = sample_item()
    monkeypatch.setattr(module, "fetch_order_files", lambda server, token, latest: [item])

    payload = module.deliver(args(tmp_path, init_baseline=True))

    state = module.load_state(tmp_path / "state.json")
    assert payload["status"] == "baseline"
    assert payload["marked"] == 1
    assert module.item_key(item) in state["delivered"]


def test_dry_run_downloads_and_logs_media_message_without_marking_sent(tmp_path, monkeypatch):
    module = load_delivery_module()
    item = sample_item()
    monkeypatch.setattr(module, "fetch_order_files", lambda server, token, latest: [item])
    monkeypatch.setattr(module, "fetch_bytes", lambda url: b"excel-bytes")

    payload = module.deliver(args(tmp_path, dry_run=True))

    downloaded = tmp_path / "orders" / item["filename"]
    logs = list((tmp_path / "logs").glob("*.json"))
    state = module.load_state(tmp_path / "state.json")
    assert downloaded.read_bytes() == b"excel-bytes"
    assert payload["sent"] == 0
    assert len(logs) == 1
    assert f"MEDIA:{downloaded}" in logs[0].read_text(encoding="utf-8")
    assert module.item_key(item) not in state["delivered"]


def test_successful_delivery_calls_group_and_records_state(tmp_path, monkeypatch):
    module = load_delivery_module()
    item = sample_item()
    calls = []
    monkeypatch.setattr(module, "fetch_order_files", lambda server, token, latest: [item])
    monkeypatch.setattr(module, "fetch_bytes", lambda url: b"excel-bytes")

    def fake_send(message, target, hermes_bin):
        calls.append((message, target, hermes_bin))
        return subprocess.CompletedProcess(args=["hermes"], returncode=0, stdout="ok")

    monkeypatch.setattr(module, "send_with_hermes", fake_send)

    payload = module.deliver(args(tmp_path))
    state = module.load_state(tmp_path / "state.json")

    assert payload["sent"] == 1
    assert calls[0][1] == "熊小小牛排饭-易代仓仓储配送群"
    assert "MEDIA:" in calls[0][0]
    assert module.item_key(item) in state["delivered"]


def test_successful_delivery_can_use_wechat_gui_sender(tmp_path, monkeypatch):
    module = load_delivery_module()
    item = sample_item()
    calls = []
    monkeypatch.setattr(module, "fetch_order_files", lambda server, token, latest: [item])
    monkeypatch.setattr(module, "fetch_bytes", lambda url: b"excel-bytes")

    def fake_send(message, target, file_path, sender_bin):
        calls.append((message, target, file_path, sender_bin))
        return subprocess.CompletedProcess(args=["wechat-gui"], returncode=0, stdout='{"ok": true}')

    monkeypatch.setattr(module, "send_with_wechat_gui", fake_send)

    payload = module.deliver(args(tmp_path, sender="wechat-gui", target="皮皮球球备忘录"))
    state = module.load_state(tmp_path / "state.json")

    assert payload["sent"] == 1
    assert calls[0][1] == "皮皮球球备忘录"
    assert calls[0][2].name == item["filename"]
    assert "MEDIA:" not in calls[0][0]
    assert "文件：" in calls[0][0]
    assert module.item_key(item) in state["delivered"]


def test_failed_wechat_gui_delivery_is_not_marked_sent(tmp_path, monkeypatch):
    module = load_delivery_module()
    item = sample_item()
    monkeypatch.setattr(module, "fetch_order_files", lambda server, token, latest: [item])
    monkeypatch.setattr(module, "fetch_bytes", lambda url: b"excel-bytes")

    def fake_send(message, target, file_path, sender_bin):
        return subprocess.CompletedProcess(args=["wechat-gui"], returncode=1, stdout="微信没有可操作窗口")

    monkeypatch.setattr(module, "send_with_wechat_gui", fake_send)

    payload = module.deliver(args(tmp_path, sender="wechat-gui", target="皮皮球球备忘录"))
    state = module.load_state(tmp_path / "state.json")

    assert payload["sent"] == 0
    assert payload["failed"] == 1
    assert module.item_key(item) not in state["delivered"]


def test_delivered_items_are_skipped(tmp_path, monkeypatch):
    module = load_delivery_module()
    item = sample_item()
    state = {"delivered": {}}
    module.mark_delivered(state, item, "sent")
    module.save_state(tmp_path / "state.json", state)
    monkeypatch.setattr(module, "fetch_order_files", lambda server, token, latest: [item])

    payload = module.deliver(args(tmp_path))

    assert payload["pending"] == 0
    assert payload["sent"] == 0
