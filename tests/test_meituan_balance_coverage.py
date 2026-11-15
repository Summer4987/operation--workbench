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
         patch.object(module, "collect_direct_meituan", side_effect=AssertionError("must not browse")):
        payload, ok = module.collect_all_balances()
    assert ok
    assert payload["collected_platforms"] == ["饿了么"]
    assert payload["delegated_platforms"]["美团"]["status"] == "delegated"
    assert "余额未核实" in payload["delegated_platforms"]["美团"]["message"]


def test_meituan_balance_collection_includes_wangjing_and_knows_binjiang_id():
    text = MEITUAN_BALANCE.read_text(encoding="utf-8")

    assert '"keyword": "望京"' in text
    assert '"望京": "33766612"' in text
    assert '"滨江": "34062471"' in text
