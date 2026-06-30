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
        self.assertEqual(decision["status"], "blocked")
        self.assertEqual(decision["safe_candidate_count"], 0)
        self.assertIn("missing_pack_quantity", decision["top_candidates"][0]["risk_flags"])

    def test_explicit_pack_candidate_can_be_selected(self) -> None:
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
                    "title": "黄皮洋葱",
                    "spec": "20斤",
                    "price": 24,
                    "monthly_sales": 8000,
                    "sort_mode": "price_asc",
                    "search_page": 1,
                    "available": True,
                }
            ]
        }

        payload = build_payload(order, candidates, 2, ["price_asc", "sales_desc"])

        decision = payload["decisions"][0]
        self.assertEqual(decision["status"], "ready")
        self.assertEqual(decision["selection"][0]["count"], 2)

    def test_missing_price_candidates_are_not_safe(self) -> None:
        order = {
            "order_id": "DO-TEST",
            "store_name": "银泰城店",
            "submitted_at": "2026-06-17T10:00:00+08:00",
            "items": [
                {
                    "sku": "MUSHROOM-001",
                    "name": "白玉菇",
                    "quantity": 15,
                    "unit": "斤",
                    "purchase_channel": "快驴",
                },
                {
                    "sku": "MEAL-001",
                    "name": "工作餐（自主填写）",
                    "quantity": 1,
                    "unit": "份",
                    "note": "自主填写",
                    "purchase_channel": "快驴",
                },
            ],
        }
        candidates = {
            "白玉菇": [
                {
                    "title": "白玉菇",
                    "spec": "1斤",
                    "monthly_sales": 8203,
                    "sort_mode": "sales_desc",
                    "search_page": 1,
                    "available": True,
                }
            ]
        }

        payload = build_payload(order, candidates, 2, ["price_asc", "sales_desc"])

        self.assertEqual(payload["decisions"][0]["status"], "blocked")
        self.assertEqual(payload["decisions"][0]["safe_candidate_count"], 0)
        self.assertEqual(payload["decisions"][1]["status"], "manual_note_only")

    def test_potato_can_fallback_to_twenty_jin_when_five_jin_missing(self) -> None:
        order = {
            "order_id": "DO-TEST",
            "store_name": "银泰城店",
            "submitted_at": "2026-06-17T10:00:00+08:00",
            "items": [
                {
                    "sku": "POTATO-001",
                    "name": "土豆",
                    "quantity": 15,
                    "unit": "斤",
                    "purchase_channel": "快驴",
                }
            ],
        }
        candidates = {
            "土豆": [
                {
                    "title": "刀削土豆",
                    "spec": "20斤",
                    "unit_price": 0.67,
                    "monthly_sales": 9000,
                    "sort_mode": "price_asc",
                    "search_page": 1,
                    "available": True,
                }
            ]
        }

        payload = build_payload(order, candidates, 2, ["price_asc", "sales_desc"])

        decision = payload["decisions"][0]
        self.assertEqual(decision["status"], "ready")
        self.assertEqual(decision["planned_quantity"], 20)
        self.assertEqual(decision["overage"], 5)
        self.assertEqual(decision["selection"][0]["spec"], "20斤")

    def test_canteen_dish_candidates_are_globally_rejected(self) -> None:
        order = {
            "order_id": "DO-TEST",
            "store_name": "银泰城店",
            "submitted_at": "2026-06-17T10:00:00+08:00",
            "items": [
                {
                    "sku": "POTATO-001",
                    "name": "土豆",
                    "quantity": 15,
                    "unit": "斤",
                    "purchase_channel": "快驴",
                }
            ],
        }
        candidates = {
            "土豆": [
                {
                    "title": "刀削土豆食堂菜",
                    "spec": "20斤",
                    "unit_price": 0.67,
                    "monthly_sales": 9000,
                    "sort_mode": "price_asc",
                    "search_page": 1,
                    "available": True,
                }
            ]
        }

        payload = build_payload(order, candidates, 2, ["price_asc", "sales_desc"])

        decision = payload["decisions"][0]
        self.assertEqual(decision["status"], "blocked")
        self.assertEqual(decision["safe_candidate_count"], 0)
        self.assertIn("canteen_dish_keyword_seen", decision["top_candidates"][0]["risk_flags"])

    def test_canteen_dish_row_tag_is_globally_rejected(self) -> None:
        order = {
            "order_id": "DO-TEST",
            "store_name": "银泰城店",
            "submitted_at": "2026-06-17T10:00:00+08:00",
            "items": [
                {
                    "sku": "MUSHROOM-001",
                    "name": "白玉菇",
                    "quantity": 15,
                    "unit": "斤",
                    "purchase_channel": "快驴",
                }
            ],
        }
        candidates = {
            "白玉菇": [
                {
                    "title": "白玉菇 散装",
                    "spec": "4斤",
                    "unit_price": 2.43,
                    "monthly_sales": 521,
                    "sort_mode": "price_asc",
                    "search_page": 1,
                    "available": True,
                    "row_texts": ["白玉菇 散装", "月售521", "食堂菜", "4斤"],
                }
            ]
        }

        payload = build_payload(order, candidates, 2, ["price_asc"])

        decision = payload["decisions"][0]
        self.assertEqual(decision["status"], "blocked")
        self.assertEqual(decision["safe_candidate_count"], 0)
        self.assertIn("canteen_dish_keyword_seen", decision["top_candidates"][0]["risk_flags"])

    def test_canteen_dish_award_text_alone_does_not_reject_candidate(self) -> None:
        order = {
            "order_id": "DO-TEST",
            "store_name": "银泰城店",
            "submitted_at": "2026-06-17T10:00:00+08:00",
            "items": [
                {
                    "sku": "CARROT-001",
                    "name": "胡萝卜",
                    "quantity": 10,
                    "unit": "斤",
                    "purchase_channel": "快驴",
                }
            ],
        }
        candidates = {
            "胡萝卜": [
                {
                    "title": "断节胡萝卜",
                    "spec": "10斤",
                    "unit_price": 0.31,
                    "monthly_sales": 16000,
                    "sort_mode": "price_asc",
                    "search_page": 1,
                    "available": True,
                    "row_texts": ["断节胡萝卜", "胡萝卜食堂菜销量第1名", "10斤"],
                }
            ]
        }

        payload = build_payload(order, candidates, 2, ["price_asc"])

        decision = payload["decisions"][0]
        self.assertEqual(decision["status"], "ready")
        self.assertNotIn("canteen_dish_keyword_seen", decision["top_candidates"][0]["risk_flags"])

    def test_unavailable_time_window_candidate_is_rejected(self) -> None:
        order = {
            "order_id": "DO-TEST",
            "store_name": "银泰城店",
            "submitted_at": "2026-06-17T10:00:00+08:00",
            "items": [
                {
                    "sku": "MUSHROOM-001",
                    "name": "白玉菇",
                    "quantity": 15,
                    "unit": "斤",
                    "purchase_channel": "快驴",
                }
            ],
        }
        candidates = {
            "白玉菇": [
                {
                    "title": "白玉菇散菇",
                    "spec": "4斤",
                    "unit_price": 2.88,
                    "monthly_sales": 1142,
                    "sort_mode": "price_asc",
                    "search_page": 1,
                    "available": True,
                    "row_texts": ["白玉菇散菇", "即将开售", "仓非可售时间", "休息中", "4斤"],
                }
            ]
        }

        payload = build_payload(order, candidates, 2, ["price_asc"])

        decision = payload["decisions"][0]
        self.assertEqual(decision["status"], "blocked")
        self.assertEqual(decision["safe_candidate_count"], 0)
        self.assertIn("unavailable_time_window_seen", decision["top_candidates"][0]["risk_flags"])

    def test_equal_value_combination_prefers_fewer_clicks(self) -> None:
        order = {
            "order_id": "DO-TEST",
            "store_name": "银泰城店",
            "submitted_at": "2026-06-17T10:00:00+08:00",
            "items": [
                {
                    "sku": "CARROT-001",
                    "name": "胡萝卜",
                    "quantity": 10,
                    "unit": "斤",
                    "purchase_channel": "快驴",
                }
            ],
        }
        candidates = {
            "胡萝卜": [
                {
                    "title": "断节胡萝卜",
                    "spec": "5斤",
                    "unit_price": 0.31,
                    "monthly_sales": 16000,
                    "sort_mode": "price_asc",
                    "search_page": 1,
                    "available": True,
                },
                {
                    "title": "断节胡萝卜",
                    "spec": "10斤",
                    "unit_price": 0.31,
                    "monthly_sales": 16000,
                    "sort_mode": "price_asc",
                    "search_page": 1,
                    "available": True,
                },
            ]
        }

        payload = build_payload(order, candidates, 2, ["price_asc"])

        decision = payload["decisions"][0]
        self.assertEqual(decision["status"], "ready")
        self.assertEqual(decision["selection"][0]["spec"], "10斤")
        self.assertEqual(decision["selection"][0]["count"], 1)

    def test_explicit_price_unit_mismatch_is_ranked_as_risk(self) -> None:
        order = {
            "order_id": "DO-TEST",
            "store_name": "银泰城店",
            "submitted_at": "2026-06-17T10:00:00+08:00",
            "items": [
                {
                    "sku": "CARROT-001",
                    "name": "胡萝卜",
                    "quantity": 10,
                    "unit": "斤",
                    "purchase_channel": "快驴",
                }
            ],
        }
        candidates = {
            "胡萝卜": [
                {
                    "title": "断节胡萝卜",
                    "spec": "10斤",
                    "unit_price": 0.31,
                    "monthly_sales": 16000,
                    "sort_mode": "price_asc",
                    "search_page": 1,
                    "available": True,
                    "row_texts": ["断节胡萝卜", "10斤", "¥", "0.31", "/盒"],
                }
            ]
        }

        payload = build_payload(order, candidates, 2, ["price_asc"])

        decision = payload["decisions"][0]
        self.assertEqual(decision["status"], "blocked")
        self.assertEqual(decision["safe_candidate_count"], 0)
        self.assertEqual(decision["top_candidates"][0]["rank"], 1)
        self.assertEqual(decision["top_candidates"][0]["price_unit"], "盒")
        self.assertIn("断节胡萝卜", decision["top_candidates"][0]["candidate_text"])
        self.assertIn("unit_mismatch", decision["top_candidates"][0]["risk_flags"])


if __name__ == "__main__":
    unittest.main()
