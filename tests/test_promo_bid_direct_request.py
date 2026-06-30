from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import promo_bid_direct_request as direct_bid  # noqa: E402


class PromoBidDirectRequestTests(unittest.TestCase):
    def test_complete_instruction_enters_executor_missing_state(self) -> None:
        payload = direct_bid.build_payload("美团 银泰城店 点金出价调到 1.8 元", execute=True)

        self.assertEqual(payload["status"], "executor_missing")
        self.assertEqual(payload["request"]["platform"], "meituan")
        self.assertIn("银泰城", payload["request"]["store"])
        self.assertEqual(payload["request"]["target_bid"], 1.8)
        self.assertIn("缺少可用的真实平台出价执行器", payload["message"])

    def test_missing_required_fields_asks_for_clarification(self) -> None:
        payload = direct_bid.build_payload("把推广出价调到 1.8", execute=True)

        self.assertEqual(payload["status"], "needs_clarification")
        self.assertIn("平台", "、".join(payload["request"]["missing_fields"]))
        self.assertIn("门店", "、".join(payload["request"]["missing_fields"]))


if __name__ == "__main__":
    unittest.main()
