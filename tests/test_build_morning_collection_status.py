from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_morning_collection_status as morning_module  # noqa: E402


class BuildMorningCollectionStatusTests(unittest.TestCase):
    def test_safe_tail_rerun_does_not_hide_morning_steps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_runs = root / "outputs" / "task_runs" / "latest.json"
            task_runs.parent.mkdir(parents=True)
            task_runs.write_text(
                json.dumps(
                    {
                        "tasks": {
                            "ops.morning_collection": {
                                "status": "success",
                                "message": "收尾补跑完成。",
                                "step": "收尾补跑",
                                "updated_at": "2026-07-01 10:22:25",
                            }
                        },
                        "events": [
                            {
                                "task_id": "ops.morning_collection",
                                "status": "running",
                                "message": "上午运营一键采集开始。",
                                "step": "初始化",
                                "created_at": "2026-07-01 08:00:05",
                            },
                            {
                                "task_id": "ops.morning_collection",
                                "status": "success",
                                "message": "双平台评价下载完成。",
                                "step": "双平台评价下载",
                                "created_at": "2026-07-01 08:01:00",
                            },
                            {
                                "task_id": "ops.morning_collection",
                                "status": "success",
                                "message": "推广余额总巡检完成。",
                                "step": "推广余额总巡检",
                                "created_at": "2026-07-01 08:10:00",
                            },
                            {
                                "task_id": "ops.morning_collection",
                                "status": "success",
                                "message": "收尾补跑完成。",
                                "step": "收尾补跑",
                                "created_at": "2026-07-01 10:22:25",
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            original = morning_module.TASK_RUNS_PATH
            try:
                morning_module.TASK_RUNS_PATH = task_runs
                payload = morning_module.build_payload()
            finally:
                morning_module.TASK_RUNS_PATH = original

        self.assertEqual(payload["status"], "success")
        self.assertGreaterEqual(payload["summary"]["completed_count"], 2)
        self.assertIn("双平台评价下载", {step["name"] for step in payload["steps"]})
        self.assertIn("推广余额总巡检", {step["name"] for step in payload["steps"]})


if __name__ == "__main__":
    unittest.main()
