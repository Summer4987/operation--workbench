from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import agent_command  # noqa: E402


class AgentCommandTests(unittest.TestCase):
    def test_ordering_command_is_blocked(self) -> None:
        payload = agent_command.handle_command("帮我补跑订货", execute=True)

        self.assertEqual(payload["intent"], "blocked_ordering")
        self.assertTrue(payload["blocked"])
        self.assertIn("不参与订货", payload["answer"])

    def test_execute_non_ordering_requires_flag(self) -> None:
        payload = agent_command.handle_command("执行非订货恢复", execute=False)

        self.assertEqual(payload["intent"], "execute_non_ordering")
        self.assertIn("--execute", payload["answer"])

    def test_problem_command_routes_to_problem_intent(self) -> None:
        self.assertEqual(agent_command.classify_intent("今天哪里有问题"), "problems")

    def test_refresh_command_routes_to_refresh_intent(self) -> None:
        self.assertEqual(agent_command.classify_intent("刷新状态"), "refresh_status")


if __name__ == "__main__":
    unittest.main()
