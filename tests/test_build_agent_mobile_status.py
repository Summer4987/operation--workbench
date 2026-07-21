from __future__ import annotations

import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import build_agent_mobile_status


class AgentMobileStatusTests(unittest.TestCase):
    def test_payload_contains_safe_mobile_answers(self) -> None:
        payload = build_agent_mobile_status.build_payload()

        self.assertFalse(payload["safety"]["mobile_can_execute"])
        self.assertFalse(payload["safety"]["execution_agent_enabled"])
        self.assertEqual({item["id"] for item in payload["answers"]}, {"status", "problems", "rerun", "execution_agent"})
        self.assertIn("blocked_ordering", {item["intent"] for item in payload["commands"]})
        self.assertEqual(payload["assistant"]["name"], "运营 Agent")
        self.assertIn("今天跑得稳不稳？", {item["text"] for item in payload["commands"]})
        self.assertIn("task_runs_stale", payload["data_freshness"])

    def test_payload_answers_do_not_use_llm_rewrite(self) -> None:
        original_generate_answer = build_agent_mobile_status.agent_chat.agent_llm.generate_answer
        try:
            build_agent_mobile_status.agent_chat.agent_llm.generate_answer = lambda **kwargs: {
                "used": True,
                "answer": "错误改写",
                "confidence": 1,
            }

            payload = build_agent_mobile_status.build_payload()

            self.assertNotIn("错误改写", {item["answer"] for item in payload["answers"]})
        finally:
            build_agent_mobile_status.agent_chat.agent_llm.generate_answer = original_generate_answer


if __name__ == "__main__":
    unittest.main()
