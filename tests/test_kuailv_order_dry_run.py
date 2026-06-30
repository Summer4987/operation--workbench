from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from kuailv_order_dry_run import (  # noqa: E402
    analyze_cart_review_xml,
    android_auto_add_gate,
    auto_add_pack_steps,
    build_plan,
    safe_tap_visual_proof,
)


class KuailvOrderDryRunTest(unittest.TestCase):
    def test_visual_proof_accepts_xml_target_card_spec_when_ocr_misses_spec(self) -> None:
        before = {"detected_text": ["黄皮洋葱"]}
        selected = {
            "source": "xml_target_card_control",
            "identity_keywords": ["黄皮洋葱"],
            "identity_hits": ["黄皮洋葱"],
            "pack_hits": ["20斤"],
            "pack_label": "20斤",
            "target_title_text": "黄皮洋葱",
            "target_spec_text": "20斤",
        }

        proof = safe_tap_visual_proof(before, selected)

        self.assertTrue(proof["allowed"])
        self.assertIn("20斤", proof["xml_spec_seen"])

    def test_visual_proof_still_blocks_checkout_text(self) -> None:
        before = {"detected_text": ["黄皮洋葱", "提交订单"]}
        selected = {
            "source": "xml_target_card_control",
            "identity_keywords": ["黄皮洋葱"],
            "identity_hits": ["黄皮洋葱"],
            "pack_hits": ["20斤"],
            "pack_label": "20斤",
            "target_title_text": "黄皮洋葱",
            "target_spec_text": "20斤",
        }

        proof = safe_tap_visual_proof(before, selected)

        self.assertFalse(proof["allowed"])
        self.assertIn("submit_or_payment_text_visible", proof["reasons"])

    def test_cart_review_expectation_matches_visible_planned_item(self) -> None:
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
        plan = build_plan(order)
        xml_text = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node text="购物车" bounds="[40,120][180,180]" />
  <node text="全选" bounds="[40,2140][140,2200]" />
  <node text="合计:" bounds="[480,2140][580,2200]" />
  <node text="去结算" bounds="[820,2140][1040,2240]" />
  <node text="黄皮洋葱" bounds="[410,820][620,880]" />
  <node text="20斤" bounds="[410,900][500,960]" />
  <node text="¥24.00" bounds="[410,980][550,1040]" />
  <node text="2" bounds="[820,1010][850,1060]" />
</hierarchy>"""

        details = analyze_cart_review_xml(xml_text, plan)

        expectation = details["expectation"]
        self.assertTrue(details["reached_cart"])
        self.assertEqual(expectation["status"], "ready")
        self.assertEqual(expectation["matched_line_count"], 1)
        self.assertEqual(expectation["missing_line_count"], 0)
        self.assertEqual(expectation["risk_flags"], [])

    def test_cart_review_expectation_flags_unexpected_item(self) -> None:
        order = {
            "order_id": "DO-TEST",
            "store_name": "银泰城店",
            "submitted_at": "2026-06-17T10:00:00+08:00",
            "items": [
                {
                    "sku": "TOFU-001",
                    "name": "豆腐",
                    "quantity": 2,
                    "unit": "盒",
                    "purchase_channel": "快驴",
                }
            ],
        }
        plan = build_plan(order)
        xml_text = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node text="购物车" bounds="[40,120][180,180]" />
  <node text="全选" bounds="[40,2140][140,2200]" />
  <node text="合计:" bounds="[480,2140][580,2200]" />
  <node text="去结算" bounds="[820,2140][1040,2240]" />
  <node text="嫩豆腐" bounds="[410,820][620,880]" />
  <node text="5斤" bounds="[410,900][500,960]" />
  <node text="¥12.00" bounds="[410,980][550,1040]" />
  <node text="2" bounds="[820,1010][850,1060]" />
</hierarchy>"""

        details = analyze_cart_review_xml(xml_text, plan)

        expectation = details["expectation"]
        self.assertEqual(expectation["status"], "needs_review")
        self.assertEqual(expectation["missing_line_count"], 1)
        self.assertIn("expected_item_missing", expectation["risk_flags"])
        self.assertIn("global_reject_keyword_seen", expectation["risk_flags"])
        self.assertIn("嫩豆腐", expectation["global_reject_hits"])

    def test_auto_add_pack_steps_expand_full_order_counts(self) -> None:
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
                },
                {
                    "sku": "POTATO-001",
                    "name": "土豆",
                    "quantity": 15,
                    "unit": "斤",
                    "purchase_channel": "快驴",
                },
            ],
        }

        steps = auto_add_pack_steps(build_plan(order))

        self.assertEqual(steps[0]["line_name"], "洋葱")
        self.assertEqual(steps[0]["pack_label"], "20斤")
        self.assertEqual(steps[0]["count"], 2)
        potato_steps = [step for step in steps if step["line_name"] == "土豆"]
        self.assertEqual([step["pack_label"] for step in potato_steps], ["10斤", "5斤"])
        self.assertEqual([step["search_query"] for step in potato_steps], ["土豆10斤", "土豆5斤"])

    def test_auto_add_gate_requires_confirm_and_private_config_flag(self) -> None:
        config = {
            "payment": {"auto_payment_allowed": False},
            "channels": [{"channel": "快驴", "enabled": True}],
            "safety": {
                "allow_auto_add_to_cart": True,
                "forbidden_actions": ["自动提交订单", "自动付款", "自动切换收货地址"],
            },
        }

        blocked = android_auto_add_gate(config, confirm=False)
        allowed = android_auto_add_gate(config, confirm=True)
        no_flag = android_auto_add_gate({**config, "safety": {**config["safety"], "allow_auto_add_to_cart": False}}, confirm=True)

        self.assertFalse(blocked["allowed"])
        self.assertIn("missing_confirm_auto_add_to_cart", blocked["reasons"])
        self.assertTrue(allowed["allowed"])
        self.assertFalse(no_flag["allowed"])
        self.assertIn("auto_add_to_cart_not_allowed_by_config", no_flag["reasons"])


if __name__ == "__main__":
    unittest.main()
