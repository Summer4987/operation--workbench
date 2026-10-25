from __future__ import annotations

import json
import sys
import tempfile
import unittest
from unittest import mock
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import hermes_schedule_status as schedule_module  # noqa: E402


class HermesScheduleStatusTests(unittest.TestCase):
    def test_dedicated_cainiao_ledger_overrides_old_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main = root / "main.json"
            dedicated = root / "cainiao.json"
            def payload(at, status):
                return {"tasks": {"ops.cainiao_logistics": {
                    "finished_at": at, "status": status, "message": "菜鸟物流采集完成。",
                }}}
            main.write_text(json.dumps(payload("2026-07-03 10:53:20", "success")))
            dedicated.write_text(json.dumps(payload("2026-10-25 17:00:59", "success")))
            with mock.patch.multiple(schedule_module, RUNS_PATH=main,
                                     CLEAN_RUNS_PATH=root / "missing.json", CAINIAO_RUNS_PATH=dedicated):
                runs, _ = schedule_module.load_task_runs()
            row = schedule_module.classify_row({
                "label": "com.summer.operation.cainiao-logistics",
                "plist": {"StartCalendarInterval": {"Hour": 17, "Minute": 0}},
            }, runs, {}, datetime(2026, 10, 25, 17, 30))
            self.assertEqual(row["status"], "success")
            self.assertEqual(row["last_at"], "2026-10-25 17:00:59")

    def test_log_warning_uses_log_time_instead_of_old_ledger_time(self) -> None:
        with mock.patch.object(schedule_module, "newest_log_time", return_value=(
            datetime(2026, 10, 25, 17, 1), "/tmp/today.log"
        )):
            row = schedule_module.classify_row({
                "label": "com.summer.operation.cainiao-logistics",
                "plist": {"StartCalendarInterval": {"Hour": 17, "Minute": 0}},
            }, {"tasks": {"ops.cainiao_logistics": {
                "finished_at": "2026-07-03 10:53:20", "status": "success",
            }}}, {}, datetime(2026, 10, 25, 17, 30))
        self.assertEqual(row["status"], "warning")
        self.assertEqual(row["last_at"], "2026-10-25 17:01:00")
        self.assertIn("结果未确认", row["reason"])

    def test_inventory_warning_reads_business_ledger(self) -> None:
        for status in ("success", "failed"):
            with self.subTest(status=status):
                row = schedule_module.classify_row(
                    {"label": "com.summer.operation.inventory-warning-daily",
                     "plist": {"StartCalendarInterval": {"Hour": 16, "Minute": 0}}},
                    {"tasks": {"ops.inventory_warning_daily": {
                        "status": status, "message": "业务结果",
                        "finished_at": "2026-10-21 16:00:05",
                    }}}, {}, datetime(2026, 10, 21, 17, 0),
                )
                self.assertEqual(row["status"], status)
                self.assertEqual(row["name"], "每日库存预警")
                self.assertEqual(row["reason"], "业务结果")

    def setUp(self) -> None:
        self.original_runs_path = schedule_module.RUNS_PATH
        self.original_clean_runs_path = schedule_module.CLEAN_RUNS_PATH

    def tearDown(self) -> None:
        schedule_module.RUNS_PATH = self.original_runs_path
        schedule_module.CLEAN_RUNS_PATH = self.original_clean_runs_path

    def write_runs(self, path: Path, finished_at: str, message: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "tasks": {
                        "growth.promo_budget": {
                            "task_id": "growth.promo_budget",
                            "status": "success",
                            "message": message,
                            "step": "晚餐预算汇总",
                            "finished_at": finished_at,
                        }
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def test_evening_budget_uses_latest_clean_task_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clean_runs = root / "clean" / "latest.json"
            current_runs = root / "current" / "latest.json"
            self.write_runs(clean_runs, "2026-07-01 16:36:26", "晚餐预算全部步骤完成。")

            schedule_module.CLEAN_RUNS_PATH = clean_runs
            schedule_module.RUNS_PATH = current_runs

            runs, source_path = schedule_module.load_task_runs()
            self.assertEqual(source_path, clean_runs)

            row = schedule_module.classify_row(
                {
                    "label": "com.summer.operation.evening",
                    "plist": {"StartCalendarInterval": {"Hour": 16, "Minute": 30}},
                    "path": str(root / "com.summer.operation.evening.plist"),
                },
                runs,
                {},
                datetime(2026, 7, 1, 16, 56, 0),
            )

            self.assertEqual(row["status"], "success")
            self.assertEqual(row["last_at"], "2026-07-01 16:36:26")
            self.assertIn("晚餐预算全部步骤完成", row["reason"])

    def test_repeated_task_success_before_latest_due_is_missing(self) -> None:
        row = schedule_module.classify_row(
            {
                "label": "com.summer.operation.realtime-order-income",
                "plist": {
                    "StartCalendarInterval": [
                        {"Hour": 12, "Minute": 30},
                        {"Hour": 13, "Minute": 0},
                    ]
                },
                "path": "/tmp/com.summer.operation.realtime-order-income.plist",
            },
            {
                "tasks": {
                    "ops.realtime_order_income": {
                        "status": "success",
                        "message": "实时单量收入采集完成。",
                        "finished_at": "2026-08-10 12:31:18",
                    }
                }
            },
            {},
            datetime(2026, 8, 10, 13, 30, 0),
        )

        self.assertEqual(row["status"], "missing")
        self.assertIn("早于最近计划时间 13:00", row["reason"])
        self.assertEqual(row["latest_due_at"], "2026-08-10 13:00:00")

    def test_latest_issue_prefers_recent_due_time_for_missing_rows(self) -> None:
        payload = {
            "tasks": [
                {
                    "name": "AI 业务中心守护检查",
                    "status": "missing",
                    "last_at": "2026-06-13 10:25:01",
                    "latest_due_at": "2026-08-10 10:25:00",
                },
                {
                    "name": "晚间预算任务",
                    "status": "missing",
                    "last_at": "2026-08-09 17:18:27",
                    "latest_due_at": "2026-08-10 16:30:00",
                },
            ]
        }

        issue = schedule_module.latest_issue(payload)

        self.assertIsNotNone(issue)
        self.assertEqual(issue["name"], "晚间预算任务")


if __name__ == "__main__":
    unittest.main()
