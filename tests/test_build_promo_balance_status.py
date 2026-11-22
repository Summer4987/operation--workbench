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
        self.assertEqual(status["recharge_plan"]["status"], "pending_verification")
        self.assertIn("不能判断", status["recharge_plan"]["message"])
        self.assertNotIn("没有低余额", status["recharge_plan"]["next_action"])
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

    def test_confirmed_zero_keeps_evidence_in_warning_cards(self) -> None:
        items = [
            {"platform": "饿了么", "store_name": store, "balance": 0.0,
             "status": "warning", "confirmed_zero": True,
             "source": "Chrome CDP接口读取", "balance_field": "adBalance.totalWithoutCard"}
            for store in ("金融城店", "万象城店")
        ]
        status = self.module.build_status({
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "threshold": 200, "items": items,
        })
        self.assertEqual(len(status["low_balance_items"]), 2)
        self.assertEqual(status["unconfirmed_balance_items"], [])
        for item in status["low_balance_items"]:
            self.assertEqual(item["balance"], 0.0)
            self.assertTrue(item["confirmed_zero"])
            self.assertEqual(item["source"], "Chrome CDP接口读取")
            self.assertEqual(item["balance_field"], "adBalance.totalWithoutCard")
            self.assertFalse(self.module.is_unconfirmed_zero_balance(item))

    def test_unconfirmed_page_zero_stays_out_of_warning_cards(self) -> None:
        payload = {"threshold": 200, "items": [{
            "platform": "饿了么", "store_name": "金融城店", "balance": 0.0,
            "status": "warning", "source": "Chrome CDP页面表格读取",
        }]}
        self.assertEqual(self.module.low_balance_items(payload), [])
        self.assertEqual(len(self.module.unconfirmed_balance_items(payload)), 1)

    def test_legacy_api_zero_keeps_its_confirmation_source(self) -> None:
        payload = {"threshold": 200, "items": [{
            "platform": "饿了么", "store_name": "金融城店", "balance": 0.0,
            "status": "warning", "source": "Chrome CDP接口读取",
        }]}
        warning = self.module.low_balance_items(payload)[0]
        self.assertFalse(self.module.is_unconfirmed_zero_balance(warning))

    def test_selected_direct_meituan_stores_are_excluded_from_low_balance_warning(self) -> None:
        payload = {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "threshold": 200,
            "items": [
                {
                    "platform": "美团",
                    "store_name": f"熊小小牛排饭POKEBEAR（{store_name}）",
                    "balance": 31.89,
                    "status": "warning",
                    "source": "Chrome CDP接口读取",
                }
                for store_name in ("朝阳门店", "银泰城店", "万象城店", "金融城店", "保利中心店")
            ]
            + [
                {
                    "platform": "饿了么",
                    "store_name": "朝阳门店",
                    "balance": 20,
                    "status": "warning",
                    "source": "Chrome CDP接口读取",
                },
                {
                    "platform": "美团",
                    "store_name": "金融街店",
                    "balance": 50,
                    "status": "warning",
                    "source": "Chrome CDP接口读取",
                },
            ],
            "summary": {"store_count": 7, "platform_count": 2, "warning_count": 7},
        }

        status = self.module.build_status(payload)

        self.assertEqual(status["summary"]["store_count"], 7)
        self.assertEqual(status["summary"]["low_balance_count"], 2)
        self.assertEqual(status["summary"]["excluded_low_balance_count"], 5)
        self.assertEqual(
            {(item["platform"], item["store_name"]) for item in status["low_balance_items"]},
            {("饿了么", "朝阳门店"), ("美团", "金融街店")},
        )
        self.assertEqual(len(status["excluded_low_balance_items"]), 5)
        self.assertEqual(status["recharge_plan"]["item_count"], 2)
        self.assertGreater(status["direct_coverage"]["expected_count"], 5)


if __name__ == "__main__":
    unittest.main()


def test_delegated_meituan_is_visible_and_never_reported_as_verified_balance():
    import importlib.util
    spec = importlib.util.spec_from_file_location('delegated_balance_status', ROOT / 'scripts/build_promo_balance_status.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    payload = {
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'collected_platforms': ['饿了么'],
        'delegated_platforms': {'美团': {'status': 'delegated', 'source': 'longxia_snapshot', 'message': '龙虾统一读取；账户余额未核实。'}},
        'items': [{'platform': '饿了么', 'store_name': name, 'balance': 500} for name in ('朝阳门店', '银泰城店', '万象城店', '金融城店', '保利中心店')],
    }
    result = module.build_status(payload)
    assert '余额未核实' in result['message']
    assert result['status'] == 'warning'
    assert not module.direct_coverage_rows(payload)
    assert next(row for row in module.platform_rows(payload, []) if row['platform'] == '美团')['status'] == 'delegated'


def test_semicolons_inside_one_transport_error_do_not_invent_platform_failures():
    module=load_module()
    message='饿了么：Chrome/CDP 接入超时；两次连接均未完成；请检查 Mac mini 总部 Chrome。'
    rows=module.split_platform_failures(message)
    assert len(rows)==1 and rows[0]['platform']=='饿了么'
    assert '两次连接均未完成；请检查' in rows[0]['message']
    both=module.split_platform_failures(message+'；美团：安全验证')
    assert [r['platform'] for r in both]==['饿了么','美团']
