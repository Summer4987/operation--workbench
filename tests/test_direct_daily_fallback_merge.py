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

    def test_empty_report_never_overwrites_fallback_with_zero(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'empty.csv';path.write_text('日期,门店名称,营业收入,有效订单\n2026-10-14,银泰城店,,\n',encoding='utf-8-sig')
            config=direct.load_config()
            with self.assertRaises(direct.base.EmptyDailyReportError):
                direct.read_valid_meituan(path,config,direct.base.build_alias_lookup(config))

if __name__=='__main__':unittest.main()
