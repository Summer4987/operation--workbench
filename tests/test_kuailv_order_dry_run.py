from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from kuailv_order_dry_run import (  # noqa: E402
    analyze_cart_review_xml,
    android_auto_add_gate,
    auto_add_pack_steps,
    build_plan,
    delivery_store_match,
    detect_xml_add_controls,
    empty_cart_shop_candidate,
    filter_visible_xml_add_candidates,
    find_search_entry_candidates,
    load_order_json,
    parse_ui_nodes,
    safe_tap_visual_proof,
    score_candidate_for_line,
    search_suggestion_candidate,
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
  <node text="[其辉]胆水老豆腐" bounds="[410,820][720,880]" />
  <node text="400g" bounds="[410,900][500,960]" />
  <node text="¥3.20" bounds="[410,980][550,1040]" />
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
        self.assertEqual(steps[0]["pack_label"], "")
        self.assertEqual(steps[0]["display_pack_label"], "40斤目标")
        self.assertEqual(steps[0]["selection_mode"], "identity_only")
        self.assertEqual(steps[0]["count"], 1)
        potato_steps = [step for step in steps if step["line_name"] == "土豆"]
        self.assertEqual([step["pack_label"] for step in potato_steps], [""])
        self.assertEqual([step["display_pack_label"] for step in potato_steps], ["15斤目标"])
        self.assertEqual([step["search_query"] for step in potato_steps], ["土豆"])
        self.assertEqual([step["count"] for step in potato_steps], [1])

    def test_identity_only_line_does_not_require_pack_quantity_on_card(self) -> None:
        order = {
            "order_id": "DO-TEST",
            "store_name": "保利中心店",
            "submitted_at": "2026-06-30T10:00:00+08:00",
            "items": [
                {
                    "sku": "ONION-001",
                    "name": "洋葱",
                    "quantity": 30,
                    "unit": "斤",
                    "purchase_channel": "快驴",
                }
            ],
        }
        line = build_plan(order)["lines"][0]
        candidate = {
            "source": "xml_target_card_control",
            "control_text": "orange_add_icon",
            "target_line_name": "洋葱",
            "target_title_text": "黄皮洋葱",
            "target_spec_text": "",
            "nearby_texts": [{"text": "黄皮洋葱", "bounds": [410, 820, 620, 880]}],
            "context_texts": [{"text": "黄皮洋葱", "bounds": [410, 820, 620, 880]}],
        }

        score = score_candidate_for_line(candidate, line, "")

        self.assertTrue(score["allowed"])
        self.assertNotIn("pack_label_not_in_card_context", score["reasons"])

    def test_identity_only_text_spec_candidate_tolerates_neighbor_product_context(self) -> None:
        order = {
            "order_id": "DO-TEST",
            "store_name": "保利中心店",
            "submitted_at": "2026-06-30T10:00:00+08:00",
            "items": [
                {
                    "sku": "ONION-001",
                    "name": "洋葱",
                    "quantity": 30,
                    "unit": "斤",
                    "purchase_channel": "快驴",
                }
            ],
        }
        line = build_plan(order)["lines"][0]
        candidate = {
            "source": "xml_add_control",
            "control_text": "选规格",
            "nearby_texts": [
                {"text": "黄皮洋葱", "bounds": [866, 1260, 1018, 1313]},
                {"text": "粉壳黄心鲜鸡蛋 中码 箱装", "bounds": [174, 1409, 492, 1459]},
            ],
            "context_texts": [
                {"text": "黄皮洋葱", "bounds": [866, 1260, 1018, 1313]},
                {"text": "粉壳黄心鲜鸡蛋 中码 箱装", "bounds": [174, 1409, 492, 1459]},
            ],
        }

        score = score_candidate_for_line(candidate, line, "")

        self.assertTrue(score["allowed"])
        self.assertNotIn("other_product_context_seen", score["reasons"])

    def test_search_suggestion_prefers_exact_non_risk_query(self) -> None:
        snapshot = {
            "ui_analysis": {
                "visible_text_nodes": [
                    {"text": "黄皮洋葱", "bounds": [45, 264, 807, 326]},
                    {"text": "黄皮洋葱食堂", "bounds": [45, 641, 1035, 703]},
                ]
            }
        }

        candidate = search_suggestion_candidate(snapshot, "黄皮洋葱", ["黄皮洋葱"])

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["text"], "黄皮洋葱")
        self.assertEqual(candidate["center"], [426.0, 295.0])

    def test_empty_cart_shop_candidate_accepts_go_shop_only_on_empty_cart(self) -> None:
        xml_text = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node text="购物车为空，快来选购吧" bounds="[289,781][790,849]" />
  <node text="去选购" bounds="[433,888][646,990]" />
