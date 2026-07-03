#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "business-report-dashboard" / "process_reports.py"


def load_module():
    module_dir = str(SCRIPT_PATH.parent)
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)
    spec = importlib.util.spec_from_file_location("process_reports_for_platform_guard_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class DailyPlatformGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module()

    def test_latest_date_requires_both_platforms(self) -> None:
        unified = pd.DataFrame(
            [
                {"date": "2026-07-01", "platform": "饿了么", "store": "安贞"},
                {"date": "2026-07-01", "platform": "美团", "store": "安贞"},
                {"date": "2026-07-02", "platform": "美团", "store": "安贞"},
            ]
        )

        with self.assertRaisesRegex(RuntimeError, "缺少平台：饿了么"):
            self.module.validate_latest_platform_coverage(unified, ["安贞"], context="加盟店日报")

    def test_latest_date_with_both_platforms_passes(self) -> None:
        unified = pd.DataFrame(
            [
                {"date": "2026-07-02", "platform": "饿了么", "store": "安贞"},
                {"date": "2026-07-02", "platform": "美团", "store": "安贞"},
            ]
        )

        self.module.validate_latest_platform_coverage(unified, ["安贞"], context="加盟店日报")


if __name__ == "__main__":
    unittest.main()
