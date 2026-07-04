from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "inventory-board"))
sys.path.insert(0, str(ROOT / "scripts"))

from app import agent_inbox, agent_wecom  # noqa: E402
import agent_inbox_worker  # noqa: E402


class AgentInboxTests(unittest.TestCase):
    def test_budget_preview_policy_enqueues_preview_only(self) -> None:
        policy = agent_inbox.command_policy("重跑预算设置")

        self.assertTrue(policy["enqueue"])
        self.assertEqual(policy["intent"], "budget_preview")
        self.assertTrue(policy["execute"])

    def test_ordering_policy_is_blocked(self) -> None:
        policy = agent_inbox.command_policy("帮我补跑订货")

        self.assertFalse(policy["enqueue"])
        self.assertEqual(policy["intent"], "blocked_ordering")

    def test_inbox_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "inbox.json"
            item = agent_inbox.append_task(
                text="刷新状态",
                intent="refresh_status",
                execute=True,
                source="test",
                path=path,
            )

            self.assertEqual(len(agent_inbox.pending_tasks(path=path)), 1)
            claimed = agent_inbox.claim_task(item["id"], worker="macmini", path=path)
            self.assertIsNotNone(claimed)
            self.assertEqual(claimed["status"], "running")
            updated = agent_inbox.complete_task(item["id"], status="success", result={"returncode": 0}, path=path)
            self.assertEqual(updated["status"], "success")
            self.assertEqual(agent_inbox.pending_tasks(path=path), [])

    def test_wecom_action_message_enqueues(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            original = agent_inbox.inbox_path
            try:
                agent_inbox.inbox_path = lambda: Path(temp_dir) / "inbox.json"
                answer = agent_wecom.answer_or_enqueue("刷新状态", sender="summer", status={"answers": []})
                self.assertIn("已加入 Mac mini 队列", answer)
                self.assertEqual(agent_inbox.pending_tasks(path=Path(temp_dir) / "inbox.json")[0]["intent"], "refresh_status")
            finally:
                agent_inbox.inbox_path = original

    def test_worker_processes_pending_task(self) -> None:
        calls = []
        original_request_json = agent_inbox_worker.request_json
        original_run = agent_inbox_worker.run_agent_command
        try:
            def fake_request(base_url, path, token, *, method="GET", payload=None, timeout=20):
                calls.append((path, method, payload))
                if path.startswith("/agent-wecom/inbox/pending"):
                    return {"items": [{"id": "t1", "text": "刷新状态", "intent": "refresh_status", "execute": True}]}
                if path == "/agent-wecom/inbox/claim":
                    return {"item": {"id": "t1", "text": "刷新状态", "intent": "refresh_status", "execute": True}}
                if path == "/agent-wecom/inbox/complete":
                    return {"item": {"id": "t1", "status": payload["status"]}}
                raise AssertionError(path)

            agent_inbox_worker.request_json = fake_request
            agent_inbox_worker.run_agent_command = lambda text, execute: {"returncode": 0, "output_tail": "ok"}

            result = agent_inbox_worker.process_once("http://example.invalid", "token", 3)

            self.assertTrue(result["ok"])
            self.assertEqual(result["processed"][0]["status"], "success")
            self.assertTrue(any(call[0] == "/agent-wecom/inbox/complete" for call in calls))
        finally:
            agent_inbox_worker.request_json = original_request_json
            agent_inbox_worker.run_agent_command = original_run

    def test_nginx_exposes_inbox_without_auth_request(self) -> None:
        text = (ROOT / "inventory-board" / "deploy" / "nginx.conf").read_text(encoding="utf-8")
        block = text.split("location /agent-wecom/inbox/", 1)[1].split("location", 1)[0]

        self.assertIn("proxy_pass http://127.0.0.1:8000", block)
        self.assertNotIn("auth_request", block)


if __name__ == "__main__":
    unittest.main()
