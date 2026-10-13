from __future__ import annotations

import importlib.util
import pathlib
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

from openpyxl import Workbook


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

    def run_paid_field_metadata(self, metadata):
        frame = mock.Mock()
        self.module.meituan_customer_paid_field(frame)
        javascript = frame.evaluate.call_args.args[0]
        harness = """
const metadata = """ + json.dumps(metadata, ensure_ascii=False) + """;
global.performance = {getEntriesByType: () => [{name: 'https://example.test/gw/bizdata/report/download/tab?acctId=test&wmPoiId=-1'}]};
global.fetch = async (url, options) => {
  if (new URL(url).pathname !== '/gw/bizdata/report/data') throw Error('wrong endpoint');
  if (options.method !== 'POST' || new URLSearchParams(options.body).get('type') !== '1') throw Error('wrong report type');
  return {json: async () => metadata};
};
(""" + javascript + """)().then(value => process.stdout.write(JSON.stringify({value}))).catch(error => process.stdout.write(JSON.stringify({error: error.message})));
"""
        result = subprocess.run(['/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node', '-e', harness], text=True, capture_output=True, check=True)
        return json.loads(result.stdout)

    def test_store_metadata_selects_total_paid_not_average_or_no_coupon(self):
        result = self.run_paid_field_metadata({'success': True, 'data': {'modules': [{'list': [
            {'id': 32319, 'name': '顾客实付（不含券）'},
            {'id': 12033, 'name': '实付单均价'},
            {'id': 12031, 'name': '顾客实付'},
        ]}]}})
        self.assertEqual(result, {'value': '12031'})

    def test_missing_total_paid_does_not_substitute_other_metric(self):
        result = self.run_paid_field_metadata({'success': True, 'data': {'modules': [{'list': [
            {'id': 32319, 'name': '顾客实付（不含券）'},
            {'id': 12033, 'name': '实付单均价'},
        ]}]}})
        self.assertIn('缺少顾客实付总额', result['error'])

    def test_maintenance_metadata_preserves_download_fallback(self):
        self.assertEqual(self.run_paid_field_metadata({'success': False, 'code': 100045, 'message': '维护中'}), {'value': None})

    def test_old_report_without_paid_column_is_not_accepted_as_new_export(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'report.csv'
            path.write_text('日期,营业收入,有效订单\n20261012,1539.99,57\n', encoding='gb18030')
            with self.assertRaisesRegex(RuntimeError, '未包含顾客实付'):
                self.module.validate_meituan_customer_paid_file(path)
            path.write_text('日期,营业收入,有效订单,顾客实付\n20261012,1539.99,57,1800\n', encoding='gb18030')
            self.module.validate_meituan_customer_paid_file(path)

    def test_meituan_report_date_ignores_export_timestamp(self):
        matches = self.module.meituan_report_name_matches_target
        self.assertFalse(matches("门店_全部门店_20261011_20261011_xxx_2026-10-12+08_13_29.csv", "20261012"))
        self.assertTrue(matches("门店_全部门店_20261012_20261012_xxx_2026-10-13+08_13_29.csv", "20261012"))
        self.assertFalse(matches("门店_全部门店_20261011_20261012_xxx.csv", "20261012"))

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

    def test_validate_eleme_report_rejects_header_only_workbook(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "eleme.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "data"
            sheet.append(["日期", "门店名称", "订单量"])
            workbook.save(path)

            with self.assertRaisesRegex(self.module.EmptyReportError, "只有表头"):
                self.module.validate_eleme_report_file(path, "20260805")

    def test_validate_eleme_report_accepts_target_date_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "eleme.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "data"
            sheet.append(["日期", "门店名称", "订单量"])
            sheet.append(["2026-08-05", "安贞店", 12])
            workbook.save(path)

            self.assertEqual(self.module.validate_eleme_report_file(path, "20260805"), 1)

    def test_validate_eleme_report_ignores_stale_worksheet_dimension(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "eleme.xlsx"
            rewritten = pathlib.Path(directory) / "rewritten.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "data"
            sheet.append(["日期", "门店名称", "订单量"])
            sheet.append(["2026-08-05", "安贞店", 12])
            workbook.save(path)

            with zipfile.ZipFile(path, "r") as source, zipfile.ZipFile(rewritten, "w") as target:
                for item in source.infolist():
                    content = source.read(item.filename)
                    if item.filename == "xl/worksheets/sheet1.xml":
                        content = content.replace(b'<dimension ref="A1:C2"/>', b'<dimension ref="A1:A1"/>')
                    target.writestr(item, content)

            self.assertEqual(self.module.validate_eleme_report_file(rewritten, "20260805"), 1)

    def test_wait_for_eleme_report_returns_empty_export_immediately(self) -> None:
        with mock.patch.object(
            self.module,
            "download_eleme_latest",
            side_effect=self.module.EmptyReportError("empty"),
        ) as download:
            with self.assertRaises(self.module.EmptyReportError):
                self.module.wait_for_eleme_report("20260805", timeout_seconds=180)
        download.assert_called_once_with("20260805")


if __name__ == "__main__":
    unittest.main()
