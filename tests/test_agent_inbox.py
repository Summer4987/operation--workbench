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

    def test_budget_preview_wording_enqueues_preview_only(self) -> None:
        policy = agent_inbox.command_policy("生成预算预览")

        self.assertTrue(policy["enqueue"])
        self.assertEqual(policy["intent"], "budget_preview")
        self.assertEqual(policy["reason"], "budget-preview-only")

    def test_ordering_policy_is_blocked(self) -> None:
        policy = agent_inbox.command_policy("帮我补跑订货")

        self.assertFalse(policy["enqueue"])
        self.assertEqual(policy["intent"], "blocked_ordering")

    def test_execute_rerun_policy_enqueues_safe_rerun(self) -> None:
        policy = agent_inbox.command_policy("执行补跑")

        self.assertTrue(policy["enqueue"])
        self.assertEqual(policy["intent"], "rerun_plan")
        self.assertTrue(policy["execute"])

    def test_meituan_remaining_policy_enqueues_readonly_inspection(self) -> None:
        policy = agent_inbox.command_policy("一键查询美团余量")

        self.assertTrue(policy["enqueue"])
        self.assertEqual(policy["intent"], "meituan_spend_inspection")
        self.assertTrue(policy["execute"])

    def test_system_check_policy_enqueues(self) -> None:
        policy = agent_inbox.command_policy("系统自检")

        self.assertTrue(policy["enqueue"])
        self.assertEqual(policy["intent"], "system_check")
        self.assertTrue(policy["execute"])

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

    def test_inbox_can_mark_task_canceled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "inbox.json"
            item = agent_inbox.append_task(text="生成预算预览", intent="budget_preview", execute=True, source="test", path=path)
            updated = agent_inbox.complete_task(item["id"], status="canceled", result={"returncode": 130}, path=path)
            summary = agent_inbox.task_summary(path=path)

            self.assertEqual(updated["status"], "canceled")
            self.assertEqual(summary["canceled"], 1)

    def test_success_recovers_older_failed_same_intent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "inbox.json"
            failed = agent_inbox.append_task(
                text="巡检美团实时消耗",
                intent="meituan_spend_inspection",
                execute=True,
                source="test",
                path=path,
            )
            agent_inbox.complete_task(failed["id"], status="failed", result={"returncode": 1}, path=path)
            success = agent_inbox.append_task(
                text="巡检美团实时消耗",
                intent="meituan_spend_inspection",
                execute=True,
                source="test",
                path=path,
            )
            agent_inbox.complete_task(success["id"], status="success", result={"returncode": 0}, path=path)

            summary = agent_inbox.task_summary(path=path)
            recent = agent_inbox.recent_tasks(limit=2, path=path)

            self.assertEqual(summary["failed"], 0)
            self.assertEqual(summary["recovered"], 1)
            self.assertEqual(recent[1]["status"], "recovered")
            self.assertEqual(recent[1]["recovered_by"], success["id"])

    def test_recent_tasks_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "inbox.json"
            first = agent_inbox.append_task(text="任务正常吗", intent="", execute=False, source="test", path=path)
            second = agent_inbox.append_task(text="刷新状态", intent="refresh_status", execute=True, source="test", path=path)
            agent_inbox.claim_task(second["id"], worker="macmini", path=path)
            agent_inbox.complete_task(second["id"], status="success", result={"returncode": 0}, path=path)

            recent = agent_inbox.recent_tasks(limit=2, path=path)
            summary = agent_inbox.task_summary(path=path)

            self.assertEqual([item["id"] for item in recent], [second["id"], first["id"]])
            self.assertEqual(summary["pending"], 1)
            self.assertEqual(summary["success"], 1)
            self.assertEqual(summary["total"], 2)

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

    def test_wecom_meituan_remaining_message_enqueues(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            original = agent_inbox.inbox_path
            try:
                agent_inbox.inbox_path = lambda: Path(temp_dir) / "inbox.json"
                answer = agent_wecom.answer_or_enqueue("查询美团余量", sender="summer", status={"answers": []})
                item = agent_inbox.pending_tasks(path=Path(temp_dir) / "inbox.json")[0]

                self.assertIn("已加入 Mac mini 队列", answer)
                self.assertEqual(item["intent"], "meituan_spend_inspection")
                self.assertTrue(item["execute"])
            finally:
                agent_inbox.inbox_path = original

    def test_worker_processes_pending_task(self) -> None:
        calls = []
        notices = []
        original_request_json = agent_inbox_worker.request_json
        original_run = agent_inbox_worker.run_agent_command
        original_notify = agent_inbox_worker.agent_notify.notify_message
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
            agent_inbox_worker.run_agent_command = lambda text, execute: {
                "returncode": 0,
                "output_tail": "ok",
                "command_payload": {"intent": "refresh_status", "answer": "已刷新 agent 状态。"},
            }
            agent_inbox_worker.agent_notify.notify_message = lambda message, dry_run=False: notices.append(message) or (True, "sent")

            result = agent_inbox_worker.process_once("http://example.invalid", "token", 3)

            self.assertTrue(result["ok"])
            self.assertEqual(result["processed"][0]["status"], "success")
            self.assertTrue(any(call[0] == "/agent-wecom/inbox/complete" for call in calls))
            self.assertEqual(len(notices), 1)
            self.assertIn("企微队列 t1", notices[0])
            complete_payload = [call[2] for call in calls if call[0] == "/agent-wecom/inbox/complete"][0]
            self.assertTrue(complete_payload["result"]["queue_notification"]["delivered"])
        finally:
            agent_inbox_worker.request_json = original_request_json
            agent_inbox_worker.run_agent_command = original_run
            agent_inbox_worker.agent_notify.notify_message = original_notify

    def test_worker_runs_agent_command_without_nested_notify(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            original_latest = agent_inbox_worker.LAST_COMMAND_PATH
            original_run = agent_inbox_worker.subprocess.run
            try:
                agent_inbox_worker.LAST_COMMAND_PATH = Path(temp_dir) / "last_command.json"

                def fake_run(command, **kwargs):
                    agent_inbox_worker.LAST_COMMAND_PATH.write_text(
                        '{"intent":"status","answer":"状态正常"}',
                        encoding="utf-8",
                    )

                    class Result:
                        returncode = 0
                        stdout = "状态正常"

                    self.assertNotIn("--notify", command)
                    return Result()

                agent_inbox_worker.subprocess.run = fake_run
                result = agent_inbox_worker.run_agent_command("任务正常吗", execute=False)

                self.assertEqual(result["returncode"], 0)
                self.assertEqual(result["command_payload"]["answer"], "状态正常")
            finally:
                agent_inbox_worker.LAST_COMMAND_PATH = original_latest
                agent_inbox_worker.subprocess.run = original_run

    def test_worker_marks_partial_meituan_inspection_as_warning_notice(self) -> None:
        notice_status, action = agent_inbox_worker.infer_business_notice(
            "success",
            {"intent": "meituan_spend_inspection"},
            "美团推广实时消耗巡检：总览：已读到 4/13 家，今日消耗 110.77 元，当前预算 380 元；正常 4，预警 0，异常 0，未核实 9。",
        )

        self.assertEqual(notice_status, "warning")
        self.assertIn("未核实", action)

    def test_worker_marks_meituan_warning_count_as_warning_notice(self) -> None:
        notice_status, action = agent_inbox_worker.infer_business_notice(
            "success",
            {"intent": "meituan_spend_inspection"},
            "美团推广实时消耗巡检：总览：已读到 13/13 家，今日消耗 0 元；正常 12，预警 1，异常 0，未核实 0。",
        )

        self.assertEqual(notice_status, "warning")
        self.assertIn("预警", action)

    def test_worker_sends_start_notice_for_meituan_inspection(self) -> None:
        notices = []
        original_notify = agent_inbox_worker.agent_notify.notify_message
        try:
            agent_inbox_worker.agent_notify.notify_message = lambda message, dry_run=False: notices.append(message) or (True, "sent")
            result = agent_inbox_worker.notify_task_started(
                {"id": "abcdef123456", "text": "巡检美团实时消耗", "intent": "meituan_spend_inspection"}
            )

            self.assertIsNotNone(result)
            self.assertTrue(result["delivered"])
            self.assertIn("已开始读取美团推广实时消耗", notices[0])
            self.assertIn("3-6 分钟", notices[0])
        finally:
            agent_inbox_worker.agent_notify.notify_message = original_notify

    def test_nginx_exposes_inbox_without_auth_request(self) -> None:
        text = (ROOT / "inventory-board" / "deploy" / "nginx.conf").read_text(encoding="utf-8")
        block = text.split("location /agent-wecom/inbox/", 1)[1].split("location", 1)[0]

        self.assertIn("proxy_pass http://127.0.0.1:8000", block)
        self.assertNotIn("auth_request", block)

    def test_nginx_exposes_mobile_agent_without_auth_request(self) -> None:
        text = (ROOT / "inventory-board" / "deploy" / "nginx.conf").read_text(encoding="utf-8")
        page_block = text.split("location = /agent", 1)[1].split("location", 1)[0]
        api_block = text.split("location /agent/api/", 1)[1].split("location", 1)[0]

        self.assertIn("proxy_pass http://127.0.0.1:8000", page_block)
        self.assertIn("proxy_pass http://127.0.0.1:8000", api_block)
        self.assertNotIn("auth_request", page_block)
        self.assertNotIn("auth_request", api_block)

    def test_mobile_agent_page_keeps_chat_area_clickable(self) -> None:
        text = (ROOT / "inventory-board" / "app" / "main.py").read_text(encoding="utf-8")

        self.assertIn("AGENT_PAGE_VERSION", text)
        self.assertIn("xiongAgentPageVersion", text)
        self.assertIn("seedMobileAnswer(payload.mobile || {})", text)
        self.assertIn("grid-template-rows: auto auto auto auto minmax(0, 1fr) auto auto", text)
        self.assertIn("height: 100dvh", text)
        self.assertIn("function loadStoredMessages()", text)
        self.assertIn("localStorage.removeItem(\"xiongAgentMessages\")", text)
        self.assertIn("min-height: 0", text)
        self.assertIn('canceled:"已取消"', text)

    def test_mobile_agent_api_returns_mobile_status_and_recent_queue_only(self) -> None:
        text = (ROOT / "inventory-board" / "app" / "main.py").read_text(encoding="utf-8")

        self.assertIn('"mobile": _agent_mobile_status_payload()', text)
        self.assertIn("AGENT_RECENT_TASK_MAX_AGE_SECONDS", text)
        self.assertIn("_agent_recent_visible_tasks", text)
        self.assertIn('"queue_summary": agent_inbox.task_summary()', text)

    def test_mobile_agent_page_has_meituan_remaining_button(self) -> None:
        text = (ROOT / "inventory-board" / "app" / "main.py").read_text(encoding="utf-8")

        self.assertIn('data-command="巡检美团实时消耗"', text)
        self.assertIn("一键查余量", text)

    def test_mobile_agent_page_omits_maintenance_buttons_without_one_off_acceptance(self) -> None:
        text = (ROOT / "inventory-board" / "app" / "main.py").read_text(encoding="utf-8")

        self.assertNotIn('data-command="系统自检"', text)
        self.assertNotIn('data-command="刷新状态"', text)
        self.assertNotIn('data-command="验收望京同步"', text)
        self.assertNotIn("验收望京", text)

    def test_mobile_agent_page_omits_budget_preview_button(self) -> None:
        text = (ROOT / "inventory-board" / "app" / "main.py").read_text(encoding="utf-8")

        self.assertNotIn('data-command="生成预算预览"', text)
        self.assertNotIn('data-command="重跑预算设置"', text)
        self.assertNotIn(">预算预览</button>", text)


if __name__ == "__main__":
    unittest.main()
