from __future__ import annotations

import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class BinjiangPromoBudgetTests(unittest.TestCase):
    def test_binjiang_is_in_eleme_rules_and_budget_overrides(self):
        rules_text = (ROOT / "dianjin-prototype" / "rules.js").read_text(encoding="utf-8")
        rules = json.loads(re.search(r"window\.DIANJIN_RULES\s*=\s*(\{.*\});", rules_text, re.S).group(1))
        store = next(item for item in rules["stores"] if item["name"] == "滨江店")

        self.assertEqual(store["shopId"], 545055537)
        self.assertEqual((store["lunchBudget"], store["dinnerBudget"]), (100, 150))
        self.assertEqual(store["elemeFullName"], "熊小小牛排饭POKEBEAR(滨江店)")

        overrides = json.loads((ROOT / "config" / "promo_budget_overrides.json").read_text(encoding="utf-8"))
        self.assertEqual(overrides["stores"]["滨江店"]["饿了么"]["lunchBudget"], 100)
        self.assertEqual(overrides["stores"]["滨江店"]["美团"]["dinnerBudget"], 150)

    def test_binjiang_is_in_meituan_budget_balance_and_spend_mappings(self):
        budget = (ROOT / "store-inspection" / "meituan_budget_cdp.py").read_text(encoding="utf-8")
        balance = (ROOT / "store-inspection" / "one_click_meituan_balance.py").read_text(encoding="utf-8")
        spend = (ROOT / "scripts" / "meituan_promo_spend_query.py").read_text(encoding="utf-8")
        preview = (ROOT / "scripts" / "build_promo_budget_preview.mjs").read_text(encoding="utf-8")

        self.assertIn('"滨江": "34062471"', budget)
        self.assertIn('"滨江": "34062471"', balance)
        self.assertIn('"滨江": ["滨江"]', spend)
        self.assertIn('"滨江店": "熊小小牛排饭POKEBEAR(滨江店)"', preview)
        self.assertIn('"滨江店": "滨江"', preview)


if __name__ == "__main__":
    unittest.main()
