from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from kuailv_adb_order_candidate_collection import (  # noqa: E402
    build_inline_spec_capture,
    build_plan_payload,
    capture_needs_spec_expansion,
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
        self.assertEqual(payload["summary"]["line_count"], 2)
        self.assertEqual(payload["summary"]["job_count"], 6)
        onion_jobs = [job for job in payload["collection_jobs"] if job["line_name"] == "洋葱"]
        self.assertEqual({job["query"] for job in onion_jobs}, {"黄皮洋葱", "洋葱"})
        self.assertTrue(all(job["pages"] == [1, 2] for job in payload["collection_jobs"]))

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


if __name__ == "__main__":
    unittest.main()
