#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import pathlib
import sys
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
        self.assertNotIn("中心：", text)
        self.assertNotIn("风险：", text)
        self.assertNotIn("安全命令：", text)
        self.assertNotIn("安全边界：", text)


if __name__ == "__main__":
    unittest.main()
