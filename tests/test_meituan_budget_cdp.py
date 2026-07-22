from __future__ import annotations

import importlib.util
import pathlib
import sys
import types
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "store-inspection" / "meituan_budget_cdp.py"


def load_module():
    sys.path.insert(0, str(SCRIPT_PATH.parent))
    playwright_module = types.ModuleType("playwright")
    sync_api_module = types.ModuleType("playwright.sync_api")
    sync_api_module.sync_playwright = object
    sys.modules.setdefault("playwright", playwright_module)
    sys.modules.setdefault("playwright.sync_api", sync_api_module)
    spec = importlib.util.spec_from_file_location("meituan_budget_cdp_for_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeFrame:
    def __init__(self, url: str) -> None:
        self.url = url


class FakePage:
    def __init__(self, url: str, frame_urls: list[str] | None = None) -> None:
        self.url = url
        self.frames = [FakeFrame(url) for url in (frame_urls or [])]
        self.closed = False

    def goto(self, url: str, **_kwargs) -> None:
        self.url = url

    def close(self) -> None:
        self.closed = True


class FakeContext:
    def __init__(self, pages: list[FakePage]) -> None:
        self.pages = pages

    def new_page(self) -> FakePage:
        page = FakePage("about:blank")
        self.pages.append(page)
        return page


class FakeBrowser:
    def __init__(self, context: FakeContext) -> None:
        self.contexts = [context]

    def new_context(self) -> FakeContext:
        return self.contexts[0]


class FakeChromium:
    def __init__(self, browser: FakeBrowser) -> None:
        self.browser = browser
        self.endpoints: list[str] = []

    def connect_over_cdp(self, endpoint: str) -> FakeBrowser:
        self.endpoints.append(endpoint)
        return self.browser


class FakePlaywright:
    def __init__(self, browser: FakeBrowser) -> None:
        self.chromium = FakeChromium(browser)


class FakeInput:
    def input_value(self, **_kwargs) -> str:
        return "60"


class FakeLocator:
    def __init__(
        self,
        items: list["FakeLocator"] | None = None,
        *,
        visible: bool = True,
        enabled: bool = True,
        fail_normal_click: bool = False,
    ) -> None:
        self.items = items or []
        self.visible = visible
        self.enabled = enabled
        self.clicked = False
        self.fail_normal_click = fail_normal_click
        self.click_kwargs: list[dict] = []

    def count(self) -> int:
        return len(self.items)

    def nth(self, index: int) -> "FakeLocator":
        return self.items[index]

    def is_visible(self) -> bool:
        return self.visible

    def is_enabled(self, **_kwargs) -> bool:
        return self.enabled

    def click(self, **_kwargs) -> None:
        self.click_kwargs.append(_kwargs)
        if self.fail_normal_click and not _kwargs.get("force"):
            raise RuntimeError("iframe intercepts pointer events")
        self.clicked = True

    def evaluate(self, *_args, **_kwargs) -> None:
        self.clicked = True


class FakeConfirmFrame:
    url = "https://waimaieapp.meituan.com/ad/v1/rpc"

    def __init__(self) -> None:
        self.confirm = FakeLocator()

    def get_by_role(self, *_args, **_kwargs) -> FakeLocator:
        return FakeLocator([])

    def get_by_text(self, *_args, **_kwargs) -> FakeLocator:
        return FakeLocator([self.confirm])


class FakeConfirmPage:
    def __init__(self) -> None:
        self.frame = FakeConfirmFrame()
        self.frames = [self.frame]
        self.reloaded = False
        self.goto_url = ""

    def reload(self, **_kwargs) -> None:
        self.reloaded = True

    def goto(self, url: str, **_kwargs) -> None:
        self.goto_url = url


class MeituanBudgetCdpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module()

    def test_resolve_default_base_url_falls_back_without_chrome_history(self) -> None:
        with mock.patch.object(self.module, "recent_meituan_promo_url", return_value=None):
            with mock.patch.dict("os.environ", {}, clear=True):
                self.assertEqual(
                    self.module.resolve_default_base_url(),
                    self.module.MEITUAN_PROMO_FALLBACK_URL,
                )

    def test_base_url_for_non_direct_task_prefers_current_cdp_page(self) -> None:
        current_url = "https://waimaieapp.meituan.com/ad/v1/rpc?token=abc&acctId=123"
        context = FakeContext([FakePage("https://e.waimai.meituan.com/", [current_url])])
        self.assertEqual(
            self.module.base_url_for_task("https://fallback.example", {}, {}, context),
            current_url,
        )

    def test_recent_promo_url_ignores_recharge_page(self) -> None:
        recharge = "https://waimaieapp.meituan.com/ad/v1/rpc?token=abc&acctId=123#/subapp/isomor_recharge/pages/index/index"
        budget = "https://waimaieapp.meituan.com/ad/v1/rpc?token=abc&acctId=123#/subapp/isomor_cpc/pages/index/index"
        context = FakeContext([FakePage(budget), FakePage(recharge)])

        self.assertEqual(self.module.recent_promo_url_from_context(context), budget)

    def test_recent_promo_url_accepts_new_jump_authorize_budget_route(self) -> None:
        budget = "https://waimaieapp.meituan.com/ad/v1/rpc?jumpAuthorize=true#/subapp/isomor_cpc/pages/index/index"

        self.assertTrue(self.module.is_budget_promo_url(budget))

    def test_authenticated_budget_url_skips_newer_outer_route(self) -> None:
        authenticated = "https://waimaieapp.meituan.com/ad/v1/rpc?token=abc&acctId=123#/subapp/isomor_cpc/pages/index/index"
        outer = "https://e.waimai.meituan.com/#https://waimaieapp.meituan.com/ad/v1/rpc?jumpAuthorize=true#/subapp/isomor_cpc/pages/index/index"
        context = FakeContext([FakePage(authenticated), FakePage(outer)])

        self.assertEqual(self.module.recent_authenticated_budget_url_from_context(context), authenticated)

    def test_promo_landing_accepts_new_outer_index_route(self) -> None:
        landing = "https://e.waimai.meituan.com/#https://waimaieapp.meituan.com/ad/v1/rpc?jumpAuthorize=true#/index"

        self.assertEqual(self.module.recent_promo_landing_url_from_page(FakePage(landing)), landing)

    def test_direct_task_falls_back_to_configured_promo_url(self) -> None:
        account = {
            "id": "direct_test",
            "pages": {"promo_balance": "https://e.waimai.meituan.com/#https://waimaieapp.meituan.com/ad/v1/rpc"},
        }
        context = FakeContext([])
        with mock.patch.object(self.module, "load_direct_promo_url_cache", return_value={}):
            with mock.patch.object(self.module, "open_direct_promo_url", side_effect=RuntimeError("入口缺失")):
                self.assertEqual(
                    self.module.base_url_for_task(
                        "https://fallback.example",
                        {"directMeituanAccountId": "direct_test"},
                        {"direct_test": account},
                        context,
                    ),
                    account["pages"]["promo_balance"],
                )

    def test_direct_task_without_wm_poi_id_can_use_account_entry(self) -> None:
        context = FakeContext([])
        task = {
            "store": "万象城店",
            "keyword": "万象城",
            "sourceStore": "万象城店",
            "targetBudget": 60,
            "directMeituanAccountId": "direct_wanxiangcheng",
        }
        with mock.patch.object(self.module, "enter_dianjin_with_recovery"):
            with mock.patch.object(self.module, "wait_setting_ready", return_value={"rangeMax": 1}):
                with mock.patch.object(self.module, "read_budget", return_value=60):
                    with mock.patch.object(self.module, "wait_budget", return_value=60):
                        with mock.patch.object(self.module, "open_budget_modal"):
                            with mock.patch.object(self.module, "budget_input_locator", return_value=FakeInput()):
                                with mock.patch.object(self.module, "close_budget_modal"):
                                    with mock.patch.object(self.module, "confirm_button_locator", return_value=FakeLocator()):
                                        result = self.module.execute_task(
                                            context,
                                            "https://e.waimai.meituan.com/#https://waimaieapp.meituan.com/ad/v1/rpc",
                                            task,
                                            commit=False,
                                            preflight=True,
                                        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["wmPoiId"], "")

    def test_headquarters_context_uses_configured_debug_port(self) -> None:
        context = FakeContext([FakePage("https://e.waimai.meituan.com/")])
        playwright = FakePlaywright(FakeBrowser(context))
        contexts = {}

        with mock.patch.object(self.module, "cdp_available", return_value=True):
            with mock.patch.dict("os.environ", {"MEITUAN_HEADQUARTERS_DEBUG_PORT": "19227"}):
                result = self.module.context_for_task(playwright, contexts, [], {}, {})

        self.assertIs(result, context)
        self.assertEqual(playwright.chromium.endpoints, ["http://127.0.0.1:19227"])
        self.assertIn("http://127.0.0.1:19227", contexts)

    def test_confirm_button_locator_falls_back_to_exact_text(self) -> None:
        page = FakeConfirmPage()

        locator = self.module.confirm_button_locator(page)

        self.assertIs(locator, page.frame.confirm)
        locator.click()
        self.assertTrue(page.frame.confirm.clicked)

    def test_click_confirm_button_forces_click_when_overlay_intercepts(self) -> None:
        page = FakeConfirmPage()
        locator = FakeLocator(fail_normal_click=True)

        message = self.module.click_confirm_button(page, locator)

        self.assertTrue(locator.clicked)
        self.assertIn("强制点击确定", message)
        self.assertEqual(locator.click_kwargs[-1].get("force"), True)

    def test_current_day_spend_ignores_stale_today_card(self) -> None:
        text = "今日 07-21 17:04 更新，指标解读\n推广花费\n80.01元\n昨日130元"

        self.assertIsNone(self.module.parse_current_day_spend(text, "07-22"))

    def test_current_day_spend_reads_matching_today_card(self) -> None:
        text = "今日 07-22 10:35 更新，指标解读\n推广花费\n1,280.50元\n昨日130元"

        self.assertEqual(self.module.parse_current_day_spend(text, "07-22"), 1280.5)

    def test_read_today_spend_reads_realtime_promo_spend(self) -> None:
        page = FakeConfirmPage()

        with mock.patch.object(
            self.module,
            "page_text",
            return_value=(
                f"实时数据\n今日 {self.module.time.strftime('%m-%d')} 10:35 更新\n"
                "推广花费\n110.91元\n昨日120元\n历史数据\n推广花费\n793.43元"
            ),
        ):
            self.assertEqual(self.module.read_today_spend(page), 110.91)

    def test_execute_task_skips_lowering_budget_when_spend_exceeds_target(self) -> None:
        context = FakeContext([])
        task = {
            "store": "熊小小牛排饭POKEBEAR（保利中心店）",
            "keyword": "保利中心",
            "wmPoiId": "32022526",
            "targetBudget": 100,
        }

        headquarters_page = context.new_page()
        with mock.patch.object(
            self.module,
            "open_headquarters_budget_page",
            return_value=(headquarters_page, True, "https://waimaieapp.meituan.com/ad/v1/rpc?token=abc&acctId=123"),
        ):
            with mock.patch.object(self.module, "enter_dianjin_with_recovery"):
                with mock.patch.object(self.module, "wait_setting_ready", return_value={"rangeMax": 1}):
                    with mock.patch.object(self.module, "wait_budget", return_value=120.0):
                        with mock.patch.object(self.module, "read_budget", return_value=120.0):
                            with mock.patch.object(self.module, "read_today_spend", return_value=110.91):
                                with mock.patch.object(self.module, "open_budget_modal") as open_modal:
                                    result = self.module.execute_task(
                                        context,
                                        "https://waimaieapp.meituan.com/ad/v1/rpc?token=abc&acctId=123",
                                        task,
                                        commit=True,
                                    )

        self.assertTrue(result["ok"])
        self.assertTrue(result["skipped"])
        self.assertEqual(result["failure_type"], "spent_exceeds_target")
        self.assertEqual(result["afterBudget"], 120.0)
        self.assertIn("今日已消耗110.91元", result["message"])
        open_modal.assert_not_called()

    def test_authenticated_budget_page_skips_headquarters_menu(self) -> None:
        budget_url = "https://waimaieapp.meituan.com/ad/v1/rpc?token=abc&acctId=123&wmPoiId=32022526#/subapp/isomor_cpc/pages/index/index"
        context = FakeContext([FakePage(budget_url)])
        task = {
            "store": "保利中心店",
            "keyword": "保利中心",
            "wmPoiId": "32022526",
            "targetBudget": 100,
        }

        with mock.patch.object(self.module, "open_headquarters_budget_page") as open_menu:
            with mock.patch.object(self.module, "enter_dianjin_with_recovery"):
                with mock.patch.object(self.module, "wait_setting_ready", return_value={"rangeMax": 1}):
                    with mock.patch.object(self.module, "wait_budget", return_value=100.0):
                        with mock.patch.object(self.module, "read_budget", return_value=100.0):
                            result = self.module.execute_task(context, budget_url, task, commit=True)

        self.assertTrue(result["ok"])
        open_menu.assert_not_called()

    def test_classify_platform_budget_locked_zero_range(self) -> None:
        self.assertEqual(
            self.module.classify_failure("平台预算锁定：预算已耗尽，预算弹窗限制请输入0-0元"),
            "platform_budget_locked",
        )

    def test_classify_spent_exceeds_target(self) -> None:
        self.assertEqual(
            self.module.classify_failure("今日已消耗110.91元，超过目标预算100元；平台不允许下调到目标值"),
            "spent_exceeds_target",
        )

    def test_confirm_budget_reports_platform_locked_zero_range(self) -> None:
        page = FakeConfirmPage()
        disabled = FakeLocator(enabled=False)

        with mock.patch.object(self.module, "confirm_button_locator", return_value=disabled):
            with mock.patch.object(self.module, "budget_input_locator", return_value=FakeInput()):
                with mock.patch.object(self.module, "trigger_form_dirty"):
                    with mock.patch.object(self.module, "read_budget", return_value=150.0):
                        with mock.patch.object(
                            self.module,
                            "page_text",
                            return_value="每日预算 输入金额过高，请输入0-0元 取消 确定",
                        ):
                            with mock.patch.object(self.module, "close_budget_modal"):
                                with self.assertRaisesRegex(RuntimeError, "平台预算锁定"):
                                    self.module.confirm_budget_with_recovery(page, 70.0)

    def test_confirm_budget_verifies_committed_budget_after_reload(self) -> None:
        page = FakeConfirmPage()

        with mock.patch.object(self.module, "confirm_button_locator", return_value=page.frame.confirm):
            with mock.patch.object(self.module, "confirm_button_enabled", return_value=True):
                with mock.patch.object(self.module, "close_budget_modal"):
                    with mock.patch.object(self.module, "enter_dianjin_with_recovery") as enter:
                        with mock.patch.object(self.module, "wait_setting_ready"):
                            with mock.patch.object(self.module, "wait_budget", return_value=120.0):
                                final_budget, message = self.module.confirm_budget_with_recovery(
                                    page,
                                    200.0,
                                    "https://waimaieapp.meituan.com/ad/v1/rpc?wmPoiId=5650880",
                                )

        self.assertTrue(page.reloaded)
        enter.assert_called_once()
        self.assertEqual(final_budget, 120.0)
        self.assertIn("刷新后读回确认", message)


if __name__ == "__main__":
    unittest.main()
