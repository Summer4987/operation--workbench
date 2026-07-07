from __future__ import annotations

import importlib.util
import sys
import unittest
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

    def test_report_generation_maintenance_is_temporary(self) -> None:
        result = {"success": False, "code": 100045, "message": "维护中"}
        self.assertTrue(self.module.report_generation_temporarily_unavailable(result))

    def test_run_continues_to_download_when_submit_reports_maintenance(self) -> None:
        fake_page = object()
        fake_context = mock.Mock()
        fake_context.pages = [fake_page]
        expected_path = ROOT / "business-report-dashboard" / "data" / "direct" / "raw" / "report.csv"

        with mock.patch.object(self.module, "load_account", return_value={"id": "direct_chaoyangmen"}), \
            mock.patch.object(self.module, "require_playwright", return_value=FakeSyncPlaywright()), \
            mock.patch.object(self.module, "launch_context", return_value=(fake_context, False)), \
            mock.patch.object(self.module, "generate_report", return_value=False) as generate_report, \
            mock.patch.object(self.module, "download_latest", return_value=expected_path) as download_latest:
            path = self.module.run("direct_chaoyangmen", "20260706", True, False, 1, None)

        self.assertEqual(path, expected_path)
        generate_report.assert_called_once_with(fake_page, {"id": "direct_chaoyangmen"}, "20260706")
        download_latest.assert_called_once_with(fake_page, fake_context, {"id": "direct_chaoyangmen"}, "20260706")
        fake_context.close.assert_not_called()


if __name__ == "__main__":
    unittest.main()
