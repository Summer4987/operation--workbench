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


def test_cli_fails_closed_for_partial_or_missing_budget_coverage(tmp_path,monkeypatch,capsys):
    payload={'status':'failed','period':'晚餐','platforms':{'meituan':{'success_count':4,'total':15,'failed_count':11}},'message':'美团成功 4/15 家'}
    monkeypatch.setattr(result,'build_result',lambda period,since:payload)
    monkeypatch.setattr(result.sys,'argv',['result','--period','晚餐','--since-epoch','0','--output',str(tmp_path/'result.json'),'--check-success','--print-message'])
    assert result.main()==1
    assert '4/15' in capsys.readouterr().out
    payload['status']='success'
    assert result.main()==0
