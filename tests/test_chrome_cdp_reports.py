from __future__ import annotations

import importlib.util
import pathlib
import sys
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "business-report-dashboard" / "chrome_cdp_reports.py"


def load_module():
    spec = importlib.util.spec_from_file_location("chrome_cdp_reports_for_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ChromeCdpReportsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module()

    def test_process_reports_without_explicit_inputs_auto_discovers_daily_files(self) -> None:
        with mock.patch.object(self.module.subprocess, "run") as run:
            self.module.process_reports()
        args = run.call_args.args[0]
        self.assertNotIn("--allow-missing-platform", args)

    def test_process_reports_with_one_missing_platform_is_explicitly_partial(self) -> None:
        with mock.patch.object(self.module.subprocess, "run") as run:
            self.module.process_reports(eleme=pathlib.Path("eleme.xlsx"))
        args = run.call_args.args[0]
        self.assertIn("--allow-missing-platform", args)
        self.assertIn("--eleme", args)


if __name__ == "__main__":
    unittest.main()
