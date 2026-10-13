from __future__ import annotations

import importlib.util
import pathlib
import sys
import unittest
from unittest import mock


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

    def test_waits_for_account_tabs_before_reading_entry(self):
        frame = mock.Mock()
        with mock.patch.object(self.module, "find_account_frame", return_value=frame), mock.patch.object(self.module, "click_exact_text"), mock.patch.object(self.module, "wait_for_account_frame_text", return_value=(frame, "分店账户明细及转账")) as wait:
            self.assertIs(self.module.open_leaf_balance_detail(mock.Mock()), frame)
        wait.assert_called_once_with(mock.ANY, frame, "分店账户", timeout_seconds=30)

    def test_api_zero_is_confirmed_but_missing_or_invalid_is_not_zero(self):
        payload = {'result': [
            {'shopName': '零余额店', 'adBalance': {'detail': {'balance': 0}}},
            {'shopName': '未返回余额店', 'adBalance': {}},
            {'shopName': '错误余额店', 'adBalance': {'balance': 'invalid'}},
            {'shopName': '非数值店', 'adBalance': {'balance': 'NaN'}},
        ]}
        items = self.module.parse_shop_rows(payload)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['balance'], 0)
        self.assertTrue(items[0]['confirmed_zero'])

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

    def test_uses_new_unit_promotion_funds_route(self) -> None:
        self.assertEqual(
            self.module.ELEME_BALANCE_URL,
            "https://melody.shop.ele.me/app/unit/vas__account#app.unit.vas.account",
        )

    def test_parse_new_leaf_balance_api_rows(self) -> None:
        items = self.module.parse_shop_rows(
            {
                "result": [
                    {
                        "shopId": 545055537,
                        "shopName": "熊小小牛排饭POKEBEAR(滨江店)",
                        "adBalance": {
                            "detail": {"shopId": 545055537, "balance": 31010},
                            "totalCash": 31010,
                        },
                    }
                ]
            }
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["store_id"], "545055537")
        self.assertEqual(items[0]["balance"], 310.10)
        self.assertEqual(items[0]["status"], "normal")


if __name__ == "__main__":
    unittest.main()
