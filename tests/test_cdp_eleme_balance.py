from __future__ import annotations

import importlib.util
import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "store-inspection" / "cdp_eleme_balance.py"


def load_module():
    sys.path.insert(0, str(SCRIPT_PATH.parent))
    spec = importlib.util.spec_from_file_location("cdp_eleme_balance_for_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class CdpElemeBalanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module()

    def test_parse_dom_balance_rows(self) -> None:
        items = self.module.parse_dom_balance_rows(
            [
                {
                    "shopId": "524321320",
                    "shopName": "熊小小牛排饭POKEBEAR(万象城店)",
                    "balance": "752.74",
                },
                {
                    "shopId": "1300114063",
                    "shopName": "熊小小牛排饭POKEBEAR(金融城店)",
                    "balance": "176.12",
                },
            ]
        )

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["platform"], "饿了么")
        self.assertEqual(items[0]["store_id"], "524321320")
        self.assertEqual(items[0]["balance"], 752.74)
        self.assertEqual(items[0]["status"], "normal")
        self.assertEqual(items[0]["source"], "Chrome CDP页面表格读取")
        self.assertEqual(items[1]["status"], "warning")

    def test_parse_dom_balance_rows_skips_invalid_rows(self) -> None:
        items = self.module.parse_dom_balance_rows(
            [
                {"shopId": "1", "shopName": "", "balance": "752.74"},
                {"shopId": "2", "shopName": "熊小小牛排饭POKEBEAR(测试店)", "balance": ""},
            ]
        )

        self.assertEqual(items, [])


if __name__ == "__main__":
    unittest.main()
