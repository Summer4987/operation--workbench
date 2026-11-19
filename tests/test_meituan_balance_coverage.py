from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ALL_BALANCES = ROOT / "store-inspection" / "cdp_all_balances.py"
MEITUAN_BALANCE = ROOT / "store-inspection" / "one_click_meituan_balance.py"


def test_total_balance_collection_delegates_meituan_without_browser_fallback():
    import importlib.util
    import sys
    from unittest.mock import patch
    sys.path.insert(0, str(ROOT / "store-inspection"))
    spec = importlib.util.spec_from_file_location("all_balances_source_test", ALL_BALANCES)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    items = [{"platform": "饿了么", "store_name": "测试", "balance": 500}]
    with patch.object(module, "collect_eleme", return_value=(items, "")), \
         patch.object(module, "collect_meituan", side_effect=AssertionError("must not browse")), \
         patch.object(module, "collect_direct_meituan", side_effect=AssertionError("must not browse")), \
         patch.object(module, "read_balance_items", return_value=([{ "platform": "美团", "store_name": "望京", "balance": 12.34}], [])):
        payload, ok = module.collect_all_balances()
    assert ok
    assert set(payload["collected_platforms"]) == {"饿了么", "美团"}
    assert not payload["balance_collection_issues"]
    assert any(i["balance"] == 12.34 for i in payload["items"] if i["platform"] == "美团")


def test_meituan_balance_collection_includes_wangjing_and_knows_binjiang_id():
    text = MEITUAN_BALANCE.read_text(encoding="utf-8")

    assert '"keyword": "望京"' in text
    assert '"望京": "33766612"' in text
    assert '"滨江": "34062471"' in text


def test_fleet_only_never_starts_browser_and_preserves_original_eleme_time(tmp_path):
    import importlib.util, sys, json
    from datetime import datetime, timedelta
    from unittest.mock import patch
    sys.path.insert(0,str(ROOT/'store-inspection'))
    spec=importlib.util.spec_from_file_location('fleet_only_balances',ALL_BALANCES)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    captured=(datetime.now()-timedelta(minutes=60)).strftime('%F %T')
    path=tmp_path/'latest.json'
    path.write_text(json.dumps({'generated_at':captured,'items':[{'platform':'饿了么','store_name':'测试','balance':12}]}))
    with patch.object(module,'ROOT',tmp_path),patch.object(module,'collect_eleme',side_effect=AssertionError('must not browse')), \
         patch.object(module,'read_balance_items',return_value=([{'platform':'美团','store_name':'望京','balance':13}],[])):
        payload,ok=module.collect_all_balances(fleet_only=True)
        ele=next(i for i in payload['items'] if i['platform']=='饿了么')
        assert ok and ele['collected_at']==captured
        # A new aggregate timestamp must not extend the underlying balance age.
        payload['generated_at']=datetime.now().strftime('%F %T')
        ele['collected_at']=(datetime.now()-timedelta(minutes=91)).strftime('%F %T')
        path.write_text(json.dumps(payload))
        payload,ok=module.collect_all_balances(fleet_only=True)
        assert not ok and all(i['platform']=='美团' for i in payload['items'])
        assert any(i['platform']=='饿了么' for i in payload['balance_collection_issues'])
