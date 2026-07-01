from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import agent_task_monitor as monitor_module  # noqa: E402
import agent_rerun_dry_run as rerun_module  # noqa: E402


class AgentTaskMonitorTests(unittest.TestCase):
    def test_health_warning_takes_precedence_over_success_run(self) -> None:
        self.assertEqual(monitor_module.classify_completion("warn", "success"), "attention")

    def test_attention_reason_prefers_health_reason(self) -> None:
        row = monitor_module.build_task_report(
            "ops.realtime_order_income",
            {
                "id": "ops.realtime_order_income",
                "status": "warn",
                "reason": "实时采集数据已生成，但云端发布权限错误。",
                "last_seen_at": "2026-06-30 20:01:15",
            },
            {
                "tasks": {
                    "ops.realtime_order_income": {
                        "status": "success",
                        "message": "实时单量收入采集完成。",
                        "updated_at": "2026-06-30 20:01:15",
                    }
                }
            },
            {"name": "实时单量和营业额采集"},
        )

        self.assertEqual(row["status"], "attention")
        self.assertIn("云端发布权限错误", row["failure_reason"])

    def test_wechat_text_is_plain_language(self) -> None:
        payload = {
            "generated_at": "2026-07-01 10:00:00",
            "summary": {
                "total": 2,
                "completed": 0,
                "failed": 1,
                "attention": 1,
                "running": 0,
                "missing": 0,
                "skipped": 0,
                "rerun_suggested": 2,
                "auto_rerun_allowed": 1,
                "report_only": 1,
            },
            "tasks": [
                {
                    "id": "ops.morning_collection",
                    "name": "上午运营一键采集",
                    "status": "failed",
                    "status_text": "失败",
                    "failure_reason": "异常结束，退出码 143。",
                    "last_run_step": "launchd 包装器",
                    "rerun": {"suggested": True, "auto_allowed": False},
                },
                {
                    "id": "ops.realtime_order_income",
                    "name": "实时单量和营业额采集",
                    "status": "attention",
                    "status_text": "需关注",
                    "failure_reason": "数据已生成，但云端发布失败。",
                    "last_run_step": "发布工作台云端数据",
                    "rerun": {"suggested": True, "auto_allowed": True},
                },
            ],
            "rerun_plan": [
                {"task_id": "ops.realtime_order_income", "task_name": "实时单量和营业额采集", "auto_allowed": True},
                {"task_id": "ops.morning_collection", "task_name": "上午运营一键采集", "auto_allowed": False},
            ],
        }

        text = monitor_module.build_wechat_text(payload)

        self.assertIn("这次有 2 个自动化任务需要处理", text)
        self.assertIn("上午运营一键采集：失败。原因：异常结束，退出码 143。", text)
        self.assertIn("可以安全补跑的是：实时单量和营业额采集", text)
        self.assertNotIn("Mac mini 自动化任务透明化报告", text)
        self.assertNotIn("｜", text)

    def test_excluded_policy_rows_do_not_enter_report(self) -> None:
        rows = monitor_module.task_rows(
            {"tasks": [{"id": "tools.franchise_contract", "status": "warn", "name": "加盟合同生成器"}]},
            {"tasks": {}},
            {"tools.franchise_contract": {"include_in_report": False, "name": "加盟合同生成器"}},
        )

        self.assertEqual(rows, [])

    def test_rerun_execute_runs_only_allowed_candidates(self) -> None:
        original_execute = rerun_module.execute_command
        try:
            calls = []

            def fake_execute(command, *, timeout):
                calls.append(command)
                return {"executed": True, "returncode": 0, "output": "ok"}

            rerun_module.execute_command = fake_execute
            plan = rerun_module.build_dry_run(
                {
                    "generated_at": "2026-07-01 10:00:00",
                    "tasks": [
                        {"id": "ops.realtime_order_income", "name": "实时单量和营业额采集", "risk": "low", "status": "attention"},
                        {"id": "growth.promo_budget", "name": "推广预算初始化设置", "risk": "high", "status": "failed"},
                    ],
                    "rerun_plan": [
                        {"task_id": "ops.realtime_order_income", "task_name": "实时单量和营业额采集", "auto_allowed": True, "command": ["echo", "ok"]},
                        {"task_id": "growth.promo_budget", "task_name": "推广预算初始化设置", "auto_allowed": True, "command": ["echo", "risk"]},
                    ],
                },
                execute=True,
            )
        finally:
            rerun_module.execute_command = original_execute

        self.assertEqual(calls, [["echo", "ok"]])
        self.assertEqual(plan["summary"]["executed"], 1)
        self.assertEqual(plan["summary"]["report_only"], 1)


if __name__ == "__main__":
    unittest.main()
