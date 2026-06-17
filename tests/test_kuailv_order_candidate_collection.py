from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from kuailv_adb_order_candidate_collection import (  # noqa: E402
    build_inline_spec_capture,
    build_plan_payload,
    capture_needs_spec_expansion,
    collection_status_from_decision,
    expand_specs_for_capture,
    line_decision_status,
)
from kuailv_order_dry_run import build_line_plan  # noqa: E402


def sample_order() -> dict:
    return {
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
            {
                "sku": "TOMATO-001",
                "name": "圣女果",
                "quantity": 5,
                "unit": "斤",
                "purchase_channel": "快驴",
            },
        ],
    }


class KuailvOrderCandidateCollectionTest(unittest.TestCase):
    def test_onion_defaults_to_yellow_onion(self) -> None:
        line = build_line_plan(sample_order()["items"][0])

        self.assertEqual(line["preferred_keyword"], "黄皮洋葱")
        self.assertIn("黄皮洋葱", line["required_keywords"])
        self.assertIn("白皮洋葱", line["excluded_keywords"])
        self.assertIn("红皮洋葱", line["excluded_keywords"])

    def test_plan_builds_sort_page_jobs_for_each_line(self) -> None:
        payload = build_plan_payload(sample_order(), ["price_asc", "sales_desc"], 2)

        self.assertEqual(payload["status"], "needs_collection")
        self.assertEqual(payload["summary"]["line_count"], 3)
        self.assertEqual(payload["summary"]["job_count"], 18)
        onion_jobs = [job for job in payload["collection_jobs"] if job["line_name"] == "洋葱"]
        self.assertEqual({job["query"] for job in onion_jobs}, {"黄皮洋葱", "洋葱"})
        self.assertTrue(all(job["pages"] == [1, 2] for job in payload["collection_jobs"]))

    def test_cherry_tomato_uses_precise_aliases_before_generic_search(self) -> None:
        line = build_line_plan(sample_order()["items"][2])

        self.assertEqual(line["preferred_keyword"], "红圣女果")
        self.assertIn("圣女果", line["required_keywords"])
        self.assertIn("小番茄", line["required_keywords"])
        self.assertIn("红西红柿", line["excluded_keywords"])

    def test_white_beech_mushroom_rejects_neighbor_mushrooms(self) -> None:
        line = build_line_plan({"sku": "MUSHROOM-001", "name": "白玉菇", "quantity": 15, "unit": "斤", "purchase_channel": "快驴"})

        self.assertIn("白玉菇", line["required_keywords"])
        self.assertIn("海鲜菇", line["excluded_keywords"])
        self.assertIn("蟹味菇", line["excluded_keywords"])

    def test_potato_prefers_pack_size_searches(self) -> None:
        line = build_line_plan(sample_order()["items"][1])

        self.assertEqual(line["search_terms"][:2], ["土豆5斤", "土豆10斤"])
        self.assertIn("土豆", line["search_terms"])
        self.assertIn("食堂菜", line["excluded_keywords"])
        self.assertEqual(line["overage"], 0)
        self.assertEqual(line["pack_strategy"], [{"pack_size": 10.0, "count": 1, "label": "10斤 x 1"}, {"pack_size": 5.0, "count": 1, "label": "5斤 x 1"}])

    def test_carrot_prefers_pack_size_searches(self) -> None:
        line = build_line_plan({"sku": "CARROT-001", "name": "胡萝卜", "quantity": 10, "unit": "斤", "purchase_channel": "快驴"})

        self.assertEqual(line["search_terms"][:2], ["胡萝卜5斤", "胡萝卜10斤"])
        self.assertIn("食堂菜", line["excluded_keywords"])

    def test_batch_cli_expands_multiple_spec_controls_by_default(self) -> None:
        script_text = (ROOT / "scripts" / "kuailv_adb_order_candidate_collection.py").read_text(encoding="utf-8")

        self.assertIn('default=3, help="每个搜索页最多展开几个规格控件"', script_text)

    def test_line_decision_status_reads_current_line(self) -> None:
        payload = {
            "decision": {
                "decisions": [
                    {"name": "洋葱", "status": "ready"},
                    {"name": "土豆", "status": "needs_review"},
                ]
            }
        }

        self.assertEqual(line_decision_status(payload, "洋葱"), "ready")
        self.assertEqual(line_decision_status(payload, "土豆"), "needs_review")
        self.assertEqual(line_decision_status(payload, "圣女果"), "")

    def test_collection_status_follows_ready_decision_despite_blocked_captures(self) -> None:
        grouped = {"土豆": [{"title": "刀削土豆食堂菜", "spec": "20斤"}]}

        self.assertEqual(collection_status_from_decision(grouped, {"status": "ready"}), "ready")
        self.assertEqual(collection_status_from_decision(grouped, {"status": "needs_review"}), "needs_review")
        self.assertEqual(collection_status_from_decision({}, {"status": "needs_candidates"}), "blocked")

    def test_missing_jin_pack_candidate_requests_spec_expansion(self) -> None:
        line = build_line_plan(sample_order()["items"][0])
        capture = {
            "items": [
                {
                    "source": "adb_xml_product_card",
                    "title": "黄皮洋葱",
                    "price": 1.15,
                    "spec": "",
                }
            ]
        }

        self.assertTrue(capture_needs_spec_expansion(capture, line))

        capture["items"].append(
            {
                "source": "adb_xml_product_card_offer",
                "title": "黄皮洋葱",
                "price": 1.15,
                "unit_price": 1.15,
                "spec": "10斤",
            }
        )
        self.assertFalse(capture_needs_spec_expansion(capture, line))

    def test_inline_spec_capture_keeps_only_spec_offer_rows(self) -> None:
        xml_text = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node text="" resource-id="search-page-container" bounds="[0,0][1080,2358]">
    <node text="黄皮洋葱" bounds="[120,120][300,210]" />
    <node text="综合排序" bounds="[40,620][210,680]" />
    <node text="销量" bounds="[300,620][390,680]" />
    <node text="价格" bounds="[480,620][570,680]" />
    <node text="黄皮洋葱" resource-id="complex-card-goods-1" bounds="[20,760][1060,1500]" />
    <node text="黄皮洋葱" bounds="[440,820][620,880]" />
    <node text="月售8292" bounds="[440,900][620,950]" />
    <node text="10斤" bounds="[440,1160][525,1220]" />
    <node text="¥" bounds="[590,1160][630,1220]" />
    <node text="1.15" bounds="[640,1155][730,1225]" />
    <node text="/斤" bounds="[735,1160][790,1220]" />
  </node>
