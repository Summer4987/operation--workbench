from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from kuailv_adb_order_candidate_collection import build_plan_payload  # noqa: E402
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


if __name__ == "__main__":
    unittest.main()
