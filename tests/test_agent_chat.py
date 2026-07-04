from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import agent_chat  # noqa: E402


class AgentChatTests(unittest.TestCase):
    def test_execution_question_names_skipped_agent(self) -> None:
        answer = agent_chat.build_execution_answer(
            {
                "stages": [
                    {"id": "collect", "agent": "collect", "name": "采集 Agent", "status": "success"},
                    {
                        "id": "execute",
                        "agent": "execution",
                        "name": "执行 Agent",
                        "status": "skipped",
                        "message": "执行 Agent 需要显式 --allow-execution。",
                    },
                ]
            }
        )

        self.assertIn("执行 Agent", answer)
        self.assertIn("id: execute", answer)
        self.assertIn("--allow-execution", answer)

    def test_execution_question_reports_successful_execution_agent(self) -> None:
        answer = agent_chat.build_execution_answer(
            {
                "stages": [
                    {
                        "id": "execute",
                        "agent": "execution",
                        "name": "执行 Agent",
                        "status": "success",
                    }
                ]
            }
        )

        self.assertIn("执行 Agent 已参与", answer)
        self.assertIn("订货/下单/采购类动作不参与", answer)

    def test_problem_answer_prefers_pipeline_failure(self) -> None:
        answer = agent_chat.build_problem_answer(
            {"stages": [{"name": "校验 Agent", "status": "failed", "message": "缺少产物"}]},
            {"tasks": []},
        )

        self.assertIn("校验 Agent", answer)
        self.assertIn("缺少产物", answer)

    def test_answer_question_uses_latest_files(self) -> None:
        original_root = agent_chat.ROOT
        original_pipeline_path = agent_chat.PIPELINE_PATH
        original_monitor_path = agent_chat.MONITOR_PATH
        original_task_runs_path = agent_chat.TASK_RUNS_PATH
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                pipeline_path = root / "outputs" / "agent_pipeline" / "daily_automation_guard" / "latest.json"
                monitor_path = root / "outputs" / "agent_task_monitor" / "latest.json"
                task_runs_path = root / "outputs" / "task_runs" / "latest.json"
                pipeline_path.parent.mkdir(parents=True)
                monitor_path.parent.mkdir(parents=True)
                task_runs_path.parent.mkdir(parents=True)
                pipeline_path.write_text(
                    '{"generated_at":"2026-07-03 10:00:00","summary":{"success":5,"failed":0,"skipped":1},"stages":[{"id":"execute","agent":"execution","name":"执行 Agent","status":"skipped","message":"默认禁用"}]}',
                    encoding="utf-8",
                )
                monitor_path.write_text('{"summary":{"completed":1,"failed":0,"attention":0},"tasks":[]}', encoding="utf-8")
                task_runs_path.write_text('{"generated_at":"2026-07-03 10:00:01","tasks":{}}', encoding="utf-8")
                agent_chat.ROOT = root
                agent_chat.PIPELINE_PATH = pipeline_path
                agent_chat.MONITOR_PATH = monitor_path
                agent_chat.TASK_RUNS_PATH = task_runs_path

                payload = agent_chat.answer_question("现在 agent 状态怎么样？", use_llm=False)

                self.assertEqual(payload["intent"], "status")
                self.assertIn("成功 5 个", payload["answer"])
                self.assertIn("执行 Agent", payload["answer"])
        finally:
            agent_chat.ROOT = original_root
            agent_chat.PIPELINE_PATH = original_pipeline_path
            agent_chat.MONITOR_PATH = original_monitor_path
            agent_chat.TASK_RUNS_PATH = original_task_runs_path

    def test_answer_question_can_use_llm_generated_answer(self) -> None:
        original_generate_answer = agent_chat.agent_llm.generate_answer
        try:
            agent_chat.agent_llm.generate_answer = lambda **kwargs: {
                "used": True,
                "answer": "今天整体正常，执行 Agent 仍按规则排除订货。",
                "confidence": 0.82,
                "provider": "deepseek",
                "model": "deepseek-chat",
                "reason": "基于草稿改写",
            }

            payload = agent_chat.answer_question("今天稳不稳？")

            self.assertTrue(payload["llm"]["used"])
            self.assertIn("整体正常", payload["answer"])
            self.assertIn("draft_answer", payload["llm"])
        finally:
            agent_chat.agent_llm.generate_answer = original_generate_answer

    def test_answer_question_falls_back_when_llm_confidence_is_low(self) -> None:
        original_generate_answer = agent_chat.agent_llm.generate_answer
        try:
            agent_chat.agent_llm.generate_answer = lambda **kwargs: {
                "used": True,
                "answer": "低置信度回答",
                "confidence": 0.2,
                "provider": "deepseek",
                "model": "deepseek-chat",
                "reason": "不确定",
            }

            payload = agent_chat.answer_question("现在 agent 状态怎么样？")

            self.assertFalse("低置信度回答" == payload["answer"])
            self.assertTrue(payload["llm"]["used"])
        finally:
            agent_chat.agent_llm.generate_answer = original_generate_answer


if __name__ == "__main__":
    unittest.main()
