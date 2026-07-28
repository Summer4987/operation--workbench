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

    def test_dianjin_url_for_store_rewrites_nested_meituan_shell_url(self) -> None:
        base_url = (
            "https://e.waimai.meituan.com/#"
            "https://waimaieapp.meituan.com/ad/v1/rpc?token=abc&wmPoiId=111#/index"
        )

        target = self.query.dianjin_url_for_store(base_url, "30703865")

        self.assertIn("token=abc", target)
        self.assertIn("wmPoiId=30703865", target)
        self.assertIn("#/subapp/isomor_cpc/pages/index/index", target)
        self.assertNotIn("wmPoiId=111#/index", target)

    def test_dianjin_url_for_store_rewrites_plain_meituan_ad_url(self) -> None:
        base_url = "https://waimaieapp.meituan.com/ad/v1/rpc?token=abc&wmPoiId=111#/index"

        target = self.query.dianjin_url_for_store(base_url, "32346101")

        self.assertEqual(
            target,
            "https://waimaieapp.meituan.com/ad/v1/rpc?token=abc&wmPoiId=32346101#/subapp/isomor_cpc/pages/index/index",
        )

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

    def test_task_store_aliases_include_wangjing(self) -> None:
        aliases = self.query.task_store_aliases(
            {
                "keyword": "望京",
                "store": "熊小小牛排饭POKEBEAR（望京店）",
                "sourceStore": "望京店",
            }
        )

        self.assertIn("望京", aliases)
        self.assertIn("望京店", aliases)

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

    def test_compact_error_message_hides_selector_url_noise(self) -> None:
        reason = self.query.compact_error_message(
            "总部账号页面没有找到“全部门店”选择器。 当前URL："
            "https://waimaieapp.meituan.com/ad/v1/rpc?_source=PC&token=secret&wmPoiId=32022526"
        )

        self.assertEqual(reason, "总部账号门店选择器未出现，未能切换门店")
        self.assertNotIn("https://", reason)
        self.assertNotIn("token=", reason)

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
            timeout=30_000,
        )
        helpers["url_for_store"].assert_not_called()

    def test_headquarters_query_uses_direct_ad_url_when_wm_poi_id_exists(self) -> None:
        page = types.SimpleNamespace(
            url="https://e.waimai.meituan.com/",
            goto=mock.Mock(),
            close=mock.Mock(),
        )
        context = types.SimpleNamespace(pages=[page])
        helpers = {
            "context_for_task": mock.Mock(return_value=context),
            "wm_poi_id": mock.Mock(return_value="32346101"),
            "url_for_store": mock.Mock(return_value="https://waimaieapp.meituan.com/ad/v1/rpc?token=abc&wmPoiId=32346101"),
            "enter_dianjin_with_recovery": mock.Mock(),
            "wait_setting_ready": mock.Mock(return_value={}),
            "page_text": mock.Mock(return_value="推广实况\n推广花费\n79.01元\n推广设置\n推广预算\n已消耗99%\n80\n元\n"),
            "classify_failure": mock.Mock(return_value="execution_failed"),
            "save_failure_evidence": mock.Mock(),
        }

        with mock.patch.object(
            self.query,
            "wait_parseable_spend_snapshot",
            return_value=(
                {"today_spend": 79.01, "budget": 80, "budget_percent": 98.76, "source": "realtime"},
                "推广实况\n推广花费\n79.01元\n推广设置\n推广预算\n已消耗99%\n80\n元\n",
            ),
        ) as wait_fast:
            result = self.query.query_task(
                {"keyword": "川湘府", "store": "熊小小牛排饭POKEBEAR(第5号档口川湘府美食城店)", "wmPoiId": "32346101"},
                helpers,
                playwright=None,
                contexts={},
                launched_contexts=[],
                base_url="https://waimaieapp.meituan.com/ad/v1/rpc?token=abc&wmPoiId=32022526",
                direct_accounts={},
            )

        self.assertTrue(result["ok"])
        page.goto.assert_called_once_with(
            "https://waimaieapp.meituan.com/ad/v1/rpc?token=abc&wmPoiId=32346101#/subapp/isomor_cpc/pages/index/index",
            wait_until="domcontentloaded",
            timeout=30_000,
        )
        helpers["enter_dianjin_with_recovery"].assert_not_called()
        helpers["wait_setting_ready"].assert_not_called()
        wait_fast.assert_called_once()
        self.assertEqual(result["selected_store"], "川湘府")

    def test_wait_parseable_spend_snapshot_returns_as_soon_as_current_data_is_visible(self) -> None:
        class FakeLocator:
            def inner_text(self, timeout=0):
                return "推广实况\n推广花费\n66.50元\n推广设置\n每日预算\n已消耗 55% 120 元"

        class FakeFrame:
            def locator(self, selector):
                return FakeLocator()

        page = types.SimpleNamespace(frames=[FakeFrame()], url="https://waimaieapp.meituan.com/ad/v1/rpc")

        snapshot, text = self.query.wait_parseable_spend_snapshot(page, configured_budget=120, timeout_seconds=0.1)

        self.assertEqual(snapshot["today_spend"], 66.5)
        self.assertEqual(snapshot["budget"], 120)
        self.assertEqual(snapshot["remaining_budget"], 53.5)
        self.assertIn("推广花费", text)

    def test_zero_budget_percent_is_not_current_when_configured_budget_exists(self) -> None:
        snapshot = {
            "today_spend": 0.0,
            "budget": 0.0,
            "budget_percent": 0.0,
            "source": "budget_percent",
            "updated_at_hint": "",
        }

        self.assertFalse(self.query.snapshot_is_current_enough(snapshot, configured_budget=120))

    def test_positive_budget_percent_can_still_be_current_fallback(self) -> None:
        snapshot = {
            "today_spend": 66.0,
            "budget": 120.0,
            "budget_percent": 55.0,
            "source": "budget_percent",
            "updated_at_hint": "",
        }

        self.assertTrue(self.query.snapshot_is_current_enough(snapshot, configured_budget=120))

    def test_format_human_reports_failures_plainly(self) -> None:
        text = self.query.format_human(
            [
                {"keyword": "银泰城", "ok": True, "today_spend": 150.01, "budget": 200, "remaining_budget": 49.99, "budget_percent": 75},
                {"keyword": "万象城", "ok": False, "error": "登录失效"},
            ]
        )
        self.assertIn("美团推广实时消耗巡检", text)
        self.assertIn("总览：已读到 1/2 家", text)
        self.assertIn("门店   状态   消耗   预算   剩余   用量", text)
        self.assertIn("银泰城", text)
        self.assertIn("150.01", text)
        self.assertIn("49.99", text)
        self.assertNotIn("昨日", text)
        self.assertIn("万象城", text)
        self.assertIn("登录失效", text)

    def test_format_human_uses_source_store_for_direct_account(self) -> None:
        text = self.query.format_human(
            [
                {
                    "keyword": "雅宝",
                    "sourceStore": "朝阳门店",
                    "displayName": "朝阳门店",
                    "directMeituanAccountId": "direct_chaoyangmen",
                    "ok": True,
                    "today_spend": 200.01,
                    "budget": 200,
                    "remaining_budget": 0,
                    "budget_percent": 100,
                    "source": "budget_exhausted",
                },
            ]
        )

        self.assertIn("已耗尽 1", text)
        self.assertIn("朝阳门店", text)
        self.assertIn("已耗尽", text)

    def test_all_period_prefers_current_meal_budget_keys(self) -> None:
        self.assertEqual(self.query.meituan_task_keys("all", hour=19), ["meituan_dinner", "meituan_lunch"])
        self.assertEqual(self.query.meituan_task_keys("all", hour=10), ["meituan_lunch", "meituan_dinner"])

    def test_parallel_groups_keep_headquarters_stores_serial(self) -> None:
        groups = self.query.split_safe_parallel_groups(
            [
                {"keyword": "第3档口"},
                {"keyword": "川湘府"},
                {"keyword": "万象城", "directMeituanAccountId": "direct_wanxiangcheng"},
                {"keyword": "金融城", "directMeituanAccountId": "direct_jinrongcheng"},
                {"keyword": "银泰城", "directMeituanAccountId": "direct_yintaicheng"},
            ],
            workers=3,
        )

        self.assertEqual([item["keyword"] for item in groups[0]], ["第3档口", "川湘府"])
        self.assertTrue(all(item.get("directMeituanAccountId") for group in groups[1:] for item in group))
        self.assertEqual(len(groups), 3)

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
        self.assertIn("银泰城", text)
        self.assertIn("预警", text)
        self.assertIn("95%", text)
        self.assertIn("本巡检只读", text)

    def test_apply_budget_fields_uses_configured_budget_for_remaining(self) -> None:
        record = {"today_spend": 75}

        self.query.apply_budget_fields(record, 100)

        self.assertEqual(record["budget"], 100)
        self.assertEqual(record["remaining_budget"], 25)
        self.assertEqual(record["budget_percent"], 75)
        self.assertEqual(record["budget_source"], "configured")

    def test_should_retry_transient_browser_and_entry_failures(self) -> None:
        self.assertTrue(
            self.query.should_retry_query(
                {"ok": False, "error": "Page.evaluate: Target page, context or browser has been closed"}
            )
        )
        self.assertTrue(self.query.should_retry_query({"ok": False, "failure_type": "dianjin_entry_missing"}))
        self.assertFalse(self.query.should_retry_query({"ok": False, "failure_type": "auth_block"}))

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

        self.assertIn("第3档口", text)
        self.assertIn("未核实", text)
        self.assertIn("页面弹出遮罩层挡住门店选择器", text)
        self.assertNotIn("Call log", text)

    def test_main_returns_nonzero_for_partial_coverage(self) -> None:
        with mock.patch.object(
            self.query,
            "build_payload",
            return_value={"status": "partial", "message": "美团推广实时消耗巡检：总览：已读到 4/13 家"},
        ):
            with mock.patch.object(self.query, "write_latest"):
                self.assertEqual(self.query.main(["--quiet"]), 2)

    def test_main_returns_zero_only_for_full_coverage(self) -> None:
        with mock.patch.object(
            self.query,
            "build_payload",
            return_value={"status": "ok", "message": "美团推广实时消耗巡检：总览：已读到 13/13 家"},
        ):
            with mock.patch.object(self.query, "write_latest"):
                self.assertEqual(self.query.main(["--quiet"]), 0)


if __name__ == "__main__":
    unittest.main()
