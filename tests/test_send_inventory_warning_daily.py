from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import send_inventory_warning_daily as sender


class InventoryWarningDailyTests(unittest.TestCase):
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
