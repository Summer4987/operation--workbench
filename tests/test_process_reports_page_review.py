import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'business-report-dashboard'))
spec = importlib.util.spec_from_file_location('report_page_regression', ROOT / 'business-report-dashboard/process_reports.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class PageReviewPersistenceTests(unittest.TestCase):
    def review_summary(self):
        return {'source': 'review_pages', 'target_date': '2026-10-24', 'stores': {
            '朝阳门店': {'date': '2026-10-24', 'bad_reviews': [{'content': '肉嚼不动 <script>alert(1)</script>'}], 'platforms': {
                '饿了么': {'status': 'ready', 'negative_count': 1, 'bad_reviews': [
                    {'review_id': '41879022715', 'date': '2026-10-24', 'rating': 1.0, 'content': '肉嚼不动 <script>alert(1)</script>', 'replied': False}]},
                '美团': {'status': 'ready', 'negative_count': 0, 'bad_reviews': []}}},
            '其他门店': {'platforms': {'饿了么': {'status': 'ready', 'bad_reviews': [{'content': '其他门店内容'}]}}}}}

    def test_page_review_content_is_visible_in_summary_and_store_page(self):
        summary = self.review_summary()
        self.assertIn('肉嚼不动', module.store_review_note(summary, '朝阳门店'))
        payload = dict(target_stores=['朝阳门店'], source_dates=['2026-10-24'], generated_at='2026-10-25 13:00:00', review_summary=summary,
                       records=[dict(date='2026-10-24', platform='饿了么', store='朝阳门店', **{metric: 1 for metric in module.METRICS})])
        with tempfile.TemporaryDirectory() as tmp, patch.object(module, 'DASHBOARD_DIR', Path(tmp)):
            paths = module.write_store_reports(payload)
            page = paths[0].read_text()
        self.assertIn('昨日差评明细', page)
        self.assertIn('data-review-id="41879022715"', page)
        self.assertIn('淘宝闪购', page)
        self.assertIn('1 星 · 待回复', page)
        self.assertIn('&lt;script&gt;', page)
        self.assertNotIn('<script>alert(1)</script>', page)
        self.assertNotIn('其他门店内容', page)

    def test_incomplete_collection_is_distinct_from_zero_reviews(self):
        summary = self.review_summary()
        summary['stores']['朝阳门店']['platforms']['饿了么']['status'] = 'failed'
        page = module.store_review_details(summary, '朝阳门店')
        self.assertIn('评价采集未完成', page)
        self.assertNotIn('data-review-id=', page)
        self.assertEqual(page.count('昨日未发现 1–3 星差评'), 1)

    def test_process_persists_page_reviews_and_renders(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / 'data'
            summary = {'source': 'evaluation_page', 'stores': []}
            with patch.multiple(module, DATA_DIR=data, RAW_DIR=Path(tmp)/'raw'), \
                 patch.object(module, 'load_config', return_value={'target_stores': []}), \
                 patch.object(module, 'build_alias_lookup', return_value={}), \
                 patch.object(module, 'validate_latest_platform_coverage'), \
                 patch.object(module, 'build_store_summary', return_value=[]), \
                 patch.object(module, 'build_platform_summary', return_value=[]), \
                 patch.object(module, 'read_review_files', return_value=module.pd.DataFrame()), \
                 patch.object(module, 'page_review_summary', return_value=summary), \
                 patch.object(module, 'write_dashboard', return_value=data/'index.html') as render, \
                 patch.object(module, 'write_store_reports', return_value=[]):
                result = module.process(None, None, include_eleme_history=False, include_meituan_history=False)
            self.assertEqual(json.loads((data/'latest.json').read_text())['review_summary'], summary)
            self.assertEqual(result['payload']['review_summary'], summary)
            render.assert_called_once()
