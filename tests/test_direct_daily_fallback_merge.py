import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'business-report-dashboard'))
import process_direct_reports as direct
import pandas as pd


def row(source, income=10, date='2026-10-14'):
    return dict(date=date,platform='美团',store='银泰城店',store_raw='银泰城店',income=income,orders=1,
                source=source,old_customer_order_conversion=None,new_customer_order_conversion=None)


class DirectFallbackMergeTests(unittest.TestCase):
    def test_recovered_official_report_replaces_fallback_including_real_zero(self):
        data=direct.merge_daily_frames([pd.DataFrame([row('business_page_fallback')]),pd.DataFrame([row('report_download',0)])],['银泰城店'])
        self.assertEqual(len(data),1)
        self.assertEqual(data.iloc[0]['source'],'report_download')
        self.assertEqual(data.iloc[0]['income'],0)

    def test_older_official_report_cannot_replace_newer_fallback(self):
        data=direct.merge_daily_frames([pd.DataFrame([row('business_page_fallback')]),pd.DataFrame([row('report_download',20,'2026-10-13')])],['银泰城店'])
        latest=data[data['date']=='2026-10-14'].iloc[0]
        self.assertEqual(latest['source'],'business_page_fallback')
        self.assertTrue(pd.isna(latest['old_customer_order_conversion']))

    def test_newly_recovered_platform_is_excluded_from_growth_comparison(self):
        import json, re, subprocess, shutil
        source=(Path(__file__).resolve().parents[1]/"business-report-dashboard/process_reports.py").read_text()
        function=re.search(r"    function comparableRecords\(current, previous\) \{\{.*?\n    \}\}",source,re.S).group(0).replace("{{","{").replace("}}","}")
        current=[dict(store="A",platform="美团",income=100),dict(store="A",platform="饿了么",income=110),dict(store="B",platform="美团",income=50)]
        previous=[dict(store="A",platform="饿了么",income=100),dict(store="B",platform="美团",income=50)]
        node=shutil.which("node") or str(Path.home()/".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node")
        result=subprocess.check_output([node,"-e",function+";console.log(JSON.stringify(comparableRecords("+json.dumps(current)+","+json.dumps(previous)+")));"],text=True)
        rows=json.loads(result)
        self.assertEqual(sum(r["income"] for r in rows),160)
        self.assertFalse(any(r["store"]=="A" and r["platform"]=="美团" for r in rows))

    def test_empty_report_never_overwrites_fallback_with_zero(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'empty.csv';path.write_text('日期,门店名称,营业收入,有效订单\n2026-10-14,银泰城店,,\n',encoding='utf-8-sig')
            config=direct.load_config()
            with self.assertRaises(direct.base.EmptyDailyReportError):
                direct.read_valid_meituan(path,config,direct.base.build_alias_lookup(config))

if __name__=='__main__':unittest.main()
