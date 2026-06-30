from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_task_health as health_module  # noqa: E402


class BuildTaskHealthTests(unittest.TestCase):
    def test_success_run_does_not_hide_realtime_publish_issue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir(parents=True)
            (root / "outputs" / "realtime_order_income").mkdir(parents=True)
            (root / "outputs" / "realtime_order_income_status").mkdir(parents=True)
            (root / "outputs" / "task_runs").mkdir(parents=True)
            (root / "outputs" / "realtime_order_income" / "logs").mkdir(parents=True)

            (root / "config" / "ai_business_center_tasks.json").write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "id": "ops.realtime_order_income",
                                "name": "实时单量和营业额采集",
                                "center": "加盟店运营数据中心",
                                "module": "加盟店实时数据看板",
                                "status": "running",
                                "risk": "low",
                                "schedule": "10:30-20:00",
                                "outputs": ["outputs/realtime_order_income/latest.json"],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (root / "outputs" / "realtime_order_income" / "latest.json").write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "generated_at": "2026-06-30 20:00:56",
                        "summary": {"platform_store_count": 16, "missing_count": 0},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (root / "outputs" / "realtime_order_income_status" / "latest.json").write_text(
                json.dumps({"status": "ok", "last_success_at": "2026-06-30 20:00:56", "summary": {}}, ensure_ascii=False),
                encoding="utf-8",
            )
            (root / "outputs" / "task_runs" / "latest.json").write_text(
                json.dumps(
                    {
                        "tasks": {
                            "ops.realtime_order_income": {
                                "status": "success",
                                "message": "实时单量收入采集完成。",
                                "updated_at": "2026-06-30 20:01:15",
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (root / "outputs" / "realtime_order_income" / "logs" / "2026-06-30.log").write_text(
                "rsync(97123): error: workbench-data.js: open (2) in (null): Operation not permitted\n",
                encoding="utf-8",
            )

            original_values = (
                health_module.ROOT,
                health_module.TASKS_PATH,
                health_module.TASK_RUNS_PATH,
                health_module.REALTIME_COLLECTION_STATUS_PATH,
            )
            try:
                health_module.ROOT = root
                health_module.TASKS_PATH = root / "config" / "ai_business_center_tasks.json"
                health_module.TASK_RUNS_PATH = root / "outputs" / "task_runs" / "latest.json"
                health_module.REALTIME_COLLECTION_STATUS_PATH = root / "outputs" / "realtime_order_income_status" / "latest.json"

                payload = health_module.build_task_health(now=datetime(2026, 6, 30, 20, 31), runtime={"inventory": {}})
            finally:
                (
                    health_module.ROOT,
                    health_module.TASKS_PATH,
                    health_module.TASK_RUNS_PATH,
                    health_module.REALTIME_COLLECTION_STATUS_PATH,
                ) = original_values

        task = payload["tasks"][0]
        self.assertEqual(task["status"], "warn")
        self.assertIn("云端发布权限错误", task["reason"])


if __name__ == "__main__":
    unittest.main()
