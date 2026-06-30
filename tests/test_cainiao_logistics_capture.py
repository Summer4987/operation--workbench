from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "cainiao_logistics_capture.py"


def load_module():
    spec = importlib.util.spec_from_file_location("cainiao_logistics_capture", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def sample_ui_dump() -> str:
    return """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node text="菜鸟裹裹" content-desc="" bounds="[0,0][100,50]" />
  <node text="中通快递" content-desc="" bounds="[0,60][200,110]" />
  <node text="运单号 ZT123456789CN" content-desc="" bounds="[0,120][500,170]" />
  <node text="一次性餐盒" content-desc="" bounds="[0,180][500,230]" />
  <node text="已到菜鸟驿站，待取件" content-desc="" bounds="[0,240][500,290]" />
  <node text="取件码：8-1234" content-desc="" bounds="[0,300][500,350]" />
  <node text="顺丰速运 SF987654321000" content-desc="" bounds="[0,420][500,470]" />
  <node text="派送中" content-desc="" bounds="[0,480][500,530]" />
</hierarchy>
"""


def test_parse_logistics_records_reads_pickup_code_and_tracking_number():
    module = load_module()

    parsed = module.parse_logistics_records(sample_ui_dump(), "银泰城店", "2026-06-30 10:00:00+0800")

    assert parsed["pickup_codes"] == [{"code": "8-1234", "index": 5}]
    assert {"number": "ZT123456789CN", "index": 2} in parsed["tracking_numbers"]
    assert {"number": "SF987654321000", "index": 6} in parsed["tracking_numbers"]
    first = parsed["records"][0]
    assert first["store_name"] == "银泰城店"
    assert first["pickup_code"] == "8-1234"
    assert first["tracking_number"] == "ZT123456789CN"
    assert first["status"] == "待取件"
    assert first["supplier"] == "菜鸟裹裹"


def test_parse_tracking_only_record_without_pickup_code():
    module = load_module()

    parsed = module.parse_logistics_records(sample_ui_dump(), "银泰城店", "2026-06-30 10:00:00+0800")
    tracking_only = [item for item in parsed["records"] if item["tracking_number"] == "SF987654321000"][0]

    assert tracking_only["pickup_code"] == ""
    assert tracking_only["status"] == "派送中"
    assert "SF987654321000" in tracking_only["latest_trace"]


def test_main_fixture_dry_run_writes_evidence(tmp_path, monkeypatch, capsys):
    module = load_module()
    fixture = tmp_path / "dump.xml"
    fixture.write_text(sample_ui_dump(), encoding="utf-8")
    evidence_dir = tmp_path / "evidence"
    latest_path = tmp_path / "latest.json"
    monkeypatch.setattr(module, "LATEST_PATH", latest_path)
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "cainiao_logistics_capture.py",
            "--store-name",
            "银泰城店",
            "--fixture-ui-dump",
            str(fixture),
            "--evidence-dir",
            str(evidence_dir),
        ],
    )

    assert module.main() == 0

    summary = json.loads((evidence_dir / "summary.json").read_text(encoding="utf-8"))
    parsed = json.loads((evidence_dir / "parsed.json").read_text(encoding="utf-8"))
    stdout = json.loads(capsys.readouterr().out)
    assert summary["ok"] is True
    assert summary["records_written"] == 0
    assert summary["record_count"] == 2
    assert parsed["records"][0]["pickup_code"] == "8-1234"
    assert stdout["evidence_dir"] == str(evidence_dir)
    assert json.loads(latest_path.read_text(encoding="utf-8"))["evidence_dir"] == str(evidence_dir)
