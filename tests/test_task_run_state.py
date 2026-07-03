from pathlib import Path

from scripts import task_run_state
from scripts.task_run_state import classify_failure_text, record_task_event


def test_meituan_realtime_switch_failure_is_page_structure():
    assert classify_failure_text("美团页面未确认切换到今日实时") == "page_structure"


def test_meituan_single_store_context_failure_is_page_structure():
    assert classify_failure_text("美团当前停留在单店上下文：保利中心店，未进入连锁/全部门店实时排行") == "page_structure"


def test_meituan_verify_slider_failure_is_auth_block():
    assert classify_failure_text("美团登录态失效：身份核实，请按照说明拖动滑块") == "auth_block"


def test_success_extra_does_not_keep_previous_failure_fields(tmp_path, monkeypatch):
    latest_path = tmp_path / "latest.json"
    monkeypatch.setattr(task_run_state, "RUN_STATE_DIR", tmp_path)
    monkeypatch.setattr(task_run_state, "LATEST_PATH", latest_path)
    monkeypatch.setattr(task_run_state, "ROOT", Path("/tmp/workbench"))

    record_task_event(
        "ops.morning_collection",
        "failed",
        message="上午运营一键采集完成，但有失败项：证据上传。",
        extra={"failures": "证据上传"},
    )
    task = record_task_event(
        "ops.morning_collection",
        "success",
        message="上午运营一键采集完成。",
        extra={"mode": "commit", "source": "scheduled"},
    )

    assert task["extra"] == {"mode": "commit", "source": "scheduled"}
