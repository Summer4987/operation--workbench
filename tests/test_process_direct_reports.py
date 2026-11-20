#!/usr/bin/env python3
from __future__ import annotations

import errno
from unittest.mock import patch
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "business-report-dashboard" / "process_direct_reports.py"


def load_module():
    module_dir = str(SCRIPT_PATH.parent)
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)
    spec = importlib.util.spec_from_file_location("process_direct_reports_for_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ProcessDirectReportsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module()

    def test_temporary_cloud_file_read_error_retries_but_never_hides_failure(self):
        with patch.object(self.module.base, 'read_eleme', side_effect=[OSError(errno.EDEADLK,'busy'), ('frame',[])]) as read, patch.object(self.module.time,'sleep'):
            self.assertEqual(self.module.read_eleme_with_retry(Path('a.xlsx'),{},{}),('frame',[]))
            self.assertEqual(read.call_count,2)
        with patch.object(self.module.base,'read_eleme',side_effect=OSError(errno.EDEADLK,'busy')), patch.object(self.module.time,'sleep'):
            with self.assertRaisesRegex(OSError,'a.xlsx'):
                self.module.read_eleme_with_retry(Path('a.xlsx'),{},{})

    def test_yesterday_report_requires_all_stores_and_both_platforms(self):
        payload=dict(target_stores=['A'],source_dates=['2026-11-19'],records=[dict(date='2026-11-19',store='A',platform=p) for p in ['饿了么','美团']])
        self.module.validate_daily_coverage(payload,'2026-11-19')
        payload['records'].pop()
        with self.assertRaisesRegex(ValueError,'美团'):
            self.module.validate_daily_coverage(payload,'2026-11-19')

    def test_process_writes_structured_outputs_without_raw_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            dashboard_dir = root / "direct-dashboard"
            legacy_dir = root / "legacy-data"
            original_values = {
                "CHAIN_RAW_DIR": self.module.CHAIN_RAW_DIR,
                "DIRECT_RAW_DIR": self.module.DIRECT_RAW_DIR,
                "DATA_DIR": self.module.DATA_DIR,
                "DIRECT_DASHBOARD_DIR": self.module.DIRECT_DASHBOARD_DIR,
                "LEGACY_CHAIN_RAW_DIR": self.module.LEGACY_CHAIN_RAW_DIR,
                "LEGACY_DIRECT_RAW_DIR": self.module.LEGACY_DIRECT_RAW_DIR,
                "LEGACY_DATA_DIR": self.module.LEGACY_DATA_DIR,
                "read_review_files": self.module.base.read_review_files,
            }
            try:
                self.module.CHAIN_RAW_DIR = root / "raw"
                self.module.DIRECT_RAW_DIR = root / "direct" / "raw"
                self.module.DATA_DIR = data_dir
                self.module.DIRECT_DASHBOARD_DIR = dashboard_dir
                self.module.LEGACY_CHAIN_RAW_DIR = legacy_dir / "raw"
                self.module.LEGACY_DIRECT_RAW_DIR = legacy_dir / "direct" / "raw"
                self.module.LEGACY_DATA_DIR = legacy_dir
                self.module.base.read_review_files = lambda alias_lookup: pd.DataFrame()

                result = self.module.process()
            finally:
                for name, value in original_values.items():
                    if name == "read_review_files":
                        self.module.base.read_review_files = value
                    else:
                        setattr(self.module, name, value)

            payload = result["payload"]
            self.assertEqual(payload["records"], [])
            self.assertEqual(len(payload["store_summary"]), len(payload["target_stores"]))
            self.assertTrue((data_dir / "direct-latest.json").exists())
            self.assertTrue((data_dir / "direct_unified_daily.csv").exists())
            self.assertTrue((data_dir / "direct_unified_reviews.csv").exists())
            self.assertTrue((dashboard_dir / "index.html").exists())


if __name__ == "__main__":
    unittest.main()
