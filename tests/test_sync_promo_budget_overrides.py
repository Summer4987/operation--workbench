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


import unittest
from unittest.mock import patch
from types import SimpleNamespace
import json

class CloudBudgetSyncTest(unittest.TestCase):
    def test_preserves_cloud_and_fills_missing_defaults(self):
        test_merge_missing_weekend_defaults_without_overriding_cloud_weekday_budget()

    def test_ssh_fallback_reads_current_cloud_budget(self):
        from scripts import sync_promo_budget_overrides as mod
        payload = {"stores": {"test": {"美团": {"lunchBudget": 100}}}}
        with patch.object(mod, "SSH_SOURCE", "ubuntu@139.155.148.169:/opt/inventory-board/data/promo_budget_overrides.json"), patch.object(mod.subprocess, "run", return_value=SimpleNamespace(stdout=json.dumps(payload))) as run:
            self.assertEqual(mod.read_remote_ssh(), payload)
        self.assertEqual(run.call_args.args[0][-3:], ["ubuntu@139.155.148.169", "cat", "/opt/inventory-board/data/promo_budget_overrides.json"])
        self.assertIn("BatchMode=yes", run.call_args.args[0])
