from datetime import datetime

from scripts.build_workbench_data import remove_legacy_untrusted_meituan_income, reset_stale_realtime


def test_legacy_meituan_api_income_is_removed_before_rendering():
    realtime = {
        "generated_at": "2026-06-18 20:00:57",
        "summary": {"total_income": 6988.97},
        "stores": [
            {
                "store": "双井",
                "orders": 143,
                "income": 6988.97,
                "platforms": {
                    "美团": {"orders": 83, "income": 5162.8, "source": "api"},
                    "饿了么": {"orders": 60, "income": 1826.17, "source": "api"},
                },
            }
        ],
    }

    cleaned = remove_legacy_untrusted_meituan_income(realtime)

    assert cleaned["stores"][0]["income"] == 1826.17
    assert cleaned["stores"][0]["platforms"]["美团"]["income"] == 0
    assert cleaned["stores"][0]["platforms"]["美团"]["income_status"] == "missing"
    assert cleaned["summary"]["total_income"] == 1826.17


def test_stale_realtime_resets_to_zero_for_new_day():
    realtime = {
        "generated_at": "2026-06-18 20:00:57",
        "target_stores": ["双井"],
        "stores": [
            {
                "store": "双井",
                "orders": 143,
                "income": 1826.17,
                "platforms": {
                    "美团": {"orders": 83, "income": 0, "source_store": "熊小小牛排饭POKEBEAR（双井店）"},
                    "饿了么": {"orders": 60, "income": 1826.17, "source_store": "熊小小牛排饭POKEBEAR(双井店)"},
                },
            }
        ],
    }

    reset = reset_stale_realtime(realtime, datetime(2026, 6, 19, 0, 1))

    assert reset["status"] == "reset"
    assert reset["generated_at"] == "2026-06-19 00:00:00"
    assert reset["summary"]["total_orders"] == 0
    assert reset["summary"]["total_income"] == 0
    assert reset["stores"][0]["orders"] == 0
    assert reset["stores"][0]["income"] == 0
    assert reset["stores"][0]["platforms"]["美团"]["orders"] == 0