</hierarchy>"""

        candidate = empty_cart_shop_candidate(xml_text)

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["center"], [539.5, 939.0])

    def test_empty_cart_shop_candidate_blocks_checkout_risk_text(self) -> None:
        xml_text = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node text="购物车为空，快来选购吧" bounds="[289,781][790,849]" />
  <node text="去选购" bounds="[433,888][646,990]" />
  <node text="去结算" bounds="[820,2140][1040,2240]" />
</hierarchy>"""

        self.assertIsNone(empty_cart_shop_candidate(xml_text))

    def test_search_entry_candidate_prefers_text_input_over_header_container(self) -> None:
        xml_text = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node text="" class="android.view.View" bounds="[0,0][1080,334]" />
  <node text="搜冻品，来冻品大单" class="android.widget.TextView" bounds="[230,225][863,303]" />
  <node text="搜索" class="android.widget.TextView" bounds="[891,225][1046,303]" />
</hierarchy>"""

        candidates = find_search_entry_candidates(parse_ui_nodes(xml_text), Path(""))

        self.assertGreaterEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["text"], "搜冻品，来冻品大单")
        self.assertEqual(candidates[0]["center"], [546.5, 264.0])

    def test_search_entry_candidate_accepts_recommended_word_with_submit_button(self) -> None:
        xml_text = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node text="" resource-id="index-page-header" class="android.view.View" bounds="[0,0][1080,334]" />
  <node text="可乐" class="android.widget.TextView" bounds="[230,84][312,143]" />
  <node text="洋葱圈 95%同行买过" class="android.widget.TextView" bounds="[230,160][601,219]" />
  <node text="搜索" class="android.widget.TextView" bounds="[891,225][1046,303]" />
</hierarchy>"""

        candidates = find_search_entry_candidates(parse_ui_nodes(xml_text), Path(""))

        self.assertGreaterEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["text"], "可乐")
        self.assertIn("top_search_bar_text_with_submit", candidates[0]["reasons"])
        self.assertNotEqual(candidates[0]["resource_id"], "index-page-header")

    def test_search_entry_candidate_rejects_navigation_label_with_submit_button(self) -> None:
        xml_text = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node text="冻品" class="android.widget.TextView" bounds="[458,112][554,180]" />
  <node text="搜索" class="android.widget.TextView" bounds="[891,225][1046,303]" />
</hierarchy>"""

        candidates = find_search_entry_candidates(parse_ui_nodes(xml_text), Path(""))

        self.assertEqual(candidates, [])

    def test_visible_xml_add_candidates_keep_text_spec_control_without_orange_image(self) -> None:
        xml_text = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node text="黄皮洋葱" class="android.widget.TextView" bounds="[475,821][649,883]" />
  <node text="选规格" class="android.widget.TextView" bounds="[900,1023][1054,1094]" />
</hierarchy>"""

        candidates = detect_xml_add_controls(parse_ui_nodes(xml_text))
        visible = filter_visible_xml_add_candidates(candidates, Path(""))

        self.assertEqual(len(visible), 1)
        self.assertEqual(visible[0]["control_text"], "选规格")

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

    def test_delivery_store_match_accepts_address_fragment_when_store_name_hidden(self) -> None:
        order = {
            "store_name": "保利中心店",
            "store_address": "四川省成都市武侯区玉林街道保利中心东区C座一层熊小小牛排饭",
        }
        delivery_text = "配送至玉林街道保利中心-东区-C座(锦绣路1号附24号1层)"

        match = delivery_store_match(build_plan({**order, "items": []}), delivery_text)

        self.assertTrue(match["matched"])
        self.assertFalse(match["strict_store_match"])
        self.assertIn("保利中心", match["matched_terms"])

    def test_load_order_json_accepts_direct_order_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "order.json"
            path.write_text(
                """{
  "order_id": "DO-LOCAL",
  "store_name": "银泰城店",
  "submitted_at": "2026-06-30T10:00:00+08:00",
  "items": [
    {"sku": "ONION-001", "name": "洋葱", "quantity": 40, "unit": "斤", "purchase_channel": "快驴"}
  ]
}
""",
                encoding="utf-8",
            )

            _payload, order = load_order_json(str(path))

        self.assertEqual(order["order_id"], "DO-LOCAL")
        self.assertEqual(auto_add_pack_steps(build_plan(order))[0]["pack_label"], "")


if __name__ == "__main__":
    unittest.main()
