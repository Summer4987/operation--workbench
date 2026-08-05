from __future__ import annotations

import unittest

from scripts.build_workbench_data import build_realtime_comparison


def snapshot(generated_at: str, orders: int, income: float) -> dict:
    return {
        "generated_at": generated_at,
        "status": "ok",
        "summary": {"total_orders": orders, "total_income": income},
        "stores": [],
    }


class RealtimeComparisonTests(unittest.TestCase):
    def test_uses_success_snapshot_within_same_period_tolerance(self) -> None:
        realtime = snapshot("2026-08-05 12:30:56", 849, 27212.1)
        history = [snapshot("2026-08-04 12:36:00", 700, 22000)]

        result = build_realtime_comparison(realtime, history)

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["matched_time"], "2026-08-04 12:36:00")
        self.assertEqual(result["summary"]["orders"]["delta"], 149)

    def test_marks_same_period_missing_and_returns_surrounding_success_snapshots(self) -> None:
        realtime = snapshot("2026-08-05 12:30:56", 849, 27212.1)
        history = [
            snapshot("2026-08-04 11:31:12", 500, 16000),
            snapshot("2026-08-04 12:00:55", 620, 20000),
            snapshot("2026-08-04 13:46:23", 980, 31000),
        ]

        result = build_realtime_comparison(realtime, history)

        self.assertEqual(result["status"], "time_missing")
        self.assertEqual(result["message"], "昨日同时段数据缺失")
        self.assertNotIn("summary", result)
        self.assertEqual(
            [item["generated_at"] for item in result["nearest_snapshots"]],
            ["2026-08-04 12:00:55", "2026-08-04 13:46:23"],
        )
        self.assertEqual(result["nearest_snapshots"][0]["summary"]["current_order_delta"], 229)
        self.assertEqual(result["nearest_snapshots"][1]["relation"], "after")

    def test_returns_two_nearest_when_only_earlier_snapshots_exist(self) -> None:
        realtime = snapshot("2026-08-05 20:00:00", 1200, 40000)
        history = [
            snapshot("2026-08-04 18:30:00", 900, 30000),
            snapshot("2026-08-04 19:00:00", 1000, 33000),
        ]

        result = build_realtime_comparison(realtime, history)

        self.assertEqual(result["status"], "time_missing")
        self.assertEqual(len(result["nearest_snapshots"]), 2)
        self.assertEqual(result["nearest_snapshots"][-1]["generated_at"], "2026-08-04 19:00:00")

    def test_failed_snapshot_is_not_used_as_same_period_baseline(self) -> None:
        realtime = snapshot("2026-08-05 12:30:00", 849, 27212.1)
        failed = snapshot("2026-08-04 12:30:30", 800, 25000)
        failed["status"] = "failed"
        history = [failed, snapshot("2026-08-04 12:00:00", 620, 20000)]

        result = build_realtime_comparison(realtime, history)

        self.assertEqual(result["status"], "time_missing")
        self.assertEqual(
            [item["generated_at"] for item in result["nearest_snapshots"]],
            ["2026-08-04 12:00:00"],
        )


if __name__ == "__main__":
    unittest.main()
