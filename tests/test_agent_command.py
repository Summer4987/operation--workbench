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

    def test_normal_status_question_is_hard_status(self) -> None:
        intent, llm = agent_command.classify_intent_with_llm("今天 agent 正常吗")

        self.assertEqual(intent, "status")
        self.assertEqual(llm["fallback"], "hard-status-query")

    def test_execution_agent_question_still_routes_to_execution_status(self) -> None:
        intent, llm = agent_command.classify_intent_with_llm("刚刚跳过的执行 Agent 是谁")

        self.assertEqual(intent, "execution_status")
        self.assertEqual(llm["fallback"], "hard-execution-status-query")

    def test_budget_rerun_routes_to_preview(self) -> None:
        self.assertEqual(agent_command.classify_intent("重跑预算设置"), "budget_preview")

    def test_budget_commit_requires_confirmation_phrase(self) -> None:
        payload = agent_command.handle_command("确认执行预算重跑", execute=False)

        self.assertEqual(payload["intent"], "budget_commit")
        self.assertIn("--execute", payload["answer"])

    def test_meituan_spend_inspection_routes_to_readonly_inspection(self) -> None:
        payload = agent_command.handle_command("巡检美团实时消耗", execute=False, use_llm=False)

        self.assertEqual(payload["intent"], "meituan_spend_inspection")
        self.assertIn("只读巡检", payload["answer"])
        self.assertIn("--execute", payload["answer"])

    def test_meituan_spend_inspection_execute_runs_query_script(self) -> None:
        original_run_command = agent_command.run_command
        try:
            calls = []

            def fake_run_command(command, *, timeout=900):
                calls.append(command)
                return {"command": command, "returncode": 0, "output_tail": "美团推广实时消耗巡检：\n总览：已读到 1/1 家。"}

            agent_command.run_command = fake_run_command
            payload = agent_command.handle_command("查一下美团推广花费", execute=True, use_llm=False)
        finally:
            agent_command.run_command = original_run_command

        self.assertEqual(payload["intent"], "meituan_spend_inspection")
        self.assertIn("美团推广实时消耗巡检", payload["answer"])
        self.assertTrue(any(any(str(part).endswith("meituan_promo_spend_query.py") for part in command) for command in calls))
        self.assertTrue(any("--period" in command and "all" in command and "--quiet" in command for command in calls))

    def test_budget_preview_requires_execute_flag(self) -> None:
        payload = agent_command.handle_command("重跑预算设置", execute=False)

        self.assertEqual(payload["intent"], "budget_preview")
        self.assertIn("预算预览", payload["answer"])

    def test_execute_rerun_runs_safe_rerun_script(self) -> None:
        original_run_command = agent_command.run_command
        try:
            calls = []

            def fake_run_command(command, *, timeout=900):
                calls.append(command)
                if any(str(part).endswith("agent_rerun_dry_run.py") for part in command):
                    return {"command": command, "returncode": 0, "output_tail": "我已经尝试补跑 1 个低风险任务，成功 1 个，失败 0 个。"}
                return {"command": command, "returncode": 0, "output_tail": "ok"}

            agent_command.run_command = fake_run_command
            payload = agent_command.handle_command("执行补跑", execute=True, use_llm=False)
        finally:
            agent_command.run_command = original_run_command

        self.assertEqual(payload["intent"], "rerun_plan")
        self.assertIn("成功 1 个", payload["answer"])
        self.assertTrue(any(any(str(part).endswith("agent_task_monitor.py") for part in command) for command in calls))
        self.assertTrue(any(command[-1] == "--execute" and any(str(part).endswith("agent_rerun_dry_run.py") for part in command) for command in calls))

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

    def test_llm_advice_can_route_casual_status_question(self) -> None:
        original = agent_command.agent_llm.classify
        try:
            agent_command.agent_llm.classify = lambda text: {
                "used": True,
                "intent": "status",
                "confidence": 0.9,
                "provider": "deepseek",
                "model": "deepseek-chat",
                "reason": "询问任务情况",
            }
            intent, llm = agent_command.classify_intent_with_llm("今天靠不靠谱")
            self.assertEqual(intent, "status")
            self.assertTrue(llm["used"])
        finally:
            agent_command.agent_llm.classify = original

    def test_llm_low_confidence_falls_back_to_keywords(self) -> None:
        original = agent_command.agent_llm.classify
        try:
            agent_command.agent_llm.classify = lambda text: {
                "used": True,
                "intent": "chat",
                "confidence": 0.2,
                "provider": "deepseek",
                "model": "deepseek-chat",
            }
            intent, llm = agent_command.classify_intent_with_llm("刷新状态")
            self.assertEqual(intent, "refresh_status")
            self.assertEqual(llm["fallback"], "hard-refresh-query")
        finally:
            agent_command.agent_llm.classify = original

    def test_ordering_hard_block_runs_before_llm(self) -> None:
        original = agent_command.agent_llm.classify
        try:
            def fail_if_called(text: str) -> dict:
                raise AssertionError("LLM should not be called for ordering commands")

            agent_command.agent_llm.classify = fail_if_called
            intent, llm = agent_command.classify_intent_with_llm("帮我订货补跑")
            self.assertEqual(intent, "blocked_ordering")
            self.assertEqual(llm["fallback"], "hard-ordering-block")
        finally:
            agent_command.agent_llm.classify = original


if __name__ == "__main__":
    unittest.main()
