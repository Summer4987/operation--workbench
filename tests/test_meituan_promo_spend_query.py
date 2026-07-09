from __future__ import annotations

import importlib.util
import pathlib
import sys
import types
import unittest
from unittest import mock


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
        self.assertEqual(snapshot["budget"], 80)
        self.assertEqual(snapshot["budget_percent"], 53)
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
        self.assertEqual(snapshot["budget"], 100)
        self.assertEqual(snapshot["budget_percent"], 100)
        self.assertEqual(snapshot["source"], "budget_exhausted")

    def test_parse_budget_percent_from_single_line_text(self) -> None:
        text = "推广实况 加载中... 推广设置 每日预算 已消耗 17% 120 元 推广出价 0 元"
        snapshot = self.query.parse_spend_snapshot(text)
        self.assertEqual(snapshot["today_spend"], 20.4)
        self.assertEqual(snapshot["source"], "budget_percent")

    def test_task_store_aliases_expand_short_brand_names(self) -> None:
        aliases = self.query.task_store_aliases(
            {
                "keyword": "川湘府",
                "store": "熊小小牛排饭POKEBEAR(第5号档口川湘府美食城店)",
            }
        )

        self.assertIn("川湘府", aliases)
        self.assertIn("第5号档口", aliases)

    def test_task_store_aliases_include_third_stall_food_court(self) -> None:
        aliases = self.query.task_store_aliases({"keyword": "第3档口"})

        self.assertIn("第3档口", aliases)
        self.assertIn("吉祥美食城", aliases)

    def test_select_headquarters_store_accepts_current_single_store_ad_page(self) -> None:
        page = types.SimpleNamespace(
            url="https://waimaieapp.meituan.com/ad/v1/rpc?wmPoiId=32022526",
        )

        with mock.patch.object(
            self.query,
            "visible_page_text",
            return_value="推广首页 推广预算 已消耗0% 80 元",
        ):
            selected = self.query.select_headquarters_store(
                page,
                {"keyword": "保利中心", "store": "熊小小牛排饭POKEBEAR（保利中心店）", "wmPoiId": "32022526"},
            )

        self.assertEqual(selected, "保利中心")

    def test_direct_query_uses_base_url_when_wm_poi_id_is_absent(self) -> None:
        page = types.SimpleNamespace(
            url="https://e.waimai.meituan.com/",
            goto=mock.Mock(),
            close=mock.Mock(),
        )
        context = types.SimpleNamespace(new_page=mock.Mock(return_value=page))
        helpers = {
            "context_for_task": mock.Mock(return_value=context),
            "base_url_for_task": mock.Mock(return_value="https://e.waimai.meituan.com/#https://waimaieapp.meituan.com/ad/v1/pc"),
            "wm_poi_id": mock.Mock(side_effect=RuntimeError("没有门店 wmPoiId")),
            "url_for_store": mock.Mock(),
            "enter_dianjin_with_recovery": mock.Mock(),
            "wait_setting_ready": mock.Mock(return_value={}),
            "page_text": mock.Mock(return_value="总推广花费\n120元\n"),
            "classify_failure": mock.Mock(return_value="execution_failed"),
            "save_failure_evidence": mock.Mock(),
        }

        result = self.query.query_task(
            {"keyword": "万象城", "directMeituanAccountId": "direct_wanxiangcheng"},
            helpers,
            playwright=None,
            contexts={},
            launched_contexts=[],
            base_url="",
            direct_accounts={},
        )

        self.assertTrue(result["ok"])
        page.goto.assert_called_once_with(
            "https://e.waimai.meituan.com/#https://waimaieapp.meituan.com/ad/v1/pc",
            wait_until="domcontentloaded",
            timeout=45_000,
        )
        helpers["url_for_store"].assert_not_called()

    def test_format_human_reports_failures_plainly(self) -> None:
        text = self.query.format_human(
            [
                {"keyword": "银泰城", "ok": True, "today_spend": 150.01, "budget": 200, "remaining_budget": 49.99, "budget_percent": 75},
                {"keyword": "万象城", "ok": False, "error": "登录失效"},
            ]
        )
        self.assertIn("美团推广实时消耗巡检", text)
        self.assertIn("总览：已读到 1/2 家", text)
        self.assertIn("今日消耗 150.01 元，当前预算 200 元，剩余 49.99 元，使用率 75%", text)
        self.assertNotIn("昨日", text)
        self.assertIn("2. 万象城：未核实。原因：登录失效", text)

    def test_format_human_reports_budget_warning(self) -> None:
        text = self.query.format_human(
            [
                {
                    "keyword": "银泰城",
                    "ok": True,
                    "today_spend": 95,
                    "budget": 100,
                    "budget_percent": 95,
                    "source": "budget_percent",
                },
            ]
        )

        self.assertIn("预警 1", text)
        self.assertIn("1. 银泰城：预警，今日消耗 95 元，当前预算 100 元，使用率 95%，已消耗预算 95%", text)
        self.assertIn("本巡检只读", text)

    def test_apply_budget_fields_uses_configured_budget_for_remaining(self) -> None:
        record = {"today_spend": 75}

        self.query.apply_budget_fields(record, 100)

        self.assertEqual(record["budget"], 100)
        self.assertEqual(record["remaining_budget"], 25)
        self.assertEqual(record["budget_percent"], 75)
        self.assertEqual(record["budget_source"], "configured")

    def test_format_human_compacts_playwright_call_log(self) -> None:
        text = self.query.format_human(
            [
                {
                    "keyword": "第3档口",
                    "ok": False,
                    "error": "Locator.click: Timeout 8000ms exceeded. Call log: <div class=\"backdrop_pypeX0\"> intercepts pointer events",
                },
            ]
        )

        self.assertIn("1. 第3档口：未核实。原因：页面弹出遮罩层挡住门店选择器", text)
        self.assertNotIn("Call log", text)


if __name__ == "__main__":
    unittest.main()
