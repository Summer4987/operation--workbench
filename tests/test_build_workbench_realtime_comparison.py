from __future__ import annotations

import unittest

from scripts.build_workbench_data import build_realtime_comparison


def snapshot(generated_at: str, orders: int, income: float) -> dict:
    return {
        "generated_at": generated_at,
        "status": "ok",
        "summary": {"total_orders": orders, "total_income": income},
        "stores": [{"store": "双井", "orders": orders, "income": income}],
    }


class RealtimeComparisonTests(unittest.TestCase):
    def test_uses_success_snapshot_within_same_period_tolerance(self):
        result = build_realtime_comparison(snapshot("2026-08-05 12:30:56", 849, 27212.1), [
            snapshot("2026-08-04 12:36:00", 700, 22000),
            snapshot("2026-07-29 12:31:00", 600, 19000),
        ])
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["match_mode"], "same_period")
        self.assertEqual(result["matched_time"], "2026-08-04 12:36:00")
        self.assertEqual(result["summary"]["orders"]["delta"], 149)
        self.assertEqual(result["last_week"]["status"], "ready")
        self.assertEqual(result["last_week"]["summary"]["orders"]["previous"], 600)

    def test_uses_nearest_success_outside_tolerance_for_totals_and_stores(self):
        result = build_realtime_comparison(snapshot("2026-08-05 12:30:56", 849, 27212.1), [
            snapshot("2026-08-04 11:31:12", 500, 16000),
            snapshot("2026-08-04 12:00:55", 620, 20000),
            snapshot("2026-08-04 13:46:23", 980, 31000),
        ])
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["match_mode"], "nearest")
        self.assertEqual(result["matched_time"], "2026-08-04 12:00:55")
        self.assertIn("最临近", result["message"])
        self.assertEqual(result["summary"]["orders"]["delta"], 229)
        self.assertEqual(result["stores"][0]["orders"]["delta"], 229)
        self.assertAlmostEqual(result["stores"][0]["income"]["delta"], 7212.1)

    def test_2039_uses_yesterday_2000_as_requested(self):
        result = build_realtime_comparison(snapshot("2026-10-21 20:39:28", 1544, 46859.9), [
            snapshot("2026-10-20 19:30:00", 1538, 47442),
            snapshot("2026-10-20 20:00:00", 1565, 48205),
        ])
        self.assertEqual(result["matched_time"], "2026-10-20 20:00:00")
        self.assertEqual(result["summary"]["orders"]["delta"], -21)
        self.assertAlmostEqual(result["summary"]["income"]["delta"], -1345.1)

    def test_closer_later_snapshot_is_used(self):
        result = build_realtime_comparison(snapshot("2026-08-05 12:30:00", 849, 27212.1), [
            snapshot("2026-08-04 11:00:00", 500, 16000),
            snapshot("2026-08-04 13:00:00", 900, 28000),
        ])
        self.assertEqual(result["matched_time"], "2026-08-04 13:00:00")
        self.assertEqual(result["summary"]["orders"]["delta"], -51)

    def test_equal_distance_prefers_earlier_snapshot(self):
        result = build_realtime_comparison(snapshot("2026-08-05 12:30:00", 849, 27212.1), [
            snapshot("2026-08-04 13:00:00", 900, 28000),
            snapshot("2026-08-04 12:00:00", 620, 20000),
        ])
        self.assertEqual(result["matched_time"], "2026-08-04 12:00:00")

    def test_failed_snapshot_is_ignored_and_last_week_also_uses_nearest(self):
        failed = snapshot("2026-08-04 12:30:30", 800, 25000)
        failed["status"] = "failed"
        result = build_realtime_comparison(snapshot("2026-08-05 12:30:00", 849, 27212.1), [
            failed, snapshot("2026-08-04 12:00:00", 620, 20000),
            snapshot("2026-07-29 13:00:00", 600, 19000),
        ])
        self.assertEqual(result["matched_time"], "2026-08-04 12:00:00")
        self.assertEqual(result["last_week"]["match_mode"], "nearest")
        self.assertEqual(result["last_week"]["summary"]["orders"]["previous"], 600)

    def test_day_without_any_success_remains_unavailable(self):
        result = build_realtime_comparison(snapshot("2026-08-05 12:30:00", 849, 27212.1), [
            snapshot("2026-08-03 12:30:00", 620, 20000),
        ])
        self.assertEqual(result["status"], "pending")
        self.assertNotIn("summary", result)
        self.assertNotIn("matched_time", result)


if __name__ == "__main__":
    unittest.main()
