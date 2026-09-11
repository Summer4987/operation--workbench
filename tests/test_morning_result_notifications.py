import contextlib
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("morning_notifications_test", ROOT / "morning-ops/run_morning_ops.py")
ops = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ops
spec.loader.exec_module(ops)


class MorningResultNotificationsTests(unittest.TestCase):
    def run_flow(self, mode, fail=False):
        events = []
        result = SimpleNamespace(returncode=0, output="", log_path=Path("test.log"))
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(sys, "argv", ["test", "--mode", mode]))
            stack.enter_context(patch.object(ops, "morning_ops_lock", return_value=contextlib.nullcontext()))
            for name in ("cleanup_chrome_sessions", "refresh_final_status", "ensure_backend_chrome"):
                stack.enter_context(patch.object(ops, name))
            stack.enter_context(patch.object(ops, "run_step", side_effect=RuntimeError("preflight failed") if fail else None, return_value=result))
            stack.enter_context(patch.object(ops, "run_step_with_pause", return_value=result))
            stack.enter_context(patch.object(ops, "record_task_run", side_effect=lambda status, *a, **k: events.append(status)))
            stack.enter_context(patch.object(ops, "publish_budget_result", side_effect=lambda *a: events.append("budget") or True))
            stack.enter_context(patch.object(ops, "flush_result_notifications", side_effect=lambda *a: events.append("notify")))
            code = ops.main()
        return code, events

    def test_success_records_budget_and_delivers_final_success(self):
        code, events = self.run_flow("commit")
        self.assertEqual(code, 0)
        self.assertEqual(events.count("budget"), 1)
        self.assertEqual(events[-2:], ["success", "notify"])

    def test_early_failure_still_records_budget_and_delivers_failure(self):
        code, events = self.run_flow("commit", fail=True)
        self.assertEqual(code, 1)
        self.assertEqual(events[-3:], ["failed", "budget", "notify"])

    def test_preview_does_not_record_real_budget_or_send(self):
        code, events = self.run_flow("preview")
        self.assertEqual(code, 0)
        self.assertNotIn("budget", events)
        self.assertNotIn("notify", events)

    def test_installer_preserves_pending_notifications(self):
        text = (ROOT / "scripts/install_agent_task_notifier_launchd.zsh").read_text()
        self.assertNotIn("agent_task_notifier.py --seed", text)
        self.assertIn("StartCalendarInterval", text)
        for minute in range(60):
            self.assertIn(f"<key>Minute</key><integer>{minute}</integer>", text)
