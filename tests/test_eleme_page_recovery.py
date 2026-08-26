from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ElemePageRecoveryTests(unittest.TestCase):
    def test_balance_tabs_use_real_browser_click(self) -> None:
        source = (ROOT / "store-inspection" / "cdp_eleme_balance.py").read_text(encoding="utf-8")

        self.assertIn("locator.first.click(timeout=5_000)", source)

    def test_review_export_retries_the_content_tab(self) -> None:
        source = (ROOT / "business-report-dashboard" / "chrome_cdp_reports.py").read_text(encoding="utf-8")

        self.assertIn("export_deadline = time.time() + 45", source)
        self.assertIn('frame_or_page_with_exact_text(page, "评价内容", timeout_seconds=3)', source)


if __name__ == "__main__":
    unittest.main()
