from __future__ import annotations

import importlib.util
import pathlib
import sys
import unittest
from datetime import datetime, timedelta


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "build_promo_balance_status.py"


def load_module():
    spec = importlib.util.spec_from_file_location("build_promo_balance_status_for_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class BuildPromoBalanceStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module()

    def test_stale_balance_result_does_not_report_low_balance_items(self) -> None:
        stale_time = datetime.now() - timedelta(hours=3)
        payload = {
            "generated_at": stale_time.strftime("%Y-%m-%d %H:%M:%S"),
            "threshold": 200,
            "items": [
                {
                    "platform": "饿了么",
                    "store_name": "熊小小牛排饭POKEBEAR（丽泽门店）",
                    "balance": 6.2,
                    "status": "warning",
                    "source": "Chrome CDP接口读取",
                }
            ],
            "summary": {"store_count": 1, "platform_count": 1, "warning_count": 1},
        }
        status = self.module.build_status(payload)
        self.assertEqual(status["status"], "stale")
        self.assertEqual(status["low_balance_items"], [])
        self.assertEqual(status["recharge_plan"]["item_count"], 0)
        self.assertTrue(status["summary"]["source_is_stale"])
        self.assertIn("旧余额没有当前商业价值", status["message"])

    def test_fresh_balance_result_can_report_low_balance_items(self) -> None:
        fresh_time = datetime.now() - timedelta(minutes=5)
        payload = {
            "generated_at": fresh_time.strftime("%Y-%m-%d %H:%M:%S"),
            "threshold": 200,
            "items": [
                {
                    "platform": "美团",
                    "store_name": "熊小小牛排饭POKEBEAR（金融街店）",
                    "balance": 194.9,
                    "status": "warning",
                    "source": "Chrome CDP接口读取",
                }
            ],
            "summary": {"store_count": 1, "platform_count": 1, "warning_count": 1},
        }
        status = self.module.build_status(payload)
        self.assertEqual(status["status"], "warning")
        self.assertEqual(len(status["low_balance_items"]), 1)
        self.assertFalse(status["summary"]["source_is_stale"])


if __name__ == "__main__":
    unittest.main()
