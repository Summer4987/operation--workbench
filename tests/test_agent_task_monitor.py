from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import agent_task_monitor as monitor_module  # noqa: E402


class AgentTaskMonitorTests(unittest.TestCase):
    def test_health_warning_takes_precedence_over_success_run(self) -> None:
        self.assertEqual(monitor_module.classify_completion("warn", "success"), "attention")

    def test_attention_reason_prefers_health_reason(self) -> None:
        row = monitor_module.build_task_report(
            "ops.realtime_order_income",
            {
                "id": "ops.realtime_order_income",
                "status": "warn",
                "reason": "实时采集数据已生成，但云端发布权限错误。",
                "last_seen_at": "2026-06-30 20:01:15",
            },
            {
                "tasks": {
                    "ops.realtime_order_income": {
                        "status": "success",
                        "message": "实时单量收入采集完成。",
                        "updated_at": "2026-06-30 20:01:15",
                    }
                }
            },
            {"name": "实时单量和营业额采集"},
        )

        self.assertEqual(row["status"], "attention")
        self.assertIn("云端发布权限错误", row["failure_reason"])


if __name__ == "__main__":
    unittest.main()
