from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import promo_bid_direct_request as direct_bid  # noqa: E402


class PromoBidDirectRequestTests(unittest.TestCase):
    def test_complete_instruction_calls_executor(self) -> None:
        original_executor = direct_bid.run_executor
        try:
            direct_bid.run_executor = lambda request: {
                "status": "success",
                "message": "美团 银泰城店 出价已保存。",
                "execution": {"attempted": True, "executed": True, "reason": ""},
            }
            payload = direct_bid.build_payload("美团 银泰城店 点金出价调到 1.8 元", execute=True)
        finally:
            direct_bid.run_executor = original_executor

        self.assertEqual(payload["status"], "executed")
        self.assertEqual(payload["request"]["platform"], "meituan")
        self.assertIn("银泰城", payload["request"]["store"])
        self.assertEqual(payload["request"]["target_bid"], 1.8)
        self.assertIn("已把", payload["message"])
        self.assertNotIn("\n", payload["message"])

    def test_executor_failure_is_reported_naturally(self) -> None:
        original_executor = direct_bid.run_executor
        try:
            direct_bid.run_executor = lambda request: {
                "status": "failed",
                "message": "美团 银泰城店 出价调整失败：没有打开出价设置弹窗。",
                "execution": {"attempted": True, "executed": False, "reason": "page_structure_changed"},
            }
            payload = direct_bid.build_payload("美团 银泰城店 点金出价调到 1.8 元", execute=True)
        finally:
            direct_bid.run_executor = original_executor

        self.assertEqual(payload["status"], "failed")
        self.assertIn("没有打开出价设置弹窗", payload["message"])
        self.assertEqual(payload["execution"]["reason"], "page_structure_changed")
        self.assertNotIn("真实改价执行器还没接上", payload["message"])

    def test_missing_required_fields_asks_for_clarification(self) -> None:
        payload = direct_bid.build_payload("把推广出价调到 1.8", execute=True)

        self.assertEqual(payload["status"], "needs_clarification")
        self.assertIn("平台", "、".join(payload["request"]["missing_fields"]))
        self.assertIn("门店", "、".join(payload["request"]["missing_fields"]))
        self.assertNotIn("\n", payload["message"])


if __name__ == "__main__":
    unittest.main()
