from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import agent_command, agent_notify  # noqa: E402


class AgentNotifyTests(unittest.TestCase):
    def test_build_message_uses_wecom_friendly_text(self) -> None:
        message = agent_notify.build_message(
            title="预算预览完成",
            status="success",
            detail="没有真实提交预算。",
            action="可以继续观察。",
            source="test",
            generated_at="2026-07-04 10:00:00",
        )

        self.assertIn("熊小小运营 Agent", message)
        self.assertIn("事项：预算预览完成", message)
        self.assertIn("说明：没有真实提交预算。", message)
        self.assertIn("时间：2026-07-04 10:00:00", message)

    def test_build_message_hides_long_urls(self) -> None:
        message = agent_notify.build_message(
            title="巡检美团实时消耗",
            status="warning",
            detail="未核实。当前URL：https://waimaieapp.meituan.com/ad/v1/rpc?token=secret&wmPoiId=32022526",
            generated_at="2026-07-09 10:00:00",
        )

        self.assertIn("当前页面链接已省略", message)
        self.assertNotIn("https://", message)
        self.assertNotIn("token=secret", message)

    def test_command_payload_blocked_ordering_becomes_blocked_notice(self) -> None:
        payload = agent_command.handle_command("订货补跑", execute=True)
        status, message = agent_notify.message_from_command_payload(payload)

        self.assertEqual(status, "blocked")
        self.assertIn("已拦截", message)
        self.assertIn("订货补跑", message)
        self.assertIn("不参与订货", message)

    def test_command_payload_budget_without_execute_is_preview_notice(self) -> None:
        payload = agent_command.handle_command("重跑预算设置", execute=False)
        status, message = agent_notify.message_from_command_payload(payload)

        self.assertEqual(status, "preview")
        self.assertIn("预览", message)
        self.assertIn("--execute", message)

    def test_send_agent_notification_dry_run_writes_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "latest.json"
            payload = agent_notify.send_agent_notification(
                title="测试通知",
                status="info",
                detail="dry-run",
                dry_run=True,
                output=output,
            )

            self.assertTrue(payload["delivered"])
            self.assertEqual(payload["delivery_output"], "dry-run")
            self.assertTrue(output.exists())

    def test_send_command_notification_uses_ops_notify_when_not_dry_run(self) -> None:
        payload = agent_command.handle_command("重跑预算设置", execute=False)
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.object(agent_notify.ops_notify, "notify", return_value=True) as mocked:
            output = Path(temp_dir) / "latest.json"
            record = agent_notify.send_command_notification(payload, dry_run=False, output=output)

            self.assertTrue(record["delivered"])
            mocked.assert_called_once()
            self.assertTrue(output.exists())


if __name__ == "__main__":
    unittest.main()
