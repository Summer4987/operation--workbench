import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "eleme_single_store_budget",
    ROOT / "scripts" / "eleme_single_store_budget.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_parse_budget_text_reads_dashboard_value():
    assert MODULE.parse_budget_text("每日预算\n已消耗0%\n¥\n150\n推广出价") == 150


def test_select_rows_filters_store_without_expanding_scope():
    payload = {
        "eleme_lunch": [
            {"time": "10:30", "store": "甲店", "shopId": 1, "targetBudget": 80},
            {"time": "10:30", "store": "乙店", "shopId": 2, "targetBudget": 100},
        ],
        "eleme_dinner": [],
    }
    rows = MODULE.select_rows(payload, "10:30", stores="乙店")
    assert [row["shopId"] for row in rows] == [2]
