from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import agent_execution  # noqa: E402


class AgentExecutionTests(unittest.TestCase):
    def test_ordering_action_is_blocked(self) -> None:
        record = agent_execution.run_action(
            {"id": "inventory_order_submit", "name": "订货提交", "command": ["echo", "order"]},
            timeout=10,
            dry_run=False,
        )

        self.assertEqual(record["status"], "blocked")
        self.assertIn("订货", record["reason"])

    def test_description_can_explain_ordering_exclusion(self) -> None:
        record = agent_execution.run_action(
            {
                "id": "safe_rerun_plan",
                "name": "生成安全补跑计划",
                "description": "订货相关任务保持排除。",
                "command": ["echo", "ok"],
            },
            timeout=10,
            dry_run=True,
        )

        self.assertEqual(record["status"], "planned")

    def test_non_ordering_action_can_be_planned(self) -> None:
        record = agent_execution.run_action(
            {"id": "refresh_mobile", "name": "刷新手机状态", "command": ["echo", "ok"]},
            timeout=10,
            dry_run=True,
        )

        self.assertEqual(record["status"], "planned")

    def test_action_timeout_is_failed_record(self) -> None:
        record = agent_execution.run_action(
            {
                "id": "slow_action",
                "name": "慢动作",
                "command": ["{python}", "-c", "import time; time.sleep(2)"],
                "timeout_seconds": 1,
            },
            timeout=10,
            dry_run=False,
        )

        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["returncode"], 124)


if __name__ == "__main__":
    unittest.main()
