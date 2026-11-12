import contextlib
import pathlib
import signal
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import direct_meituan_browser as recovery
import check_direct_meituan_account as checker


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.profile = pathlib.Path(self.temp.name).resolve()
        self.account = {"id": "direct_yintaicheng", "profile_dir": str(self.profile), "debug_port": 19224}
        self.command = f"{recovery.CHROME} --user-data-dir={self.profile} --profile-directory=Default --remote-debugging-port=19224 https://e.waimai.meituan.com/"

    def test_healthy_connection_does_not_restart(self):
        p = mock.Mock()
        with mock.patch.object(recovery, "restart_store_browser") as restart:
            result = recovery.connect_store_browser(p, self.account, allow_recovery=True)
        self.assertIs(result, p.chromium.connect_over_cdp.return_value)
        restart.assert_not_called()
        p.chromium.connect_over_cdp.assert_called_once_with("http://127.0.0.1:19224", timeout=10_000)

    def test_timeout_recovers_once_and_reconnects(self):
        p = mock.Mock()
        browser = object()
        p.chromium.connect_over_cdp.side_effect = [TimeoutError("stalled tab"), browser]
        with mock.patch.object(recovery, "restart_store_browser") as restart:
            self.assertIs(recovery.connect_store_browser(p, self.account, allow_recovery=True), browser)
        restart.assert_called_once_with(self.account)
        self.assertEqual(p.chromium.connect_over_cdp.call_count, 2)

    def test_commit_default_never_restarts(self):
        p = mock.Mock()
        p.chromium.connect_over_cdp.side_effect = TimeoutError("stalled tab")
        with mock.patch.object(recovery, "restart_store_browser") as restart:
            with self.assertRaises(TimeoutError):
                recovery.connect_store_browser(p, self.account)
        restart.assert_not_called()

    def test_second_connection_failure_does_not_loop(self):
        p = mock.Mock()
        p.chromium.connect_over_cdp.side_effect = TimeoutError("stalled tab")
        with mock.patch.object(recovery, "restart_store_browser") as restart:
            with self.assertRaises(TimeoutError):
                recovery.connect_store_browser(p, self.account, allow_recovery=True)
        restart.assert_called_once()
        self.assertEqual(p.chromium.connect_over_cdp.call_count, 2)

    def test_exact_profile_and_port_matching(self):
        self.assertTrue(recovery.matches_browser(self.command, self.profile, 19224))
        for command in [self.command.replace(str(self.profile), str(self.profile) + "-other"),
                        self.command.replace("19224 ", "192240 "),
                        "helper " + self.command]:
            self.assertFalse(recovery.matches_browser(command, self.profile, 19224))

    def restart_patches(self, rows):
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(recovery, "production_recovery_allowed", return_value=True))
        stack.enter_context(mock.patch.object(recovery, "process_rows", side_effect=rows))
        stack.enter_context(mock.patch.object(recovery, "cdp_ready", return_value=True))
        return stack

    def test_only_exact_browser_is_gracefully_restarted(self):
        with self.restart_patches([[(100, self.command), (101, self.command.replace("19224", "19225"))], []]), \
             mock.patch.object(recovery.os, "kill") as kill, \
             mock.patch.object(recovery.subprocess, "Popen") as launch:
            recovery.restart_store_browser(self.account)
        kill.assert_called_once_with(100, signal.SIGTERM)
        args = launch.call_args.args[0]
        self.assertIn(f"--user-data-dir={self.profile}", args)
        self.assertIn("--remote-debugging-port=19224", args)
        self.assertEqual(args[-1], "https://e.waimai.meituan.com/")

    def test_active_commit_blocks_recovery(self):
        with self.restart_patches([[(100, self.command), (200, "python store-inspection/meituan_budget_cdp.py --period 晚餐 --mode commit")]]), \
             mock.patch.object(recovery.os, "kill") as kill:
            with self.assertRaisesRegex(RuntimeError, "正式提交"):
                recovery.restart_store_browser(self.account)
        kill.assert_not_called()

    def test_missing_browser_starts_only_when_profile_and_port_are_free(self):
        with self.restart_patches([[]]), \
             mock.patch.object(recovery, "cdp_ready", side_effect=[False, True]), \
             mock.patch.object(recovery.os, "kill") as kill, \
             mock.patch.object(recovery.subprocess, "Popen") as launch:
            recovery.restart_store_browser(self.account)
        kill.assert_not_called()
        launch.assert_called_once()

    def test_profile_on_another_port_is_not_launched_twice(self):
        with self.restart_patches([[(100, self.command.replace("19224", "19225"))]]), \
             mock.patch.object(recovery.os, "kill") as kill, \
             mock.patch.object(recovery.subprocess, "Popen") as launch:
            with self.assertRaisesRegex(RuntimeError, "占用"):
                recovery.restart_store_browser(self.account)
        kill.assert_not_called()
        launch.assert_not_called()

    def test_ambiguous_browser_blocks_recovery(self):
        with self.restart_patches([[(100, self.command), (101, self.command)]]), \
             mock.patch.object(recovery.os, "kill") as kill:
            with self.assertRaisesRegex(RuntimeError, "匹配 2"):
                recovery.restart_store_browser(self.account)
        kill.assert_not_called()

    def test_development_machine_cannot_restart(self):
        with mock.patch.object(recovery, "production_recovery_allowed", return_value=False), \
             mock.patch.object(recovery.os, "kill") as kill:
            with self.assertRaisesRegex(RuntimeError, "Mac mini"):
                recovery.restart_store_browser(self.account)
        kill.assert_not_called()

    def test_cooldown_blocks_repeated_recovery(self):
        (self.profile / ".automation-recovery.lock").write_text(str(recovery.time.time()))
        with self.restart_patches([]), mock.patch.object(recovery.os, "kill") as kill:
            with self.assertRaisesRegex(RuntimeError, "5 分钟"):
                recovery.restart_store_browser(self.account)
        kill.assert_not_called()

    def test_failed_graceful_exit_never_forces_kill_or_relaunches(self):
        with mock.patch.object(recovery, "production_recovery_allowed", return_value=True), \
             mock.patch.object(recovery, "process_rows", return_value=[(100, self.command)]), \
             mock.patch.object(recovery.time, "monotonic", side_effect=[0, 9]), \
             mock.patch.object(recovery.os, "kill") as kill, \
             mock.patch.object(recovery.subprocess, "Popen") as launch:
            with self.assertRaisesRegex(RuntimeError, "未强制终止"):
                recovery.restart_store_browser(self.account)
        kill.assert_called_once_with(100, signal.SIGTERM)
        launch.assert_not_called()

    def test_probe_closes_own_tab_after_failed_page_read(self):
        p = mock.Mock()
        browser = mock.Mock()
        browser.contexts = [mock.Mock()]
        self.account["pages"] = {"home": "https://e.waimai.meituan.com/"}
        manager = mock.MagicMock()
        manager.__enter__.return_value = p
        with mock.patch.object(checker, "load_account", return_value=self.account), \
             mock.patch.object(checker, "require_playwright", return_value=lambda: manager), \
             mock.patch.object(checker, "connect_store_browser", return_value=browser), \
             mock.patch.object(checker, "check_page", side_effect=TimeoutError("navigation")):
            with self.assertRaises(TimeoutError):
                checker.run_check(self.account["id"], False, 0, None, ["home"])
        browser.contexts[0].new_page.return_value.close.assert_called_once()
        browser.close.assert_not_called()

    def test_failed_attach_never_launches_second_profile(self):
        p = mock.Mock()
        manager = mock.MagicMock()
        manager.__enter__.return_value = p
        with mock.patch.object(checker, "load_account", return_value=self.account), \
             mock.patch.object(checker, "require_playwright", return_value=lambda: manager), \
             mock.patch.object(checker, "connect_store_browser", side_effect=TimeoutError("stalled")):
            with self.assertRaises(TimeoutError):
                checker.run_check(self.account["id"], False, 0, None, ["home"])
        p.chromium.launch_persistent_context.assert_not_called()

    def test_login_probe_uses_new_tab_and_propagates_attach_failure(self):
        p = mock.Mock()
        browser = mock.Mock()
        browser.contexts = [mock.Mock()]
        with mock.patch.object(checker, "connect_store_browser", return_value=browser):
            _, context, page = checker.get_page_from_attached_chrome(p, self.account)
        self.assertIs(page, context.new_page.return_value)
        page.set_default_timeout.assert_called_once_with(5_000)
        with mock.patch.object(checker, "connect_store_browser", side_effect=TimeoutError("stalled")):
            with self.assertRaises(TimeoutError):
                checker.get_page_from_attached_chrome(p, self.account)
        p.chromium.launch_persistent_context.assert_not_called()


if __name__ == "__main__":
    unittest.main()
