import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import notify_text  # noqa: E402


class NotifyTextTests(unittest.TestCase):
    def test_strips_paths_ids_commands_and_codes(self):
        raw = ("问题：菜鸟物流采集失败，查看证据包：/Users/summer/Library/Application Support/Xiong/outputs/x\n"
               "失败分类是 execution_failed。\n处理建议：可自动补跑；命令 python3 scripts/run.py --x\n"
               "任务 schedule.com.summer.operation.evening 与 ops.realtime_order_income")
        text = notify_text.clean(raw)
        for noise in ("/Users", "Application", "execution_failed", "python3", "com.summer", "ops.realtime"):
            self.assertNotIn(noise, text)
        self.assertIn("问题：菜鸟物流采集失败", text)

    def test_translates_errors_and_drops_tracebacks(self):
        text = notify_text.clean("保利中心店|美团: failed, 平台采集：AccountQueueBusy\nTraceback (most recent call last):\n  File \"/x.py\"\nKeyError: 'a'")
        self.assertIn("美团账号排队中", text)
        self.assertIn("失败", text)
        self.assertNotIn("Traceback", text)
        self.assertNotIn("KeyError", text)
        self.assertIn("技术细节已省略", text)

    def test_keeps_numbers_stores_and_dashboard_url(self):
        raw = "1. 美团｜丽泽门店｜56.03 元（阈值 200 元）\n正式看板：https://139.155.148.169/operation-workbench/"
        self.assertEqual(notify_text.clean(raw), raw)

    def test_drops_legacy_hermes_sentences(self):
        self.assertEqual(notify_text.clean("需核实：今天有日志；Hermes 只能判断它触发过。"), "需核实：今天有日志")


if __name__ == "__main__":
    unittest.main()