</hierarchy>"""

        payload = build_inline_spec_capture(xml_text, "黄皮洋葱", "price_asc", 1, sample_order(), "洋葱", {})

        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["summary"]["candidate_count"], 1)
        self.assertEqual(payload["items"][0]["source"], "adb_xml_product_card_offer")
        self.assertEqual(payload["items"][0]["spec"], "10斤")
        self.assertEqual(payload["items"][0]["unit_price"], 1.15)

    def test_inline_spec_expansion_does_not_press_back(self) -> None:
        line = build_line_plan(sample_order()["items"][0])
        capture = {"snapshot": {"xml_text": "<hierarchy />"}}
        expanded_xml = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node text="" resource-id="search-page-container" bounds="[0,0][1080,2358]">
    <node text="黄皮洋葱" bounds="[120,120][300,210]" />
    <node text="综合排序" bounds="[40,620][210,680]" />
    <node text="销量" bounds="[300,620][390,680]" />
    <node text="价格" bounds="[480,620][570,680]" />
    <node text="黄皮洋葱" resource-id="complex-card-goods-1" bounds="[20,760][1060,1500]" />
    <node text="黄皮洋葱" bounds="[440,820][620,880]" />
    <node text="月售8292" bounds="[440,900][620,950]" />
    <node text="10斤" bounds="[440,1160][525,1220]" />
    <node text="¥" bounds="[590,1160][630,1220]" />
    <node text="1.15" bounds="[640,1155][730,1225]" />
    <node text="/斤" bounds="[735,1160][790,1220]" />
  </node>
</hierarchy>"""
        snapshot = {"xml_text": expanded_xml, "session_dir": "", "screen_path": ""}

        with patch("kuailv_adb_order_candidate_collection.tap_spec_control", return_value={"status": "tapped", "target": {"title": "黄皮洋葱"}}), patch(
            "kuailv_adb_order_candidate_collection.capture_snapshot", return_value=snapshot
        ), patch("kuailv_adb_order_candidate_collection.close_current_overlay") as close_mock:
            payload = expand_specs_for_capture("SERIAL", capture, "黄皮洋葱", "price_asc", 1, sample_order(), line, 25, 0, 0)

        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["spec_modal_close"]["status"], "skipped")
        close_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
