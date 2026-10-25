import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import cleanup_chrome_tabs as cleanup


class BrowserTaskProtectionTests(unittest.TestCase):
    def test_active_budget_or_collector_prevents_tab_reads_and_closes(self):
        for task in ['meituan_budget_cdp.py', 'collect_customer_messages.py', 'collect_review_pages.py']:
            with self.subTest(task=task), patch.object(cleanup, 'active_browser_tasks', return_value=[task]), \
                 patch.object(cleanup, 'read_json') as read:
                result = cleanup.cleanup_port(9222, dry_run=False, max_per_category=1)
                self.assertTrue(result['skipped'])
                self.assertEqual(result['closed'], [])
                read.assert_not_called()

    def test_inspects_script_arguments_without_matching_log_filenames(self):
        commands = '\n'.join([
            '/usr/bin/python3 "store-inspection/meituan_budget_cdp.py" --mode preview',
            '/usr/bin/python3 scripts/collect_customer_messages.py',
            'tail /tmp/collect_review_pages.py.log',
        ])
        with patch.object(cleanup.subprocess, 'run', return_value=SimpleNamespace(stdout=commands)):
            self.assertEqual(cleanup.active_browser_tasks(), ['collect_customer_messages.py', 'meituan_budget_cdp.py'])

    def test_idle_browser_still_cleans_duplicate_tabs(self):
        tabs = [dict(type='page', id=str(n), url='https://e.waimai.meituan.com/', title='store') for n in range(2)]
        with patch.object(cleanup, 'active_browser_tasks', return_value=[]), \
             patch.object(cleanup, 'read_json', return_value=tabs), patch.object(cleanup, 'urlopen') as close:
            result = cleanup.cleanup_port(9222, dry_run=False, max_per_category=1)
            self.assertEqual(result['closed_count'], 1)
            self.assertEqual(result['kept_count'], 1)
            close.assert_called_once()

    def test_unavailable_process_inspection_defers_cleanup(self):
        with patch.object(cleanup.subprocess, 'run', side_effect=OSError('unavailable')):
            self.assertEqual(cleanup.active_browser_tasks(), ['process_inspection_unavailable'])


if __name__ == '__main__':
    unittest.main()
