from scripts.task_run_state import classify_failure_text


def test_meituan_realtime_switch_failure_is_page_structure():
    assert classify_failure_text("美团页面未确认切换到今日实时") == "page_structure"
