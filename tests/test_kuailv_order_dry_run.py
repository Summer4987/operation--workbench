from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from kuailv_order_dry_run import safe_tap_visual_proof  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
