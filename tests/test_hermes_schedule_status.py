from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import hermes_schedule_status as schedule_module  # noqa: E402


class HermesScheduleStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_runs_path = schedule_module.RUNS_PATH
        self.original_production_runs_path = schedule_module.PRODUCTION_RUNS_PATH
        self.original_clean_runs_path = schedule_module.CLEAN_RUNS_PATH

    def tearDown(self) -> None:
        schedule_module.RUNS_PATH = self.original_runs_path
        schedule_module.PRODUCTION_RUNS_PATH = self.original_production_runs_path
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
            production_runs = root / "production" / "latest.json"
            clean_runs = root / "clean" / "latest.json"
            current_runs = root / "current" / "latest.json"
            self.write_runs(production_runs, "2026-06-30 17:09:58", "昨天晚餐预算完成。")
            self.write_runs(clean_runs, "2026-07-01 16:36:26", "晚餐预算全部步骤完成。")

            schedule_module.PRODUCTION_RUNS_PATH = production_runs
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


if __name__ == "__main__":
    unittest.main()
