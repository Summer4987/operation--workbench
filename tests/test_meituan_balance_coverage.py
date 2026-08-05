from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ALL_BALANCES = ROOT / "store-inspection" / "cdp_all_balances.py"
MEITUAN_BALANCE = ROOT / "store-inspection" / "one_click_meituan_balance.py"


def test_total_balance_collection_includes_direct_meituan_and_validates_coverage():
    text = ALL_BALANCES.read_text(encoding="utf-8")

    assert "import cdp_direct_meituan_balance" in text
    assert '("美团直营", collect_direct_meituan)' in text
    assert "cdp_direct_meituan_balance.enabled_accounts(None)" in text
    assert "failed_items = [item for item in items if item.get(\"error\")]" in text
    assert "if store not in DIRECT_MEITUAN_CHAIN_STORES" in text
    assert 'apply_direct_coverage(build_result(items, THRESHOLD), {"饿了么", "美团"})' in text


def test_meituan_balance_collection_includes_wangjing_and_binjiang():
    text = MEITUAN_BALANCE.read_text(encoding="utf-8")

    assert '"keyword": "望京"' in text
    assert '"望京": "33766612"' in text
    assert '"keyword": "滨江"' in text
    assert '"滨江": "34062471"' in text
