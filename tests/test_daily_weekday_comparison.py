import importlib.util
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('weekly_reports', ROOT/'business-report-dashboard/process_reports.py')
reports = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reports)


def row(date, income, rate=.4, platform='美团'):
    return dict(date=date, store='中关村', platform=platform, income=income,
                orders=100, impressions=1000, customer_paid=income,
                customer_paid_orders=100, old_customer_orders=70,
                new_customer_orders=30, visit_conversion=.1, order_conversion=rate)


def payload():
    return dict(generated_at='2026-10-20 08:00:00', target_stores=['中关村'],
                source_dates=['2026-10-12', '2026-10-18', '2026-10-19'],
                records=[row('2026-10-12', 100, .4), row('2026-10-18', 50, .7),
                         row('2026-10-19', 80, .3)], warnings=[])


class WeekdayComparisonTests(unittest.TestCase):
    def test_exact_weekday_and_missing_dates(self):
        self.assertEqual(reports.previous_report_date(payload(), '2026-10-19'), '2026-10-12')
        self.assertIsNone(reports.previous_report_date({'source_dates':['2026-10-11','2026-10-18','2026-10-19']}, '2026-10-19'))
        for current, previous in [('2026-01-03','2025-12-27'), ('2024-03-03','2024-02-25')]:
            self.assertEqual(reports.previous_report_date({'source_dates':[current, previous]}, current), previous)

    def test_same_platform_population_and_weekly_anomalies(self):
        p=payload();p['records'].append(row('2026-10-12', 500, platform='饿了么'))
        current, previous, date=reports.common_platform_records(p, '中关村', '2026-10-19')
        self.assertEqual(date, '2026-10-12')
        self.assertEqual([r['platform'] for r in previous], ['美团'])
        self.assertAlmostEqual(reports.pct_change(current[0]['income'],previous[0]['income']), -.2)
        self.assertTrue(any('收入较上周同日下降 20.0%' in x['title'] for x in reports.build_focus_items(p,'中关村','2026-10-19')))

    def test_rendered_store_and_browser_date_selection(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(reports,'DASHBOARD_DIR',Path(tmp)):
            p=payload();html=reports.write_store_reports(p)[0].read_text()
            self.assertIn('对比基准（上周同日）',html);self.assertIn('<b>2026-10-12</b>',html)
            self.assertIn('-20.0%',html);self.assertIn('-10.0个百分点',html);self.assertNotIn('-40.0个百分点',html)
            dashboard=reports.write_dashboard(p).read_text()
            self.assertNotIn('较前日',dashboard)
            js=re.search(r'function previousDate\(date\) \{[\s\S]*?\n    \}',dashboard).group(0)
            node=shutil.which('node')
            if node:
                code="const datesAsc=['2025-12-27','2026-01-03','2026-10-11','2026-10-18','2026-10-19'];"+js+";console.log(JSON.stringify([previousDate('2026-10-19'),previousDate('2026-01-03')]));"
                self.assertEqual(json.loads(subprocess.check_output([node,'-e',code])),[None,'2025-12-27'])
            p['source_dates'].remove('2026-10-12');p['records']=[r for r in p['records'] if r['date']!='2026-10-12']
            self.assertIn('上周同日无可比数据',reports.write_store_reports(p)[0].read_text())

    def test_render_existing_replaces_cached_daily_diagnoses(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(reports,'DASHBOARD_DIR',Path(tmp)/'dashboard'), patch.object(reports,'page_review_summary',return_value=None):
            p=payload();p['focus_items']=[{'title':'旧的前日诊断'}];p['all_store_diagnoses']=[]
            path=Path(tmp)/'latest.json';path.write_text(json.dumps(p))
            reports.render_existing_payload(path)
            saved=json.loads(path.read_text());self.assertTrue(saved['all_store_diagnoses'])
            self.assertTrue(any('收入较上周同日下降 20.0%' in x['title'] for x in saved['focus_items']))

if __name__=='__main__':unittest.main()
