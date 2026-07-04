from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import agent_llm  # noqa: E402


class AgentLlmTests(unittest.TestCase):
    def test_load_env_file_parses_exported_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "env"
            path.write_text(
                "export AGENT_LLM_API_KEY='secret'\n"
                "export AGENT_LLM_BASE_URL='https://api.deepseek.com'\n"
                "export AGENT_LLM_MODEL='deepseek-chat'\n",
                encoding="utf-8",
            )

            env = agent_llm.load_env_file(path)

            self.assertEqual(env["AGENT_LLM_API_KEY"], "secret")
            self.assertEqual(env["AGENT_LLM_MODEL"], "deepseek-chat")

    def test_classify_disabled_returns_fallback_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "agent_llm.json"
            config.write_text(json.dumps({"enabled": False}), encoding="utf-8")

            payload = agent_llm.classify("任务正常吗", config_path=config, env_path=Path(temp_dir) / "env")

            self.assertFalse(payload["used"])
            self.assertEqual(payload["error"], "llm-disabled")

    def test_classify_accepts_mocked_json_response(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config = temp_path / "agent_llm.json"
            env = temp_path / "env"
            config.write_text(
                json.dumps(
                    {
                        "enabled": True,
                        "mode": "advisory_only",
                        "api_key_env": "AGENT_LLM_API_KEY",
                        "base_url_env": "AGENT_LLM_BASE_URL",
                        "model_env": "AGENT_LLM_MODEL",
                    }
                ),
                encoding="utf-8",
            )
            env.write_text(
                "export AGENT_LLM_API_KEY='secret'\n"
                "export AGENT_LLM_BASE_URL='https://api.deepseek.com'\n"
                "export AGENT_LLM_MODEL='deepseek-chat'\n",
                encoding="utf-8",
            )
            with mock.patch.object(
                agent_llm,
                "call_chat_completion",
                return_value={"raw": {"intent": "status", "confidence": 0.92, "reason": "询问状态"}, "usage": {}},
            ):
                payload = agent_llm.classify("今天跑得稳不稳", config_path=config, env_path=env)

            self.assertTrue(payload["used"])
            self.assertEqual(payload["intent"], "status")
            self.assertGreater(payload["confidence"], 0.9)

    def test_budget_commit_is_downgraded_when_not_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config = temp_path / "agent_llm.json"
            env = temp_path / "env"
            config.write_text(json.dumps({"enabled": True, "mode": "advisory_only"}), encoding="utf-8")
            env.write_text(
                "export AGENT_LLM_API_KEY='secret'\n"
                "export AGENT_LLM_BASE_URL='https://api.deepseek.com'\n"
                "export AGENT_LLM_MODEL='deepseek-chat'\n",
                encoding="utf-8",
            )
            with mock.patch.object(
                agent_llm,
                "call_chat_completion",
                return_value={"raw": {"intent": "budget_commit", "confidence": 0.9, "reason": "模型误判"}, "usage": {}},
            ):
                payload = agent_llm.classify("预算看看", config_path=config, env_path=env)

            self.assertEqual(payload["intent"], "budget_preview")

    def test_generate_answer_accepts_mocked_json_response(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config = temp_path / "agent_llm.json"
            env = temp_path / "env"
            config.write_text(json.dumps({"enabled": True, "mode": "advisory_only"}), encoding="utf-8")
            env.write_text(
                "export AGENT_LLM_API_KEY='secret'\n"
                "export AGENT_LLM_BASE_URL='https://api.deepseek.com'\n"
                "export AGENT_LLM_MODEL='deepseek-chat'\n",
                encoding="utf-8",
            )
            with mock.patch.object(
                agent_llm,
                "call_answer_completion",
                return_value={
                    "raw": {
                        "answer": "今天 agent 正常，执行 Agent 没有参与订货。",
                        "confidence": 0.88,
                        "reason": "基于本地状态草稿回答",
                    },
                    "usage": {},
                },
            ):
                payload = agent_llm.generate_answer(
                    question="今天正常吗",
                    draft_answer="成功 5 个，跳过 1 个。",
                    context={"safety": {"ordering_excluded": True}},
                    config_path=config,
                    env_path=env,
                )

            self.assertTrue(payload["used"])
            self.assertIn("agent 正常", payload["answer"])


if __name__ == "__main__":
    unittest.main()
