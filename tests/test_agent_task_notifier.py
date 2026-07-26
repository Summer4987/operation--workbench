#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "agent_task_notifier.py"


def load_notifier():
    scripts_dir = str(SCRIPT_PATH.parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("agent_task_notifier_for_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class AgentTaskNotifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.notifier = load_notifier()

    def setUp(self) -> None:
        self.original_schedule_loader = self.notifier.load_schedule_issue_tasks
        self.notifier.load_schedule_issue_tasks = lambda: {}

    def tearDown(self) -> None:
        self.notifier.load_schedule_issue_tasks = self.original_schedule_loader

    def test_build_failure_message_includes_reason_and_log(self) -> None:
        message = self.notifier.build_message(
            "ops.example",
            {
                "status": "failed",
                "message": "页面结构变化",
                "step": "采集",
                "log_path": "/tmp/example.log",
                "failure_type": "page_structure",
                "finished_at": "2026-06-30 17:00:00",
            },
            {"name": "示例任务", "rerun": {"suggested": True, "auto_allowed": False, "reason": "只报告。"}},
        )

        self.assertIn("结论：示例任务未通过，需要处理。", message)
        self.assertIn("功能验收：示例任务：失败", message)
        self.assertIn("问题：页面结构变化", message)
        self.assertIn("证据 /tmp/example.log", message)
        self.assertIn("处理建议：不自动补跑，原因：只报告。", message)
        self.assertNotIn("任务 ID：", message)
        self.assertNotIn("ID task.example", message)
        self.assertNotIn("[失败]", message)

    def test_notify_deduplicates_terminal_task_signatures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            runs_path = tmp_path / "runs.json"
            state_path = tmp_path / "state.json"
            log_path = tmp_path / "log.json"
            runs_path.write_text(
                json.dumps(
                    {
                        "tasks": {
                            "ops.example": {
                                "status": "success",
                                "message": "完成",
                                "step": "汇总",
                                "finished_at": "2026-06-30 17:00:00",
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            args = type(
                "Args",
                (),
                {
                    "runs": str(runs_path),
                    "state": str(state_path),
                    "log": str(log_path),
                    "target": "weixin",
                    "hermes_bin": "hermes",
                    "seed": False,
                    "dry_run": True,
                    "no_write": False,
                    "include_unconfigured": False,
                },
            )()

            original_loader = self.notifier.load_policy_rows
            try:
                self.notifier.load_policy_rows = lambda: {
                    "ops.example": {"id": "ops.example", "name": "示例任务", "rerun": {}}
                }
                first = self.notifier.notify(args)
                second = self.notifier.notify(args)
            finally:
                self.notifier.load_policy_rows = original_loader

            self.assertEqual(first["notification_count"], 1)
            self.assertEqual(second["notification_count"], 0)

    def test_notify_ignores_health_attention_until_user_asks_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            runs_path = tmp_path / "runs.json"
            state_path = tmp_path / "state.json"
            log_path = tmp_path / "log.json"
            runs_path.write_text(
                json.dumps(
                    {
                        "tasks": {
                            "ops.realtime_order_income": {
                                "status": "success",
                                "message": "实时单量收入采集完成。",
                                "step": "发布工作台云端数据",
                                "finished_at": "2026-06-30 20:01:15",
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            state_path.write_text(
                json.dumps(
                    {
                        "sent": {
                            "ops.realtime_order_income": "success|2026-06-30 20:01:15|实时单量收入采集完成。|发布工作台云端数据"
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            args = type(
                "Args",
                (),
                {
                    "runs": str(runs_path),
                    "state": str(state_path),
                    "log": str(log_path),
                    "target": "weixin",
                    "hermes_bin": "hermes",
                    "seed": False,
                    "dry_run": True,
                    "no_write": False,
                    "include_unconfigured": False,
                },
            )()
            original_loader = self.notifier.load_policy_rows
            try:
                self.notifier.load_policy_rows = lambda: {
                    "ops.realtime_order_income": {
                        "id": "ops.realtime_order_income",
                        "name": "实时单量和营业额采集",
                        "status": "attention",
                        "failure_reason": "实时采集数据已生成，但云端发布权限错误。",
                        "last_run_at": "2026-06-30 20:01:15",
                        "last_run_step": "发布工作台云端数据",
                        "evidence": "/tmp/realtime.log",
                        "rerun": {"suggested": True, "auto_allowed": True, "command": ["/bin/zsh", "scripts/run_realtime_order_income.zsh"]},
                    }
                }

                payload = self.notifier.notify(args)
            finally:
                self.notifier.load_policy_rows = original_loader

            self.assertEqual(payload["notification_count"], 0)

    def test_notify_batches_multiple_messages_into_one_send(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            runs_path = tmp_path / "runs.json"
            state_path = tmp_path / "state.json"
            log_path = tmp_path / "log.json"
            runs_path.write_text(
                json.dumps(
                    {
                        "tasks": {
                            "ops.one": {"status": "success", "message": "完成 1", "finished_at": "2026-06-30 17:00:00"},
                            "ops.two": {"status": "failed", "message": "失败 2", "finished_at": "2026-06-30 17:01:00"},
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            args = type(
                "Args",
                (),
                {
                    "runs": str(runs_path),
                    "state": str(state_path),
                    "log": str(log_path),
                    "target": "weixin",
                    "hermes_bin": "hermes",
                    "seed": False,
                    "dry_run": False,
                    "no_write": False,
                    "include_unconfigured": False,
                },
            )()
            sent_messages: list[str] = []
            original_loader = self.notifier.load_policy_rows
            original_sender = self.notifier.send_weixin
            try:
                self.notifier.load_policy_rows = lambda: {
                    "ops.one": {"id": "ops.one", "name": "任务一", "rerun": {}},
                    "ops.two": {"id": "ops.two", "name": "任务二", "rerun": {}},
                }
                self.notifier.send_weixin = lambda message, target, hermes_bin: (sent_messages.append(message) or True, "ok")

                payload = self.notifier.notify(args)
            finally:
                self.notifier.load_policy_rows = original_loader
                self.notifier.send_weixin = original_sender

            self.assertEqual(payload["notification_count"], 2)
            self.assertEqual(len(sent_messages), 1)
            self.assertIn("我整理了 2 条 Mac mini 自动化更新：", sent_messages[0])
            self.assertIn("任务一", sent_messages[0])
            self.assertIn("任务二", sent_messages[0])
            self.assertNotIn("\n", sent_messages[0])
            self.assertNotIn("\n\n---\n\n", sent_messages[0])

    def test_notify_includes_fresh_low_balance_alert(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            runs_path = tmp_path / "runs.json"
            state_path = tmp_path / "state.json"
            log_path = tmp_path / "log.json"
            balance_path = tmp_path / "promo_balance_status.json"
            runs_path.write_text(json.dumps({"tasks": {}}, ensure_ascii=False), encoding="utf-8")
            balance_path.write_text(
                json.dumps(
                    {
                        "status": "warning",
                        "source_generated_at": "2026-07-26 08:10:00",
                        "summary": {"low_balance_count": 2, "source_is_stale": False},
                        "low_balance_items": [
                            {
                                "platform": "美团",
                                "store_name": "丽泽门店",
                                "balance": 184.58,
                                "threshold": 200,
                            },
                            {
                                "platform": "饿了么",
                                "store_name": "望京店",
                                "balance": 47.68,
                                "threshold": 200,
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            args = type(
                "Args",
                (),
                {
                    "runs": str(runs_path),
                    "state": str(state_path),
                    "log": str(log_path),
                    "target": "weixin",
                    "hermes_bin": "hermes",
                    "seed": False,
                    "dry_run": True,
                    "no_write": False,
                    "include_unconfigured": False,
                },
            )()
            original_loader = self.notifier.load_promo_balance_alert_tasks
            try:
                self.notifier.load_promo_balance_alert_tasks = lambda: original_loader(balance_path)

                payload = self.notifier.notify(args)
            finally:
                self.notifier.load_promo_balance_alert_tasks = original_loader

            self.assertEqual(payload["notification_count"], 1)
            notice = payload["notifications"][0]
            self.assertEqual(notice["task_id"], "growth.promo_balance.low_balance")
            self.assertEqual(notice["status"], "warning")
            self.assertIn("推广余额低余额预警部分通过，需要核实", notice["message"])
            self.assertIn("余额巡检发现 2 个低余额门店", notice["message"])
            self.assertIn("1. 美团 丽泽门店：余额 184.58 元", notice["message"])
            self.assertIn("2. 饿了么 望京店：余额 47.68 元", notice["message"])
            self.assertIn("先充值低余额门店", notice["message"])

    def test_notify_skips_stale_low_balance_alert(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            balance_path = tmp_path / "promo_balance_status.json"
            balance_path.write_text(
                json.dumps(
                    {
                        "status": "stale",
                        "source_generated_at": "2026-07-26 08:10:00",
                        "summary": {"low_balance_count": 2, "source_is_stale": True},
                        "low_balance_items": [
                            {"platform": "美团", "store_name": "丽泽门店", "balance": 184.58, "threshold": 200}
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            tasks = self.notifier.load_promo_balance_alert_tasks(balance_path)

            self.assertEqual(tasks, {})

    def test_send_weixin_prefers_ops_notify(self) -> None:
        original_notify_with_result = self.notifier.ops_notify.notify_with_result
        try:
            calls: list[str] = []
            self.notifier.ops_notify.notify_with_result = lambda message: (calls.append(message) and False) or (
                True,
                "wecom errcode=0 errmsg=ok",
            )

            delivered, output = self.notifier.send_weixin("测试消息", "weixin", "missing-hermes")
        finally:
            self.notifier.ops_notify.notify_with_result = original_notify_with_result

        self.assertTrue(delivered)
        self.assertEqual(output, "ops_notify: wecom errcode=0 errmsg=ok")
        self.assertEqual(calls, ["测试消息"])

    def test_send_weixin_reports_ops_notify_failure(self) -> None:
        original_notify_with_result = self.notifier.ops_notify.notify_with_result
        original_run = self.notifier.subprocess.run
        try:
            self.notifier.ops_notify.notify_with_result = lambda message: (
                False,
                "wecom errcode=93000 errmsg=invalid webhook",
            )

            class Result:
                returncode = 1
                stdout = "hermes not configured"

            self.notifier.subprocess.run = lambda *args, **kwargs: Result()
            delivered, output = self.notifier.send_weixin("测试消息", "weixin", "missing-hermes")
        finally:
            self.notifier.ops_notify.notify_with_result = original_notify_with_result
            self.notifier.subprocess.run = original_run

        self.assertFalse(delivered)
        self.assertIn("wecom errcode=93000", output)
        self.assertIn("hermes not configured", output)

    def test_notify_backs_off_when_weixin_cooldown_is_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            runs_path = tmp_path / "runs.json"
            state_path = tmp_path / "state.json"
            log_path = tmp_path / "log.json"
            runs_path.write_text(
                json.dumps(
                    {
                        "tasks": {
                            "ops.realtime_order_income": {
                                "status": "success",
                                "message": "实时单量收入采集完成。",
                                "step": "发布工作台云端数据",
                                "finished_at": "2026-07-02 10:31:17",
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            args = type(
                "Args",
                (),
                {
                    "runs": str(runs_path),
                    "state": str(state_path),
                    "log": str(log_path),
                    "target": "weixin",
                    "hermes_bin": "hermes",
                    "seed": False,
                    "dry_run": False,
                    "no_write": False,
                    "include_unconfigured": False,
                },
            )()
            calls: list[str] = []
            original_loader = self.notifier.load_policy_rows
            original_sender = self.notifier.send_weixin
            try:
                self.notifier.load_policy_rows = lambda: dict(self.notifier.DIRECT_TASK_ROWS)
                self.notifier.send_weixin = (
                    lambda message, target, hermes_bin: calls.append(message)
                    or (False, "hermes send: Weixin send failed: iLink sendmessage rate limited; cooldown active for 30.0s")
                )
                first = self.notifier.notify(args)
                second = self.notifier.notify(args)
            finally:
                self.notifier.load_policy_rows = original_loader
                self.notifier.send_weixin = original_sender

            self.assertEqual(first["notification_count"], 1)
            self.assertFalse(first["notifications"][0]["delivered"])
            self.assertGreaterEqual(first["cooldown_until"] - time.time(), 1700)
            self.assertEqual(first["consecutive_failures"], 1)
            self.assertEqual(first["sent"], {})
            self.assertTrue(second["skipped_by_cooldown"])
            self.assertEqual(len(calls), 1)

    def test_notify_uses_exponential_backoff_for_repeated_ilink_rate_limits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            runs_path = tmp_path / "runs.json"
            state_path = tmp_path / "state.json"
            log_path = tmp_path / "log.json"
            runs_path.write_text(
                json.dumps(
                    {
                        "tasks": {
                            "ops.realtime_order_income": {
                                "status": "success",
                                "message": "实时单量收入采集完成。",
                                "step": "发布工作台云端数据",
                                "finished_at": "2026-07-02 10:31:17",
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            state_path.write_text(
                json.dumps({"sent": {}, "cooldown_until": 0, "consecutive_failures": 2}, ensure_ascii=False),
                encoding="utf-8",
            )
            args = type(
                "Args",
                (),
                {
                    "runs": str(runs_path),
                    "state": str(state_path),
                    "log": str(log_path),
                    "target": "weixin",
                    "hermes_bin": "hermes",
                    "seed": False,
                    "dry_run": False,
                    "no_write": False,
                    "include_unconfigured": False,
                },
            )()
            original_loader = self.notifier.load_policy_rows
            original_sender = self.notifier.send_weixin
            try:
                self.notifier.load_policy_rows = lambda: dict(self.notifier.DIRECT_TASK_ROWS)
                self.notifier.send_weixin = (
                    lambda message, target, hermes_bin: (
                        False,
                        "hermes send: Weixin send failed: iLink sendmessage rate limited; cooldown active for 30.0s",
                    )
                )
                payload = self.notifier.notify(args)
            finally:
                self.notifier.load_policy_rows = original_loader
                self.notifier.send_weixin = original_sender

            self.assertEqual(payload["consecutive_failures"], 3)
            self.assertGreaterEqual(payload["cooldown_until"] - time.time(), 7100)

    def test_notify_includes_direct_runtime_task_success_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            runs_path = tmp_path / "runs.json"
            state_path = tmp_path / "state.json"
            log_path = tmp_path / "log.json"
            runs_path.write_text(
                json.dumps(
                    {
                        "tasks": {
                            "ops.realtime_order_income": {
                                "status": "success",
                                "message": "实时单量收入采集完成。",
                                "step": "发布工作台云端数据",
                                "finished_at": "2026-07-01 11:31:17",
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            args = type(
                "Args",
                (),
                {
                    "runs": str(runs_path),
                    "state": str(state_path),
                    "log": str(log_path),
                    "target": "weixin",
                    "hermes_bin": "hermes",
                    "seed": False,
                    "dry_run": True,
                    "no_write": False,
                    "include_unconfigured": False,
                },
            )()
            original_loader = self.notifier.load_policy_rows
            try:
                self.notifier.load_policy_rows = lambda: dict(self.notifier.DIRECT_TASK_ROWS)
                payload = self.notifier.notify(args)
            finally:
                self.notifier.load_policy_rows = original_loader

            self.assertEqual(payload["notification_count"], 1)
            self.assertIn("结论：实时单量和营业额采集通过，功能已完成。", payload["notifications"][0]["message"])
            self.assertIn("功能验收：实时单量和营业额采集：成功", payload["notifications"][0]["message"])

    def test_notify_skips_unknown_unconfigured_tasks_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            runs_path = tmp_path / "runs.json"
            state_path = tmp_path / "state.json"
            log_path = tmp_path / "log.json"
            runs_path.write_text(
                json.dumps(
                    {
                        "tasks": {
                            "unknown.task": {
                                "status": "success",
                                "message": "完成。",
                                "step": "未知任务",
                                "finished_at": "2026-07-01 11:31:17",
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            args = type(
                "Args",
                (),
                {
                    "runs": str(runs_path),
                    "state": str(state_path),
                    "log": str(log_path),
                    "target": "weixin",
                    "hermes_bin": "hermes",
                    "seed": False,
                    "dry_run": True,
                    "no_write": False,
                    "include_unconfigured": False,
                },
            )()
            original_loader = self.notifier.load_policy_rows
            try:
                self.notifier.load_policy_rows = lambda: {}
                payload = self.notifier.notify(args)
            finally:
                self.notifier.load_policy_rows = original_loader

            self.assertEqual(payload["notification_count"], 0)

    def test_notify_includes_schedule_issue_without_policy_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            runs_path = tmp_path / "runs.json"
            state_path = tmp_path / "state.json"
            log_path = tmp_path / "log.json"
            runs_path.write_text(json.dumps({"tasks": {}}, ensure_ascii=False), encoding="utf-8")
            args = type(
                "Args",
                (),
                {
                    "runs": str(runs_path),
                    "state": str(state_path),
                    "log": str(log_path),
                    "target": "weixin",
                    "hermes_bin": "hermes",
                    "seed": False,
                    "dry_run": True,
                    "no_write": False,
                    "include_unconfigured": False,
                },
            )()
            self.notifier.load_schedule_issue_tasks = lambda: {
                "schedule.com.summer.operation.morning": {
                    "status": "missing",
                    "message": "已经过了计划时间，但没看到今天的运行账本或日志。",
                    "step": "上午运营一键采集",
                    "finished_at": "2026-07-01",
                }
            }
            original_loader = self.notifier.load_policy_rows
            try:
                self.notifier.load_policy_rows = lambda: {}
                payload = self.notifier.notify(args)
            finally:
                self.notifier.load_policy_rows = original_loader

            self.assertEqual(payload["notification_count"], 1)
            self.assertIn("上午运营一键采集", payload["notifications"][0]["message"])

    def test_notify_deduplicates_schedule_issue_when_runtime_task_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            runs_path = tmp_path / "runs.json"
            state_path = tmp_path / "state.json"
            log_path = tmp_path / "log.json"
            runs_path.write_text(
                json.dumps(
                    {
                        "tasks": {
                            "ops.morning_collection": {
                                "status": "failed",
                                "message": "上午运营一键采集异常结束，退出码：1。",
                                "step": "launchd 包装器",
                                "finished_at": "2026-07-02 08:18:55",
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            args = type(
                "Args",
                (),
                {
                    "runs": str(runs_path),
                    "state": str(state_path),
                    "log": str(log_path),
                    "target": "weixin",
                    "hermes_bin": "hermes",
                    "seed": False,
                    "dry_run": True,
                    "no_write": False,
                    "include_unconfigured": False,
                },
            )()
            self.notifier.load_schedule_issue_tasks = lambda: {
                "schedule.com.summer.operation.morning": {
                    "status": "failed",
                    "message": "上午运营一键采集异常结束，退出码：1。",
                    "step": "上午运营一键采集",
                    "finished_at": "2026-07-02 08:18:55",
                    "extra": {"launchd_label": "com.summer.operation.morning"},
                }
            }
            original_loader = self.notifier.load_policy_rows
            try:
                self.notifier.load_policy_rows = lambda: dict(self.notifier.DIRECT_TASK_ROWS)
                payload = self.notifier.notify(args)
            finally:
                self.notifier.load_policy_rows = original_loader

            self.assertEqual(payload["notification_count"], 1)
            self.assertEqual(payload["notifications"][0]["task_id"], "ops.morning_collection")


if __name__ == "__main__":
    unittest.main()
