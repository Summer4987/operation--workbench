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

    def test_success_without_completed_steps_is_not_success(self) -> None:
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
                            }
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

        self.assertEqual(payload["status"], "partial")
        self.assertIn("不能判定", payload["message"])

    def test_failed_task_without_events_uses_wrapper_failure_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_runs = root / "outputs" / "task_runs" / "latest.json"
            task_runs.parent.mkdir(parents=True)
            task_runs.write_text(
                json.dumps(
                    {
                        "tasks": {
                            "ops.morning_collection": {
                                "status": "failed",
                                "message": "上午运营一键采集异常结束，退出码：1。",
                                "step": "launchd 包装器",
                                "log_path": "/tmp/morning.log",
                                "returncode": 1,
                                "failure_type": "execution_failed",
                                "updated_at": "2026-07-03 08:22:43",
                                "extra": {
                                    "failures": "双平台评价、饿了么午餐预算",
                                },
                            }
                        },
                        "events": [],
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

        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["summary"]["failed_count"], 2)
        self.assertEqual(
            {step["name"] for step in payload["failed_steps"]},
            {"双平台评价", "饿了么午餐预算"},
        )

    def test_failed_task_uses_structured_failure_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_runs = root / "outputs" / "task_runs" / "latest.json"
            task_runs.parent.mkdir(parents=True)
            task_runs.write_text(
                json.dumps(
                    {
                        "tasks": {
                            "ops.morning_collection": {
                                "status": "failed",
                                "message": "上午运营一键采集完成，但有失败项：直营美团日报。",
                                "step": "汇总",
                                "log_path": "/tmp/morning.log",
                                "returncode": 1,
                                "updated_at": "2026-07-05 08:29:49",
                                "extra": {
                                    "failures": "直营美团日报",
                                    "failure_details": json.dumps(
                                        [
                                            {
                                                "name": "直营美团日报",
                                                "step": "直营美团日报下载",
                                                "returncode": 1,
                                                "failure_type": "auth_block",
                                                "message": "直营美团日报下载失败，退出码 1。",
                                                "output_tail": "直营美团日报下载失败：direct_chaoyangmen: 请确认日常 Chrome 已登录。",
                                                "log_path": "/tmp/morning.log",
                                            }
                                        ],
                                        ensure_ascii=False,
                                    ),
                                },
                            }
                        },
                        "events": [],
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

        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["summary"]["failed_count"], 1)
        step = payload["failed_steps"][0]
        self.assertEqual(step["name"], "直营美团日报")
        self.assertEqual(step["failure_type"], "auth_block")
        self.assertIn("请确认日常 Chrome 已登录", step["message"])

    def test_summary_failure_is_replaced_by_named_historical_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_runs = root / "outputs" / "task_runs" / "latest.json"
            task_runs.parent.mkdir(parents=True)
            task_runs.write_text(
                json.dumps(
                    {
                        "tasks": {
                            "ops.morning_collection": {
                                "status": "failed",
                                "message": "上午运营一键采集异常结束，退出码：1。",
                                "step": "汇总",
                                "log_path": "/tmp/morning.log",
                                "returncode": 1,
                                "updated_at": "2026-07-05 08:29:49",
                                "extra": {
                                    "failures": "直营美团日报",
                                },
                            }
                        },
                        "events": [
                            {
                                "task_id": "ops.morning_collection",
                                "status": "running",
                                "message": "上午运营一键采集开始。",
                                "step": "初始化",
                                "created_at": "2026-07-05 08:00:00",
                            },
                            {
                                "task_id": "ops.morning_collection",
                                "status": "success",
                                "message": "运营总看板发布腾讯云完成。",
                                "step": "运营总看板发布腾讯云",
                                "created_at": "2026-07-05 08:28:00",
                            },
                            {
                                "task_id": "ops.morning_collection",
                                "status": "failed",
                                "message": "上午运营一键采集异常结束，退出码：1。",
                                "step": "汇总",
                                "returncode": 1,
                                "created_at": "2026-07-05 08:29:49",
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

        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["summary"]["completed_count"], 1)
        self.assertEqual(payload["summary"]["failed_count"], 1)
        step = payload["failed_steps"][0]
        self.assertEqual(step["name"], "直营美团日报")
        self.assertIn("历史记录未保存该子步骤输出", step["message"])

    def test_successful_repair_closes_previous_failed_step(self) -> None:
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
                                "message": "上午运营一键采集失败项已修复：五一广场美团午餐预算已单项补正为70元。",
                                "step": "美团午餐预算单项修复",
                                "returncode": 0,
                                "updated_at": "2026-07-09 09:42:58",
                            }
                        },
                        "events": [
                            {
                                "task_id": "ops.morning_collection",
                                "status": "running",
                                "message": "上午运营一键采集开始。",
                                "step": "初始化",
                                "created_at": "2026-07-09 08:00:00",
                            },
                            {
                                "task_id": "ops.morning_collection",
                                "status": "failed",
                                "message": "美团午餐预算真实提交失败，退出码 1。",
                                "step": "美团午餐预算",
                                "returncode": 1,
                                "created_at": "2026-07-09 08:31:18",
                            },
                            {
                                "task_id": "ops.morning_collection",
                                "status": "success",
                                "message": "五一广场美团午餐预算已单项补正为70元。",
                                "step": "美团午餐预算单项修复",
                                "returncode": 0,
                                "created_at": "2026-07-09 09:42:58",
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
        self.assertEqual(payload["summary"]["failed_count"], 0)
        self.assertEqual(len(payload["resolved_failed_steps"]), 1)
        self.assertIn("失败项已修复", payload["message"])


if __name__ == "__main__":
    unittest.main()
