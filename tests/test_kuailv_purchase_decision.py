from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from kuailv_purchase_decision import build_payload  # noqa: E402


class KuailvPurchaseDecisionTest(unittest.TestCase):
    def test_many_missing_pack_candidates_do_not_explode(self) -> None:
        order = {
            "order_id": "DO-TEST",
            "store_name": "银泰城店",
            "submitted_at": "2026-06-17T10:00:00+08:00",
            "items": [
                {
                    "sku": "ONION-001",
                    "name": "洋葱",
                    "quantity": 40,
                    "unit": "斤",
                    "purchase_channel": "快驴",
                }
            ],
        }
        candidates = {
            "洋葱": [
                {
                    "title": f"黄皮洋葱候选{i}",
                    "price": 1.1 + i / 100,
                    "monthly_sales": 10000 - i,
                    "sort_mode": "price_asc",
                    "search_page": 1,
                    "available": True,
                }
                for i in range(10)
            ]
        }

        payload = build_payload(order, candidates, 2, ["price_asc", "sales_desc"])

        decision = payload["decisions"][0]
        self.assertEqual(decision["status"], "needs_review")
        self.assertIn("excessive_click_count", decision["risk_flags"])


if __name__ == "__main__":
    unittest.main()
