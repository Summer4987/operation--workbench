from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import agent_chat  # noqa: E402


class AgentChatTests(unittest.TestCase):
    def test_compact_reason_removes_escaped_byte_noise(self) -> None:
        reason = agent_chat.compact_reason("美团预算失败。关键日志：f\\xbc\\x9a\\xe6\\xb2\\xa1\\xe6\\x9c\\x89\\n后续内容")

        self.assertIn("美团预算失败", reason)
        self.assertIn("关键日志已省略", reason)
        self.assertNotIn("\\x", reason)

    def test_execution_question_names_skipped_agent(self) -> None:
        answer = agent_chat.build_execution_answer(
            {
                "stages": [
                    {"id": "collect", "agent": "collect", "name": "采集 Agent", "status": "success"},
                    {
                        "id": "execute",
                        "agent": "execution",
                        "name": "执行 Agent",
                        "status": "skipped",
                        "message": "执行 Agent 需要显式 --allow-execution。",
                    },
                ]
            }
        )

        self.assertIn("执行 Agent", answer)
        self.assertIn("id: execute", answer)
        self.assertIn("--allow-execution", answer)

    def test_execution_question_reports_successful_execution_agent(self) -> None:
        answer = agent_chat.build_execution_answer(
            {
                "stages": [
                    {
                        "id": "execute",
                        "agent": "execution",
                        "name": "执行 Agent",
                        "status": "success",
                    }
                ]
            }
        )

        self.assertIn("执行 Agent 已参与", answer)
        self.assertIn("订货/下单/采购类动作不参与", answer)

    def test_problem_answer_prefers_pipeline_failure(self) -> None:
        answer = agent_chat.build_problem_answer(
            {"stages": [{"name": "校验 Agent", "status": "failed", "message": "缺少产物"}]},
            {"tasks": []},
        )

        self.assertIn("校验 Agent", answer)
        self.assertIn("缺少产物", answer)

    def test_problem_answer_separates_failures_from_attention(self) -> None:
        answer = agent_chat.build_problem_answer(
            {"stages": []},
            {
                "summary": {"total": 3, "completed": 0, "failed": 1, "attention": 2, "missing": 0, "running": 0},
                "tasks": [
                    {
                        "id": "morning.01",
                        "name": "上午运营一键采集总状态",
                        "status": "failed",
                        "failure_reason": "直营美团日报失败",
                        "evidence": "outputs/morning_collection_status/latest.json",
                    },
                    {
                        "id": "morning.02",
                        "name": "Chrome/登录环境检查",
                        "status": "attention",
                        "failure_reason": "产物已生成但缺少步骤记录",
                    },
                    {
                        "id": "morning.03",
                        "name": "双平台评价下载",
                        "status": "attention",
                        "failure_reason": "产物已生成但缺少步骤记录",
                    },
                ]
            },
        )

        self.assertIn("今天需要处理的功能", answer)
        self.assertIn("结论：不完全正常", answer)
        self.assertIn("功能验收状态", answer)
        self.assertIn("1. 上午运营一键采集总状态：失败", answer)
        self.assertIn("直营美团日报失败", answer)
        self.assertIn("2. Chrome/登录环境检查：需核实", answer)

    def test_problem_answer_reports_attention_as_verification_not_failure(self) -> None:
        answer = agent_chat.build_problem_answer(
            {"stages": []},
            {
                "summary": {"total": 1, "completed": 0, "failed": 0, "attention": 1, "missing": 0, "running": 0},
                "tasks": [{"name": "Chrome/登录环境检查", "status": "attention"}],
            },
        )

        self.assertIn("今天需要处理的功能", answer)
        self.assertIn("结论：核心任务没有失败", answer)
        self.assertIn("1. Chrome/登录环境检查：需核实", answer)

    def test_status_answer_is_numbered_task_board(self) -> None:
        answer = agent_chat.build_status_answer(
            {"summary": {"success": 5, "failed": 0, "skipped": 0}},
            {
                "summary": {"total": 3, "completed": 1, "failed": 1, "attention": 1, "missing": 0, "running": 0},
                "tasks": [
                    {"id": "m1", "name": "直营店日报采集", "status": "failed", "failure_reason": "直营美团日报失败", "rerun": {"suggested": True, "auto_allowed": False}},
                    {"id": "m2", "name": "推广余额巡检", "status": "completed", "rerun": {"suggested": False}},
                    {"id": "m3", "name": "总看板云端发布", "status": "attention", "failure_reason": "产物已生成但缺少步骤记录", "rerun": {"suggested": True, "auto_allowed": True}},
                ],
                "rerun_plan": [
                    {"task_id": "m3", "task_name": "总看板云端发布", "auto_allowed": True},
                    {"task_id": "m1", "task_name": "直营店日报采集", "auto_allowed": False},
                ],
            },
        )

        self.assertIn("自动化功能验收报告", answer)
        self.assertIn("结论：不完全正常", answer)
        self.assertIn("功能验收状态", answer)
        self.assertIn("1. 直营店日报采集：失败", answer)
        self.assertIn("2. 推广余额巡检：成功", answer)
        self.assertIn("3. 总看板云端发布：需核实", answer)
        self.assertIn("处理建议", answer)
        self.assertIn("可自动处理：总看板云端发布", answer)

    def test_tracked_task_lines_include_action_for_each_core_task(self) -> None:
        today = agent_chat.today_text()
        answer = agent_chat.build_status_answer(
            {"summary": {"success": 5, "failed": 0, "skipped": 0}},
            {"summary": {"completed": 1, "failed": 0, "attention": 0}},
            {
                "generated_at": f"{today} 10:30:00",
                "tasks": {
                    "ops.morning_collection": {
                        "status": "failed",
                        "updated_at": f"{today} 08:15:00",
                        "step": "launchd 包装器",
                        "message": "上午采集失败。",
                        "log_path": "morning.log",
                    }
                },
            },
            "今天任务状态",
        )

        self.assertIn("值班报告", answer)
        self.assertIn("任务清单", answer)
        self.assertIn("1. 上午运营一键采集：失败", answer)
        self.assertIn("原因：上午采集失败", answer)
        self.assertIn("证据：morning.log", answer)
        self.assertIn("处理：高风险，需人工确认，不自动补跑", answer)
        self.assertIn("2. 加盟店实时数据采集：今日未记录", answer)

    def test_today_status_uses_task_runs_and_does_not_surface_yesterday_failure_as_today(self) -> None:
        today = agent_chat.today_text()
        answer = agent_chat.build_status_answer(
            {"summary": {"success": 5, "failed": 0, "skipped": 0}},
            {"summary": {"completed": 13, "failed": 0, "attention": 1}},
            {
                "tasks": {
                    "ops.morning_collection": {
                        "status": "success",
                        "updated_at": f"{today} 08:26:33",
                        "step": "汇总",
                        "message": "上午运营一键采集完成。",
                    },
                    "growth.promo_budget": {
                        "status": "failed",
                        "updated_at": "2026-07-12 16:56:39",
                        "step": "晚餐预算汇总",
                        "message": "昨天饿了么捕获失败。",
                    },
                }
            },
            "任务状态",
        )

        self.assertIn("今天任务状态", answer)
        self.assertIn("上午运营一键采集：成功", answer)
        self.assertIn("下午/晚餐推广预算设置：今日未运行", answer)
        self.assertIn("最近一次 2026-07-12 16:56 是失败", answer)
        self.assertNotIn("昨天饿了么捕获失败", answer)
        self.assertNotIn("结论：有 1 个今日失败项", answer)

    def test_today_status_marks_monitor_failures_as_historical_when_no_today_failure(self) -> None:
        today = agent_chat.today_text()
        answer = agent_chat.build_status_answer(
            {"summary": {"success": 5, "failed": 0, "skipped": 0}},
            {"summary": {"completed": 13, "failed": 1, "attention": 0}},
            {
                "generated_at": f"{today} 10:00:00",
                "tasks": {
                    "agents.daily_automation_guard": {
                        "status": "success",
                        "updated_at": f"{today} 10:00:00",
                        "step": "agent pipeline",
                        "message": "守护完成。",
                    },
                    "growth.promo_budget": {
                        "status": "failed",
                        "updated_at": "2026-07-16 16:48:11",
                        "step": "晚餐预算汇总",
                        "message": "历史预算失败。",
                    },
                },
            },
            "今天任务状态",
        )

        self.assertIn("结论：没有今日失败项", answer)
        self.assertIn("仍保留历史未处理项，失败 1", answer)
        self.assertIn("历史未处理清单", answer)
        self.assertIn("这不等于今天新增失败", answer)
        self.assertNotIn("历史预算失败", answer)

    def test_today_status_warns_when_task_runs_file_is_stale(self) -> None:
        answer = agent_chat.build_status_answer(
            {"summary": {"success": 5, "failed": 0, "skipped": 0}},
            {"summary": {"completed": 13, "failed": 1, "attention": 0}},
            {
                "generated_at": "2026-07-17 08:15:46",
                "tasks": {
                    "ops.morning_collection": {
                        "status": "failed",
                        "updated_at": "2026-07-17 08:15:46",
                        "step": "launchd 包装器",
                        "message": "旧的上午运营失败",
                    }
                },
            },
            "今天任务状态",
        )

        self.assertIn("数据源过期", answer)
        self.assertIn("不能把里面的旧失败当成今天的问题", answer)
        self.assertIn("上午运营一键采集：今日未运行", answer)
        self.assertNotIn("旧的上午运营失败", answer)

    def test_today_problem_question_does_not_report_stale_failure_as_today(self) -> None:
        answer = agent_chat.build_problem_answer_for_date(
            {"stages": []},
            {
                "summary": {"completed": 13, "failed": 1, "attention": 0},
                "tasks": [
                    {
                        "name": "上午运营一键采集",
                        "status": "failed",
                        "failure_reason": "旧的上午失败",
                        "evidence": "outputs/morning.json",
                        "rerun": {"suggested": True, "auto_allowed": False},
                    }
                ],
            },
            {
                "generated_at": "2026-07-17 08:15:46",
                "tasks": {
                    "growth.promo_budget": {
                        "status": "failed",
                        "updated_at": "2026-07-17 16:48:11",
                        "step": "晚餐预算汇总",
                        "message": "旧的预算失败",
                    }
                },
            },
            "今天哪里失败",
        )

        self.assertIn("今天失败明细", answer)
        self.assertIn("数据源过期", answer)
        self.assertIn("当前不能确认今天是否有新增失败", answer)
        self.assertIn("历史未处理清单", answer)
        self.assertIn("1. 上午运营一键采集：失败", answer)
        self.assertIn("证据：outputs/morning.json", answer)
        self.assertIn("处理：需人工确认，不自动补跑", answer)
        self.assertNotIn("旧的预算失败", answer)

    def test_today_problem_question_without_today_failures_does_not_list_historical_failures(self) -> None:
        today = agent_chat.today_text()
        answer = agent_chat.build_problem_answer_for_date(
            {"stages": []},
            {"summary": {"completed": 13, "failed": 1, "attention": 0}},
            {
                "generated_at": f"{today} 10:14:28",
                "tasks": {
                    "growth.promo_budget": {
                        "status": "failed",
                        "updated_at": "2026-07-16 16:48:11",
                        "step": "晚餐预算汇总",
                        "message": "历史预算失败。",
                    },
                    "agents.daily_automation_guard": {
                        "status": "success",
                        "updated_at": f"{today} 10:14:28",
                        "step": "agent pipeline",
                        "message": "守护完成。",
                    },
                },
            },
            "今天哪里有问题",
        )

        self.assertIn("结论：今天没有读到失败项", answer)
        self.assertIn("历史未处理", answer)
        self.assertIn("历史未处理清单", answer)
        self.assertIn("这不是今天新增失败", answer)
        self.assertNotIn("下午/晚餐推广预算设置", answer)
        self.assertNotIn("历史预算失败", answer)

    def test_yesterday_problem_question_reports_yesterday_failure_details(self) -> None:
        yesterday = (agent_chat.datetime.now() - agent_chat.timedelta(days=1)).strftime("%Y-%m-%d")
        answer = agent_chat.build_problem_answer_for_date(
            {"stages": []},
            {"summary": {"completed": 13, "failed": 0, "attention": 1}},
            {
                "tasks": {
                    "growth.promo_budget": {
                        "status": "success",
                        "updated_at": f"{agent_chat.today_text()} 08:00:00",
                        "step": "今日收尾",
                        "message": "今天已经成功。",
                    }
                },
                "events": [
                    {
                        "task_id": "growth.promo_budget",
                        "status": "failed",
                        "created_at": f"{yesterday} 16:56:39",
                        "step": "晚餐预算汇总",
                        "message": "饿了么预算捕获失败。",
                        "log_path": "outputs/current_budget/logs/current_budget_晚餐.log",
                    },
                    {
                        "task_id": "growth.promo_budget",
                        "status": "success",
                        "created_at": f"{yesterday} 17:20:00",
                        "step": "晚餐预算补跑",
                        "message": "晚餐预算补跑完成。",
                    },
                ],
            },
            "昨天任务失败原因",
        )

        self.assertIn("失败明细", answer)
        self.assertIn("当前没有", answer)
        self.assertIn("曾失败后已恢复 1 项", answer)
        self.assertIn("下午/晚餐推广预算设置：曾失败", answer)
        self.assertIn("饿了么预算捕获失败", answer)
        self.assertIn("outputs/current_budget/logs/current_budget_晚餐.log", answer)
        self.assertIn("恢复：后续已有成功记录", answer)

    def test_today_problem_question_separates_recovered_failures_from_active_failures(self) -> None:
        today = agent_chat.today_text()
        answer = agent_chat.build_problem_answer_for_date(
            {"stages": []},
            {"summary": {"completed": 13, "failed": 0, "attention": 0}},
            {
                "generated_at": f"{today} 08:40:00",
                "tasks": {
                    "ops.morning_collection": {
                        "status": "success",
                        "updated_at": f"{today} 08:28:00",
                        "step": "汇总",
                        "message": "上午运营一键采集完成。",
                    }
                },
                "events": [
                    {
                        "task_id": "ops.morning_collection",
                        "status": "failed",
                        "created_at": f"{today} 08:10:00",
                        "step": "巡检证据上传云端",
                        "message": "巡检证据上传云端失败。",
                        "log_path": "logs/today.log",
                    },
                    {
                        "task_id": "ops.morning_collection",
                        "status": "success",
                        "created_at": f"{today} 08:28:00",
                        "step": "汇总",
                        "message": "上午运营一键采集完成。",
                    },
                ],
            },
            "今天哪里失败",
        )

        self.assertIn("结论：当前没有今日未恢复失败", answer)
        self.assertIn("今日曾失败后已恢复 1 项", answer)
        self.assertIn("已恢复记录", answer)
        self.assertIn("上午运营一键采集：曾失败（08:10）", answer)
        self.assertIn("恢复：后续已有成功记录（08:28，汇总）", answer)
        self.assertNotIn("当前失败清单", answer)

    def test_today_problem_question_lists_active_failures_before_recovered_failures(self) -> None:
        today = agent_chat.today_text()
        answer = agent_chat.build_problem_answer_for_date(
            {"stages": []},
            {"summary": {"completed": 13, "failed": 0, "attention": 0}},
            {
                "generated_at": f"{today} 17:10:00",
                "tasks": {
                    "ops.morning_collection": {
                        "status": "success",
                        "updated_at": f"{today} 08:28:00",
                        "step": "汇总",
                        "message": "上午运营一键采集完成。",
                    },
                    "growth.promo_budget": {
                        "status": "failed",
                        "updated_at": f"{today} 16:58:00",
                        "step": "晚餐预算汇总",
                        "message": "美团预算提交失败。",
                    },
                },
                "events": [
                    {
                        "task_id": "ops.morning_collection",
                        "status": "failed",
                        "created_at": f"{today} 08:10:00",
                        "step": "巡检证据上传云端",
                        "message": "巡检证据上传云端失败。",
                    },
                    {
                        "task_id": "ops.morning_collection",
                        "status": "success",
                        "created_at": f"{today} 08:28:00",
                        "step": "汇总",
                        "message": "上午运营一键采集完成。",
                    },
                ],
            },
            "今天哪里失败",
        )

        self.assertIn("结论：当前仍有 1 个今日失败项", answer)
        self.assertIn("当前失败清单", answer)
        self.assertIn("下午/晚餐推广预算设置：失败（16:58）", answer)
        self.assertIn("已恢复记录", answer)
        self.assertIn("上午运营一键采集：曾失败（08:10）", answer)

    def test_answer_question_uses_latest_files(self) -> None:
        original_root = agent_chat.ROOT
        original_pipeline_path = agent_chat.PIPELINE_PATH
        original_monitor_path = agent_chat.MONITOR_PATH
        original_task_runs_path = agent_chat.TASK_RUNS_PATH
        original_direct_daily_path = agent_chat.DIRECT_DAILY_PATH
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                pipeline_path = root / "outputs" / "agent_pipeline" / "daily_automation_guard" / "latest.json"
                monitor_path = root / "outputs" / "agent_task_monitor" / "latest.json"
                task_runs_path = root / "outputs" / "task_runs" / "latest.json"
                direct_daily_path = root / "business-report-dashboard" / "data" / "direct_unified_daily.csv"
                pipeline_path.parent.mkdir(parents=True)
                monitor_path.parent.mkdir(parents=True)
                task_runs_path.parent.mkdir(parents=True)
                direct_daily_path.parent.mkdir(parents=True)
                pipeline_path.write_text(
                    '{"generated_at":"2026-07-03 10:00:00","summary":{"success":5,"failed":0,"skipped":1},"stages":[{"id":"execute","agent":"execution","name":"执行 Agent","status":"skipped","message":"默认禁用"}]}',
                    encoding="utf-8",
                )
                monitor_path.write_text('{"summary":{"completed":1,"failed":0,"attention":0},"tasks":[]}', encoding="utf-8")
                task_runs_path.write_text('{"generated_at":"2026-07-03 10:00:01","tasks":{}}', encoding="utf-8")
                direct_daily_path.write_text("date,platform,store,orders,income,store_raw\n", encoding="utf-8")
                agent_chat.ROOT = root
                agent_chat.PIPELINE_PATH = pipeline_path
                agent_chat.MONITOR_PATH = monitor_path
                agent_chat.TASK_RUNS_PATH = task_runs_path
                agent_chat.DIRECT_DAILY_PATH = direct_daily_path

                payload = agent_chat.answer_question("现在 agent 状态怎么样？", use_llm=False)

                self.assertEqual(payload["intent"], "status")
                self.assertIn("成功 5 个", payload["answer"])
                self.assertFalse(payload["llm"]["enabled"])
        finally:
            agent_chat.ROOT = original_root
            agent_chat.PIPELINE_PATH = original_pipeline_path
            agent_chat.MONITOR_PATH = original_monitor_path
            agent_chat.TASK_RUNS_PATH = original_task_runs_path
            agent_chat.DIRECT_DAILY_PATH = original_direct_daily_path

    def test_restore_question_about_store_uses_business_data_not_rerun(self) -> None:
        original_root = agent_chat.ROOT
        original_pipeline_path = agent_chat.PIPELINE_PATH
        original_monitor_path = agent_chat.MONITOR_PATH
        original_task_runs_path = agent_chat.TASK_RUNS_PATH
        original_direct_daily_path = agent_chat.DIRECT_DAILY_PATH
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                pipeline_path = root / "outputs" / "agent_pipeline" / "daily_automation_guard" / "latest.json"
                monitor_path = root / "outputs" / "agent_task_monitor" / "latest.json"
                task_runs_path = root / "outputs" / "task_runs" / "latest.json"
                direct_daily_path = root / "business-report-dashboard" / "data" / "direct_unified_daily.csv"
                pipeline_path.parent.mkdir(parents=True)
                monitor_path.parent.mkdir(parents=True)
                task_runs_path.parent.mkdir(parents=True)
                direct_daily_path.parent.mkdir(parents=True)
                pipeline_path.write_text('{"summary":{"success":5,"failed":0,"skipped":0},"stages":[]}', encoding="utf-8")
                monitor_path.write_text('{"summary":{"completed":1,"failed":0,"attention":0},"tasks":[]}', encoding="utf-8")
                task_runs_path.write_text('{"generated_at":"2026-07-13 08:00:00","tasks":{}}', encoding="utf-8")
                direct_daily_path.write_text(
                    "\n".join(
                        [
                            "date,platform,store,orders,income,store_raw",
                            "2026-07-12,美团,朝阳门店,68,2237.79,熊小小牛排饭POKEEBEAR（第B2档口雅宝食堂美食城店）",
                            "2026-07-12,饿了么,朝阳门店,57,1623.81,熊小小牛排饭POKEBEAR(朝阳门店)",
                        ]
                    )
                    + "\n",
                    encoding="utf-8",
                )
                agent_chat.ROOT = root
                agent_chat.PIPELINE_PATH = pipeline_path
                agent_chat.MONITOR_PATH = monitor_path
                agent_chat.TASK_RUNS_PATH = task_runs_path
                agent_chat.DIRECT_DAILY_PATH = direct_daily_path

                payload = agent_chat.answer_question("朝阳门店的美团数据页恢复了吗？", use_llm=False)

                self.assertEqual(payload["intent"], "business_data")
                self.assertIn("朝阳门店数据页：已恢复", payload["answer"])
                self.assertIn("美团：68 单", payload["answer"])
                self.assertIn("2237.79", payload["answer"])
                self.assertNotIn("补跑计划", payload["answer"])
        finally:
            agent_chat.ROOT = original_root
            agent_chat.PIPELINE_PATH = original_pipeline_path
            agent_chat.MONITOR_PATH = original_monitor_path
            agent_chat.TASK_RUNS_PATH = original_task_runs_path
            agent_chat.DIRECT_DAILY_PATH = original_direct_daily_path

    def test_answer_question_can_use_llm_generated_answer(self) -> None:
        original_generate_answer = agent_chat.agent_llm.generate_answer
        try:
            agent_chat.agent_llm.generate_answer = lambda **kwargs: {
                "used": True,
                "answer": "今天整体正常，执行 Agent 仍按规则排除订货。",
                "confidence": 0.82,
                "provider": "deepseek",
                "model": "deepseek-chat",
                "reason": "基于草稿改写",
            }

            payload = agent_chat.answer_question("帮助")

            self.assertTrue(payload["llm"]["used"])
            self.assertIn("整体正常", payload["answer"])
            self.assertIn("draft_answer", payload["llm"])
        finally:
            agent_chat.agent_llm.generate_answer = original_generate_answer

    def test_answer_question_falls_back_when_llm_confidence_is_low(self) -> None:
        original_generate_answer = agent_chat.agent_llm.generate_answer
        try:
            agent_chat.agent_llm.generate_answer = lambda **kwargs: {
                "used": True,
                "answer": "低置信度回答",
                "confidence": 0.2,
                "provider": "deepseek",
                "model": "deepseek-chat",
                "reason": "不确定",
            }

            payload = agent_chat.answer_question("帮助")

            self.assertFalse("低置信度回答" == payload["answer"])
            self.assertTrue(payload["llm"]["used"])
        finally:
            agent_chat.agent_llm.generate_answer = original_generate_answer


if __name__ == "__main__":
    unittest.main()
