from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "download_direct_meituan_daily.py"


def load_module():
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("download_direct_meituan_daily_for_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeSyncPlaywright:
    def __call__(self):
        return self

    def __enter__(self):
        return object()

    def __exit__(self, exc_type, exc, traceback):
        return False


class DownloadDirectMeituanDailyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()

    def test_navigation_recovers_late_invitation_without_forced_click(self) -> None:
        page = mock.Mock()
        locator = mock.Mock()
        locator.click.side_effect = [RuntimeError("backdrop intercepts pointer events"), None]
        with mock.patch.object(self.module, "hide_report_marketing_invitation") as hide:
            self.module.click_report_navigation(page, locator)
        self.assertEqual(hide.call_count, 2)
        self.assertEqual(locator.click.call_args_list, [mock.call(timeout=15_000)] * 2)

    def test_navigation_preserves_unrelated_errors(self) -> None:
        page = mock.Mock()
        locator = mock.Mock()
        locator.click.side_effect = RuntimeError("Target page has been closed")
        with mock.patch.object(self.module, "hide_report_marketing_invitation"), self.assertRaisesRegex(RuntimeError, "closed"):
            self.module.click_report_navigation(page, locator)
        locator.click.assert_called_once()

    def test_navigation_stops_if_unknown_overlay_remains(self) -> None:
        page = mock.Mock()
        locator = mock.Mock()
        locator.click.side_effect = RuntimeError("unknown modal intercepts pointer events")
        with mock.patch.object(self.module, "hide_report_marketing_invitation"), self.assertRaisesRegex(RuntimeError, "unknown modal"):
            self.module.click_report_navigation(page, locator)
        self.assertEqual(locator.click.call_count, 2)

    def test_generation_passes_store_customer_paid_field_to_export(self):
        frame = mock.Mock()
        frame.evaluate.return_value = {'success': True, 'customerPaidField': '12031'}
        with mock.patch.object(self.module, 'goto_report_page', return_value=frame), mock.patch.object(self.module, 'meituan_customer_paid_field', return_value='12031'):
            self.assertTrue(self.module.generate_report(mock.Mock(), {}, '20261012'))
        self.assertEqual(frame.evaluate.call_args.args[1]['customerPaidField'], '12031')
        self.assertIn('fieldSet.add(customerPaidField)', frame.evaluate.call_args.args[0])

    def test_report_generation_maintenance_is_temporary(self) -> None:
        result = {"success": False, "code": 100045, "message": "维护中"}
        self.assertTrue(self.module.report_generation_temporarily_unavailable(result))

    def test_daily_report_pause_is_active_until_resume_date(self) -> None:
        account = {
            "id": "direct_chaoyangmen",
            "stores": ["朝阳门店"],
            "daily_report_pause_until": "2026-07-11",
            "daily_report_pause_reason": "客服确认维护中。",
        }
        pause = self.module.daily_report_pause(account, today=date(2026, 7, 10))
        self.assertIsNotNone(pause)
        self.assertIn("朝阳门店", self.module.pause_message(pause))
        self.assertIsNone(self.module.daily_report_pause(account, today=date(2026, 7, 11)))

    def test_report_date_match_does_not_accept_creation_date(self) -> None:
        stale = "门店_全部门店_20260809_20260809_user_2026-08-10 08_07_41"
        current = "门店_全部门店_20260810_20260810_user_2026-08-11 08_07_41"
        self.assertFalse(self.module.report_name_matches_target(stale, "20260810"))
        self.assertTrue(self.module.report_name_matches_target(current, "20260810"))

    def test_run_continues_to_download_when_submit_reports_maintenance(self) -> None:
        fake_page = object()
        fake_context = mock.Mock()
        fake_context.pages = [fake_page]
        expected_path = ROOT / "business-report-dashboard" / "data" / "direct" / "raw" / "report.csv"

        with mock.patch.object(self.module, "load_account", return_value={"id": "direct_chaoyangmen"}), \
            mock.patch.object(self.module, "require_playwright", return_value=FakeSyncPlaywright()), \
            mock.patch.object(self.module, "launch_context", return_value=(fake_context, False)), \
            mock.patch.object(self.module, "generate_report", return_value=False) as generate_report, \
            mock.patch.object(self.module, "validate_basic_daily_file"), \
            mock.patch.object(self.module, "download_latest", return_value=expected_path) as download_latest:
            path = self.module.run("direct_chaoyangmen", "20260706", True, False, 1, None)

        self.assertEqual(path, expected_path)
        generate_report.assert_called_once_with(fake_page, {"id": "direct_chaoyangmen"}, "20260706")
        download_latest.assert_called_once_with(fake_page, fake_context, {"id": "direct_chaoyangmen"}, "20260706")
        fake_context.close.assert_not_called()

    def test_generation_timeout_uses_backup_and_continues_other_accounts(self) -> None:
        timeout = TimeoutError("报表生成中")
        with mock.patch.object(self.module, "load_account", side_effect=lambda account_id: {"id":account_id}), \
             mock.patch.object(self.module, "run", side_effect=[timeout, Path("/tmp/second.csv")]) as run, \
             mock.patch.object(self.module, "run_business_fallback", return_value=Path("/tmp/backup.json")) as fallback:
            failures = self.module.run_accounts(["first", "second"], "20261014", True, False, 1, None)
        self.assertEqual(failures, [])
        self.assertEqual(run.call_count, 2)
        fallback.assert_called_once()
        self.assertEqual(fallback.call_args.args[:2], ("first", "20261014"))

    def test_normal_report_does_not_use_fallback(self):
        with mock.patch.object(self.module, "load_account", return_value={}), \
             mock.patch.object(self.module, "run", return_value=Path("/tmp/report.csv")), \
             mock.patch.object(self.module, "run_business_fallback") as fallback:
            self.assertEqual(self.module.run_accounts(["first"], "20261014", True, False, 1, None), [])
        fallback.assert_not_called()

    def test_both_paths_failed_are_reported(self):
        with mock.patch.object(self.module, "load_account", return_value={}), \
             mock.patch.object(self.module, "run", side_effect=RuntimeError("限流")), \
             mock.patch.object(self.module, "run_business_fallback", side_effect=RuntimeError("登录失效")):
            result = self.module.run_accounts(["first"], "20261014", True, False, 1, None)
        self.assertEqual(len(result), 1)
        self.assertIn("报表和经营数据页均失败", result[0])

    def test_header_only_report_is_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"empty.csv"
            path.write_text("日期,门店名称,营业收入,有效订单\n",encoding="utf-8-sig")
            with self.assertRaises(RuntimeError):self.module.validate_basic_daily_file(path,{},"20261014")


if __name__ == "__main__":
    unittest.main()
