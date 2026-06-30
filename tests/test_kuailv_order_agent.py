from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from kuailv_order_agent import latest_saw_empty_cart, select_order, summarize_dry_run_latest  # noqa: E402


class KuailvOrderAgentTest(unittest.TestCase):
    def test_select_order_finds_store_date_and_kuailv_items(self) -> None:
        payload = {
            "orders": [
                {
                    "order_id": "DO-OLD",
                    "store_name": "保利中心店",
                    "submitted_at": "2026-06-29T12:00:00+08:00",
                    "items": [{"name": "洋葱", "quantity": 10, "unit": "斤", "purchase_channel": "快驴"}],
                },
                {
                    "order_id": "DO-BAOLI",
                    "store_name": "保利中心店",
                    "submitted_at": "2026-06-30T14:21:51+08:00",
                    "items": [
                        {"name": "洋葱", "quantity": 30, "unit": "斤", "purchase_channel": "快驴"},
                        {"name": "大米", "quantity": 3, "unit": "袋", "purchase_channel": "大米群"},
                    ],
                },
            ]
        }

        order = select_order(payload, "2026-06-30", "保利中心店")

        self.assertEqual(order["order_id"], "DO-BAOLI")

    def test_select_order_rejects_non_kuailv_only_order(self) -> None:
        payload = {
            "orders": [
                {
                    "order_id": "DO-NON-KL",
                    "store_name": "保利中心店",
                    "submitted_at": "2026-06-30T14:21:51+08:00",
                    "items": [{"name": "大米", "quantity": 3, "unit": "袋", "purchase_channel": "大米群"}],
                }
            ]
        }

        with self.assertRaises(RuntimeError):
            select_order(payload, "2026-06-30", "保利中心店")

    def test_latest_summary_detects_empty_cart_text(self) -> None:
        latest = {"adb": {"after": {"detected_text": ["购物车为空，快来选购吧", "去选购"]}}}

        child = {"latest_summary": summarize_dry_run_latest(latest)}

        self.assertTrue(latest_saw_empty_cart(child))


if __name__ == "__main__":
    unittest.main()
