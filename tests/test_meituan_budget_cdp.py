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


class FakeContext:
    def __init__(self, pages: list[FakePage]) -> None:
        self.pages = pages


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


if __name__ == "__main__":
    unittest.main()
