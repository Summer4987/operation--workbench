from scripts.sync_promo_budget_overrides import merge_missing_defaults


def test_merge_missing_weekend_defaults_without_overriding_cloud_weekday_budget():
    cloud = {
        "stores": {
            "双井店": {
                "美团": {
                    "lunchBudget": 90,
                    "dinnerBudget": 150,
                }
            }
        }
    }
    defaults = {
        "weekendPreset": {"enabled": True},
        "stores": {
            "双井店": {
                "美团": {
                    "lunchBudget": 70,
                    "dinnerBudget": 120,
                    "weekendLunchBudget": 70,
                    "weekendDinnerBudget": 120,
                }
            }
        },
    }

    merged = merge_missing_defaults(cloud, defaults)

    assert merged["weekendPreset"] == {"enabled": True}
    assert merged["stores"]["双井店"]["美团"]["lunchBudget"] == 90
    assert merged["stores"]["双井店"]["美团"]["dinnerBudget"] == 150
    assert merged["stores"]["双井店"]["美团"]["weekendLunchBudget"] == 70
    assert merged["stores"]["双井店"]["美团"]["weekendDinnerBudget"] == 120
