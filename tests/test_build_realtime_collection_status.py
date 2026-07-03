from scripts.build_realtime_collection_status import classify_payload_failure


def test_payload_error_overrides_generic_execution_failed_task_run():
    payload = {
        "errors": [
            "美团采集失败：美团当前停留在单店上下文：保利中心店，未进入连锁/全部门店实时排行。"
        ]
    }
    task_run = {"failure_type": "execution_failed"}

    assert classify_payload_failure(payload, task_run) == "page_structure"
