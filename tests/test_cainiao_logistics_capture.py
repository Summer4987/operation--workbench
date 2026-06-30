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


def detail_ui_dump() -> str:
    return """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node text="中通快递 79015504368326" content-desc="" bounds="[0,60][500,110]" />
  <node text="复制" content-desc="" bounds="[0,120][100,170]" />
  <node text="运输中" content-desc="" bounds="[0,180][500,230]" />
  <node text="【成都市】 快件已到达 成都转运中心" content-desc="" bounds="[0,240][500,290]" />
  <node text="送至 成都市 武侯区 石羊街道 新街里6c区3楼3035号熊小小牛排饭" content-desc="" bounds="[0,300][500,350]" />
  <node text="唐 18418974867-1306" content-desc="" bounds="[0,360][500,410]" />
  <node text="隐私小号" content-desc="" bounds="[0,420][500,470]" />
  <node text="淘宝 | 买给【唐】的一次性牛皮纸汤桶圆形粥桶汤杯纸碗外卖带盖圆形打包盒商用纸餐盒" content-desc="" bounds="[0,480][500,530]" />
</hierarchy>
"""


def list_ui_dump() -> str:
    return """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node text="查收28" content-desc="" bounds="[46,727][223,812]" />
  <node text="运输中" content-desc="" bounds="[106,847][235,905]" />
  <node text="运输中" content-desc="" bounds="[319,936][448,994]" />
  <node text="90%概率明天送达" content-desc="" bounds="[460,936][809,994]" />
  <node text="淘宝 | 买给【唐】的一次性牛皮纸汤桶圆形粥桶汤杯纸碗外卖带盖圆形打包盒商用纸餐盒" content-desc="" bounds="[319,1008][973,1058]" />
  <node text="运输中" content-desc="" bounds="[319,1172][448,1230]" />
  <node text="90%概率明天送达" content-desc="" bounds="[460,1172][809,1230]" />
  <node text="淘宝 | 买给【安美灵】的【1件包邮】裙带菜 海木耳 海螺旋藻 海藻干货500g 散装称重" content-desc="" bounds="[319,1244][973,1294]" />
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


def test_parse_detail_page_excludes_recipient_phone_number():
    module = load_module()

    parsed = module.parse_logistics_records(detail_ui_dump(), "", "2026-06-30 10:00:00+0800")

    assert parsed["tracking_numbers"] == [{"number": "79015504368326", "index": 0}]
    assert len(parsed["records"]) == 1
    assert parsed["store_name"] == "金融城店"
    assert parsed["records"][0]["store_name"] == "金融城店"
    assert parsed["records"][0]["tracking_number"] == "79015504368326"
    assert parsed["records"][0]["status"] == "运输中"


def test_list_detail_targets_ignores_group_header_and_limits():
    module = load_module()

    targets = module.list_detail_targets(list_ui_dump(), 1)

    assert targets == [{"x": 500, "y": 965, "text": "运输中"}]


def test_infer_store_name_falls_back_when_address_unknown():
    module = load_module()

    assert module.infer_store_name(["送至 未知地址"], "银泰城店") == "银泰城店"


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
