from scripts import build_promo_budget_result as result


def test_summary_counts_success_failed_and_missing_stores():
    expected = [
        {"keyword": "总部A", "status": "auto"},
        {"keyword": "直营B", "status": "auto"},
        {"keyword": "总部C", "status": "auto"},
    ]
    payloads = [
        {
            "mode": "commit",
            "results": [
                {"keyword": "总部A", "ok": True},
                {"keyword": "直营B", "ok": False, "failure_type": "auth_block", "error": "登录页"},
            ]
        }
    ]

    summary = result.summarize_platform("meituan", expected, payloads)

    assert summary["status"] == "failed"
    assert summary["success_count"] == 1
    assert summary["failed_count"] == 2
    assert summary["failed_stores"] == ["直营B", "总部C"]


def test_final_message_always_contains_both_platform_counts():
    platforms = {
        "eleme": {"status": "success", "success_count": 15, "total": 15, "failed_count": 0, "failed_stores": []},
        "meituan": {"status": "failed", "success_count": 11, "total": 15, "failed_count": 4, "failed_stores": ["A", "B", "C", "D"]},
    }

    message = result.build_message("晚餐", platforms)

    assert "饿了么：成功；成功 15/15 家" in message
    assert "美团：有失败；成功 11/15 家；失败 4 家（A、B、C、D）" in message


def test_expected_tasks_accepts_eleme_scheduled_and_meituan_auto():
    preview = {
        "eleme_dinner": [{"store": "饿A", "status": "scheduled"}, {"store": "已停", "status": "disabled"}],
        "meituan_dinner": [{"store": "美A", "status": "auto"}],
    }

    assert [item["store"] for item in result.expected_tasks(preview, "eleme", "晚餐")] == ["饿A"]
    assert [item["store"] for item in result.expected_tasks(preview, "meituan", "晚餐")] == ["美A"]
