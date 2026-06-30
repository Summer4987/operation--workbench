from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_sender_module():
    script = ROOT / "inventory-board" / "scripts" / "wechat_gui_sender.py"
    spec = importlib.util.spec_from_file_location("wechat_gui_sender_for_tests", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_dry_run_reports_target_message_and_file(tmp_path):
    module = load_sender_module()
    file_path = tmp_path / "order.xlsx"
    file_path.write_bytes(b"excel")

    payload = module.send("皮皮球球备忘录", "测试消息", file_path, dry_run=True)

    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["target"] == "皮皮球球备忘录"
    assert payload["message"] == "测试消息"
    assert payload["file"] == str(file_path)


def test_missing_file_is_rejected(tmp_path):
    module = load_sender_module()

    try:
        module.send("皮皮球球备忘录", "测试消息", tmp_path / "missing.xlsx", dry_run=True)
    except FileNotFoundError as exc:
        assert "missing.xlsx" in str(exc)
    else:
        raise AssertionError("missing file should fail before touching WeChat")
