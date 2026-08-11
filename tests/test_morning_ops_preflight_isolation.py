from pathlib import Path
import unittest

from scripts.check_platform_login_preflight import build_notice


ROOT = Path(__file__).resolve().parents[1]


class MorningOpsPreflightIsolationTests(unittest.TestCase):
    def test_direct_account_failure_does_not_stop_headquarters_tasks(self) -> None:
        script = (ROOT / "morning-ops" / "run_morning_ops.py").read_text(encoding="utf-8")
        self.assertIn('"总部平台登录态预检"', script)
        self.assertIn('"--scope", "budget"', script)
        self.assertIn('"直营美团逐账号登录态预检"', script)
        self.assertIn('"--continue-on-direct-failure"', script)
        self.assertIn("已记录并继续总部平台、其它直营账号及推广预算任务", script)
        direct_block = script.split('"直营美团逐账号登录态预检"', 1)[1].split("ensure_backend_chrome", 1)[0]
        self.assertNotIn("raise RuntimeError", direct_block)

    def test_direct_only_notice_says_other_tasks_continue(self) -> None:
        notice = build_notice(
            "morning",
            [{"platform": "直营美团", "status": "auth_block"}],
            continue_on_direct_failure=True,
        )
        self.assertIn("失败门店将单独跳过", notice)
        self.assertIn("其它门店和总部任务继续执行", notice)


if __name__ == "__main__":
    unittest.main()
