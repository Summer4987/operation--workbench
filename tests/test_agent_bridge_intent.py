#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BRIDGE_PATH = ROOT / "ai-business-center" / "agent_bridge.py"


def load_agent_bridge():
    sys.path.insert(0, str(BRIDGE_PATH.parent))
    spec = importlib.util.spec_from_file_location("agent_bridge_for_test", BRIDGE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class AgentBridgeIntentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bridge = load_agent_bridge()

    def test_finance_text_with_amount_is_entry(self) -> None:
        self.assertTrue(self.bridge.looks_like_finance_entry("帮我记一笔 万象城采购原料 128 元 微信支付"))

    def test_finance_draft_query_is_not_entry(self) -> None:
        self.assertFalse(self.bridge.looks_like_finance_entry("财务草稿"))

    def test_help_text_tells_user_no_command_memory_needed(self) -> None:
        text = self.bridge.format_natural_help()
        self.assertIn("不用记任务类型", text)
        self.assertIn("直接按人话说", text)

    def test_file_task_guidance_uses_private_workspace(self) -> None:
        text = self.bridge.format_file_task_guidance("桌面表格帮我汇总")
        self.assertIn("HermesPrivate", text)
        self.assertIn("不覆盖原件", text)

    def test_direct_promo_bid_action_detects_explicit_target_price(self) -> None:
        self.assertTrue(self.bridge.looks_like_direct_promo_bid_action("美团 银泰城店 点金出价调到 1.8 元"))

    def test_promo_bid_help_is_not_system_config_dump(self) -> None:
        text = self.bridge.route_natural_text("推广出价", limit=3)
        self.assertIn("直接改价指令", text)
        self.assertIn("美团 银泰城店 点金出价调到 1.8 元", text)
        self.assertIn("美团会进入 Mac mini 真实执行器", text)
        self.assertIn("饿了么 direct 指令还在接入中", text)
        self.assertNotIn("中心：", text)
        self.assertNotIn("风险：", text)
        self.assertNotIn("安全命令：", text)
        self.assertNotIn("安全边界：", text)

    def test_business_term_reply_is_conversational(self) -> None:
        text = self.bridge.route_natural_text("实时数据采集", limit=3)
        self.assertIn("实时数据采集我可以帮你查运行结果", text)
        self.assertIn("还没完全纳入健康巡检清单", text)
        self.assertIn("只读采集", text)
        self.assertNotIn("中心：", text)
        self.assertNotIn("风险：", text)
        self.assertNotIn("安全命令：", text)
        self.assertNotIn("安全边界：", text)
        self.assertNotIn("python3 scripts", text)

    def test_afternoon_automation_query_uses_schedule_checker(self) -> None:
        calls = []
        original = self.bridge.run_checked
        try:
            self.bridge.run_checked = lambda command: calls.append(command) or "我查了 Mac mini 的下午自动化。"
            text = self.bridge.route_natural_text("下午自动化任务跑了吗", limit=3)
        finally:
            self.bridge.run_checked = original

        self.assertIn("下午自动化", text)
        self.assertTrue(calls)
        self.assertIn("scripts/hermes_schedule_status.py", calls[0])
        self.assertIn("--period", calls[0])
        self.assertIn("afternoon", calls[0])

    def test_today_schedule_query_uses_schedule_checker(self) -> None:
        calls = []
        original = self.bridge.run_checked
        try:
            self.bridge.run_checked = lambda command: calls.append(command) or "我查了 Mac mini 的今天定时任务。"
            text = self.bridge.route_natural_text("今天所有定时任务成功了吗", limit=3)
        finally:
            self.bridge.run_checked = original

        self.assertIn("今天定时任务", text)
        self.assertTrue(calls)
        self.assertIn("scripts/hermes_schedule_status.py", calls[0])
        self.assertNotIn("--period", calls[0])

    def test_latest_failure_question_uses_schedule_explainer(self) -> None:
        calls = []
        original = self.bridge.run_checked
        try:
            self.bridge.run_checked = lambda command: calls.append(command) or "最近需要处理的是：实时单量和营业额采集。"
            text = self.bridge.route_natural_text("那为什么失败了呢？", limit=3)
        finally:
            self.bridge.run_checked = original

        self.assertIn("实时单量和营业额采集", text)
        self.assertTrue(calls)
        self.assertIn("scripts/hermes_schedule_status.py", calls[0])
        self.assertIn("--explain-latest", calls[0])

    def test_rerun_question_uses_schedule_explainer_with_advice(self) -> None:
        calls = []
        original = self.bridge.run_checked
        try:
            self.bridge.run_checked = lambda command: calls.append(command) or "可以补跑。"
            text = self.bridge.route_natural_text("那你现在能补跑吗", limit=3)
        finally:
            self.bridge.run_checked = original

        self.assertIn("可以补跑", text)
        self.assertIn("--explain-latest", calls[0])
        self.assertIn("--rerun-advice", calls[0])

    def test_status_reply_is_not_safety_boundary_dump(self) -> None:
        original = self.bridge.build_snapshot
        try:
            self.bridge.build_snapshot = lambda refresh: {
                "generated_at": "2026-07-01 12:00:00",
                "root": "/tmp/project",
                "counts": {"ok": 1},
                "abnormal": [],
                "planned": [],
                "tasks": [],
            }
            text = self.bridge.route_natural_text("Hermes状态", limit=3)
        finally:
            self.bridge.build_snapshot = original

        self.assertIn("Hermes 基础能力自检", text)
        self.assertNotIn("安全边界：", text)

    def test_order_notification_query_uses_dedicated_checker(self) -> None:
        calls = []
        original = self.bridge.run_checked_with_timeout
        try:
            self.bridge.run_checked_with_timeout = lambda command, timeout: calls.append((command, timeout)) or "企业微信通知链路是恢复状态。"
            text = self.bridge.route_natural_text("企业微信通知和订单通知恢复了吗", limit=3)
        finally:
            self.bridge.run_checked_with_timeout = original

        self.assertIn("企业微信通知链路是恢复状态", text)
        self.assertTrue(calls)
        self.assertIn("scripts/hermes_order_notify_status.py", calls[0][0])

    def test_daily_excel_push_uses_dedicated_send(self) -> None:
        calls = []
        original = self.bridge.run_checked_with_timeout
        try:
            self.bridge.run_checked_with_timeout = lambda command, timeout: calls.append((command, timeout)) or "日配 Excel 已推送到企业微信。"
            text = self.bridge.route_natural_text("推送日配 Excel", limit=3)
        finally:
            self.bridge.run_checked_with_timeout = original

        self.assertIn("日配 Excel 已推送", text)
        self.assertIn("--send-excel", calls[0][0])

    def test_meituan_promo_spend_query_starts_realtime_refresh_by_default(self) -> None:
        self.assertTrue(self.bridge.looks_like_promo_spend_query("查询一下所有门店的美团推广消耗"))
        calls = []
        original_popen = self.bridge.subprocess.Popen
        original_root = self.bridge.ROOT
        try:
            with tempfile.TemporaryDirectory() as tmp:
                self.bridge.ROOT = pathlib.Path(tmp)
                self.bridge.subprocess.Popen = lambda command, **kwargs: calls.append((command, kwargs))
                text = self.bridge.route_natural_text("查询一下所有门店的美团推广消耗", limit=3)
        finally:
            self.bridge.subprocess.Popen = original_popen
            self.bridge.ROOT = original_root
        self.assertIn("重新打开页面查美团推广消耗", text)
        self.assertIn("不是读缓存", text)
        self.assertTrue(calls)
        self.assertIn("scripts/refresh_meituan_promo_spend_notify.py", calls[0][0])
        self.assertNotIn("我没完全识别", text)

    def test_meituan_promo_spend_query_uses_latest_snapshot_when_requested(self) -> None:
        self.assertTrue(self.bridge.looks_like_promo_spend_query("查询一下所有门店的美团推广消耗"))
        calls = []
        original = self.bridge.run_checked
        original_latest = self.bridge.PROMO_SPEND_LATEST_PATH
        try:
            with tempfile.TemporaryDirectory() as tmp:
                latest_path = pathlib.Path(tmp) / "latest.json"
                latest_path.write_text(
                    json.dumps(
                        {
                            "generated_at": "2026-07-01 11:51:02",
                            "summary": {"today_spend_total": 1002.02},
                            "items": [
                                {
                                    "ok": True,
                                    "keyword": "银泰城",
                                    "today_spend": 84,
                                    "yesterday_spend": 92.5,
                                    "updated_at_hint": "07-01 11:50",
                                }
                            ],
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                self.bridge.PROMO_SPEND_LATEST_PATH = latest_path
                self.bridge.run_checked = lambda command: calls.append(command) or "不应该调用慢查询"
                text = self.bridge.route_natural_text("看最近一次所有门店的美团推广消耗", limit=3)
        finally:
            self.bridge.run_checked = original
            self.bridge.PROMO_SPEND_LATEST_PATH = original_latest

        self.assertIn("美团推广消耗最近一次采集结果：1/1 家成功，今日合计 1002.02 元", text)
        self.assertIn("银泰城：今日 84 元，昨日 92.5 元，页面时间 07-01 11:50", text)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
