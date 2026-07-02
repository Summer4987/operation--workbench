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

    def goto(self, url: str, **_kwargs) -> None:
        self.url = url


class FakeContext:
    def __init__(self, pages: list[FakePage]) -> None:
        self.pages = pages

    def new_page(self) -> FakePage:
        page = FakePage("about:blank")
        self.pages.append(page)
        return page


class FakeInput:
    def input_value(self, **_kwargs) -> str:
        return "60"


class FakeLocator:
    def __init__(self, items: list["FakeLocator"] | None = None, *, visible: bool = True, enabled: bool = True) -> None:
        self.items = items or []
        self.visible = visible
        self.enabled = enabled
        self.clicked = False

    def count(self) -> int:
        return len(self.items)

    def nth(self, index: int) -> "FakeLocator":
        return self.items[index]

    def is_visible(self) -> bool:
        return self.visible

    def is_enabled(self, **_kwargs) -> bool:
        return self.enabled

    def click(self, **_kwargs) -> None:
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

    def test_confirm_button_locator_falls_back_to_exact_text(self) -> None:
        page = FakeConfirmPage()

        locator = self.module.confirm_button_locator(page)

        self.assertIs(locator, page.frame.confirm)
        locator.click()
        self.assertTrue(page.frame.confirm.clicked)


if __name__ == "__main__":
    unittest.main()
