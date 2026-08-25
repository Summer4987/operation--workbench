from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class MeituanBudgetSelectorTests(unittest.TestCase):
    def test_store_popup_does_not_depend_on_placement_class(self) -> None:
        source = (ROOT / "store-inspection" / "meituan_budget_cdp.py").read_text(encoding="utf-8")

        self.assertIn('page.locator(".roo-popup li")', source)
        self.assertNotIn('page.locator(".roo-popup.bottom li")', source)


if __name__ == "__main__":
    unittest.main()
