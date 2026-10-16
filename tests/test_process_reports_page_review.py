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
