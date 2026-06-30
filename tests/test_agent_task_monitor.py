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


if __name__ == "__main__":
    unittest.main()
