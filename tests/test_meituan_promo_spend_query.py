from __future__ import annotations

import importlib.util
import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "meituan_promo_spend_query.py"


def load_module():
    spec = importlib.util.spec_from_file_location("meituan_promo_spend_query_for_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class MeituanPromoSpendQueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.query = load_module()

    def test_parse_realtime_spend_snapshot(self) -> None:
        text = """
        实时数据
        今日 06-30 22:13 更新，指标解读
        推广实况
        推广花费
        150.01元
        昨日150元
        推广曝光量
        3,185次
        历史数据
        推广效果
        推广花费
        880.05元
        """
        snapshot = self.query.parse_spend_snapshot(text)
        self.assertEqual(snapshot["today_spend"], 150.01)
        self.assertEqual(snapshot["yesterday_spend"], 150)
        self.assertEqual(snapshot["source"], "realtime")
        self.assertEqual(snapshot["updated_at_hint"], "06-30 22:13")

    def test_parse_homepage_total_as_fallback(self) -> None:
        text = """
        推广首页
        我的账户
        总推广花费
        自动提预算
        详情
        124.02元
        总曝光量
        """
        snapshot = self.query.parse_spend_snapshot(text)
        self.assertEqual(snapshot["today_spend"], 124.02)
        self.assertEqual(snapshot["source"], "homepage_total")

    def test_parse_budget_percent_when_realtime_is_empty(self) -> None:
        text = """
        推广实况
        暂无数据
        历史数据
        推广效果
        推广花费
        780元
        推广设置
        推广预算
        已消耗53%
        80
        元
        """
        snapshot = self.query.parse_spend_snapshot(text)
        self.assertEqual(snapshot["today_spend"], 42.4)
        self.assertEqual(snapshot["source"], "budget_percent")
        self.assertIsNone(snapshot["seven_day_spend"])

    def test_parse_budget_exhausted_when_realtime_is_empty(self) -> None:
        text = """
        推广实况
        暂无数据
        推广设置
        每日预算
        预算已耗尽
        100
        元
        推广出价
        """
        snapshot = self.query.parse_spend_snapshot(text)
        self.assertEqual(snapshot["today_spend"], 100)
        self.assertEqual(snapshot["source"], "budget_exhausted")

    def test_format_human_reports_failures_plainly(self) -> None:
        text = self.query.format_human(
            [
                {"keyword": "银泰城", "ok": True, "today_spend": 150.01, "yesterday_spend": 150},
                {"keyword": "万象城", "ok": False, "error": "登录失效"},
            ]
        )
        self.assertIn("查到了 1/2 家美团门店", text)
        self.assertIn("银泰城：今日 150.01 元", text)
        self.assertIn("没查到的门店：万象城：登录失效", text)


if __name__ == "__main__":
    unittest.main()
