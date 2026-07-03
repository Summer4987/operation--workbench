from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_promo_budget_retry_plan as retry_module  # noqa: E402


def test_meituan_store_failure_file_marks_manual_review(tmp_path, monkeypatch):
    preview_path = tmp_path / "outputs" / "promo_budget_preview" / "latest.json"
    overrides_path = tmp_path / "config" / "promo_budget_overrides.json"
    runs_path = tmp_path / "outputs" / "task_runs" / "latest.json"
    output_path = tmp_path / "outputs" / "promo_budget_retry_plan" / "latest.json"
    meituan_dir = tmp_path / "outputs" / "meituan_budget_automation"
    preview_path.parent.mkdir(parents=True)
    overrides_path.parent.mkdir(parents=True)
    runs_path.parent.mkdir(parents=True)
    output_path.parent.mkdir(parents=True)
    meituan_dir.mkdir(parents=True)

    preview_path.write_text(
        json.dumps(
            {
                "meituan_dinner": [
                    {
                        "platform": "美团",
                        "store": "保利中心",
                        "sourceStore": "熊小小牛排饭POKEBEAR（保利中心店）",
                        "period": "晚餐",
                        "targetBudget": 120,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    overrides_path.write_text(json.dumps({"stores": {}}, ensure_ascii=False), encoding="utf-8")
    runs_path.write_text(
        json.dumps(
            {
                "tasks": {
                    "growth.promo_budget": {
                        "status": "failed",
                        "step": "晚餐预算汇总",
                        "message": "晚餐预算失败步骤：美团晚餐预算",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (meituan_dir / "meituan_cdp_晚餐_20260703_173411.json").write_text(
        json.dumps(
            {
                "results": [
                    {
                        "store": "熊小小牛排饭POKEBEAR（保利中心店）",
                        "keyword": "保利中心",
                        "ok": False,
                        "targetBudget": 120,
                        "beforeBudget": 80,
                        "failure_type": "confirm_disabled",
                        "error": "确定按钮禁用，且页面预算=80.0，目标=120.0",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(retry_module, "PREVIEW_PATH", preview_path)
    monkeypatch.setattr(retry_module, "OVERRIDES_PATH", overrides_path)
    monkeypatch.setattr(retry_module, "TASK_RUNS_PATH", runs_path)
    monkeypatch.setattr(retry_module, "OUTPUT_DIR", output_path.parent)
    monkeypatch.setattr(retry_module, "LATEST_PATH", output_path)
    monkeypatch.setattr(retry_module, "MEITUAN_BUDGET_DIR", meituan_dir)

    payload = retry_module.build_payload()

    assert payload["summary"]["manual_count"] == 1
    assert payload["summary"]["safe_retry_count"] == 0
    item = payload["items"][0]
    assert item["store"] == "保利中心"
    assert item["last_run"]["failure_type"] == "confirm_disabled"
    assert "平台拒绝确认预算" in item["manual_reasons"][0]
