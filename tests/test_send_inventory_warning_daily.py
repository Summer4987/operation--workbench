from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import send_inventory_warning_daily as sender


class InventoryWarningDailyTests(unittest.TestCase):
    def test_cli_records_business_results_and_failures(self) -> None:
        cases = [
            ({"status": "sent", "message": "已推送3项预警"}, "success", 0),
            ({"status": "clear", "message": "无需预警"}, "success", 0),
            ({"status": "skipped", "message": "今日已完成"}, "success", 0),
            ({"status": "error", "message": "发送失败"}, "failed", 1),
            (RuntimeError("连接超时"), "failed", 1),
        ]
        for result, status, code in cases:
            with self.subTest(result=result), mock.patch("sys.argv", ["sender"]), mock.patch.object(
                sender, "record_task_event"
            ) as record, mock.patch.object(sender, "run") as run:
                if isinstance(result, Exception):
                    run.side_effect = result
                else:
                    run.return_value = result
                self.assertEqual(sender.main(), code)
                self.assertEqual(record.call_args_list[0].args, (sender.TASK_ID, "running"))
                self.assertEqual(record.call_args.args, (sender.TASK_ID, status))
                self.assertEqual(record.call_args.kwargs["returncode"], code)
                if isinstance(result, Exception):
                    self.assertEqual(record.call_args.kwargs["failure_type"], "timeout")

    def test_daily_sender_deduplicates_completed_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.object(sender, "STATE_PATH", root / "state.json"), mock.patch.object(
                sender, "LATEST_PATH", root / "latest.json"
            ), mock.patch.object(sender, "load_token", return_value="token"), mock.patch.object(
                sender, "trigger", return_value={"status": "sent", "warning_count": 3, "message": "ok"}
            ) as trigger:
                first = sender.run(base_url="http://example.invalid", today="2026-08-05")
                second = sender.run(base_url="http://example.invalid", today="2026-08-05")

            self.assertEqual(first["status"], "sent")
            self.assertEqual(second["status"], "skipped")
            self.assertEqual(trigger.call_count, 1)

    def test_clear_result_is_also_completed_for_the_day(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.object(sender, "STATE_PATH", root / "state.json"), mock.patch.object(
                sender, "LATEST_PATH", root / "latest.json"
            ), mock.patch.object(sender, "load_token", return_value="token"), mock.patch.object(
                sender, "trigger", return_value={"status": "clear", "warning_count": 0, "message": "clear"}
            ) as trigger:
                sender.run(base_url="http://example.invalid", today="2026-08-05")
                second = sender.run(base_url="http://example.invalid", today="2026-08-05")

            self.assertEqual(second["status"], "skipped")
            self.assertEqual(trigger.call_count, 1)


if __name__ == "__main__":
    unittest.main()
