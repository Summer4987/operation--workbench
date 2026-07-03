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

    def test_budget_rerun_routes_to_preview(self) -> None:
        self.assertEqual(agent_command.classify_intent("重跑预算设置"), "budget_preview")

    def test_budget_commit_requires_confirmation_phrase(self) -> None:
        payload = agent_command.handle_command("确认执行预算重跑", execute=False)

        self.assertEqual(payload["intent"], "budget_commit")
        self.assertIn("--execute", payload["answer"])

    def test_budget_preview_requires_execute_flag(self) -> None:
        payload = agent_command.handle_command("重跑预算设置", execute=False)

        self.assertEqual(payload["intent"], "budget_preview")
        self.assertIn("预算预览", payload["answer"])

    def test_cli_supports_notification_dry_run(self) -> None:
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "command.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "agent_command.py"),
                    "重跑预算设置",
                    "--notify",
                    "--notify-dry-run",
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertTrue(output.exists())
            self.assertIn("--execute", output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
