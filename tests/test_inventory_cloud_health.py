import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from scripts import check_inventory_cloud_health as health
from scripts.ensure_eleme_headquarters_context import wait_for_store_rows


class InventoryHealthTest(unittest.TestCase):
    def test_login_html_is_reported_as_authentication_not_json_syntax(self):
        response = Mock()
        response.geturl.return_value = 'http://example/login?next=/api/summary'
        response.headers = {'Content-Type': 'text/html'}
        with self.assertRaisesRegex(ValueError, '认证'):
            health.decode_summary_response(response)
        response.read.assert_not_called()

    def test_custom_server_never_falls_back_to_production(self):
        with patch.object(health, 'urlopen', side_effect=OSError('offline')), patch.object(health, 'fetch_summary_via_production_ssh') as fallback:
            with self.assertRaises(OSError):
                health.fetch_inventory_summary('http://example', 8)
            fallback.assert_not_called()

    def test_production_auth_fallback_returns_actual_summary(self):
        expected = {'items': [{'name': 'test'}], 'stats': {'product_count': 1}}
        with patch.dict(health.os.environ, {'AI_BUSINESS_CENTER_ENV': 'production'}), patch.object(Path, 'is_file', return_value=True), patch.object(health, 'urlopen', side_effect=ValueError('login')), patch.object(health, 'fetch_summary_via_production_ssh', return_value=expected) as fallback:
            self.assertEqual(health.fetch_inventory_summary(health.DEFAULT_SERVER, 8), expected)
            fallback.assert_called_once_with(8)

    def test_development_never_uses_production_ssh(self):
        with patch.dict(health.os.environ, {'AI_BUSINESS_CENTER_ENV': 'development'}), patch.object(health, 'urlopen', side_effect=OSError('offline')), patch.object(health, 'fetch_summary_via_production_ssh') as fallback:
            with self.assertRaises(OSError):
                health.fetch_inventory_summary(health.DEFAULT_SERVER, 8)
            fallback.assert_not_called()

    def test_ssh_failure_does_not_expose_remote_output(self):
        with patch.object(health.subprocess, 'run', return_value=Mock(returncode=1, stderr='secret', stdout='secret')):
            with self.assertRaisesRegex(RuntimeError, 'SSH') as error:
                health.fetch_summary_via_production_ssh(8)
            self.assertNotIn('secret', str(error.exception))


class PaginationWaitTest(unittest.TestCase):
    def test_slow_second_page_does_not_reuse_first_page_rows(self):
        page = Mock()
        page.locator.return_value.count.return_value = 0
        with patch('scripts.ensure_eleme_headquarters_context.extract_shop_ids', side_effect=[{'1'}, {'1'}, set(), {'2'}]):
            self.assertEqual(wait_for_store_rows(page, {'1'}), {'2'})
        self.assertEqual(page.wait_for_timeout.call_count, 3)

    def test_stuck_page_fails_closed(self):
        page = Mock()
        page.locator.return_value.count.return_value = 0
        with patch('scripts.ensure_eleme_headquarters_context.extract_shop_ids', return_value={'1'}):
            with self.assertRaisesRegex(RuntimeError, '拒绝执行预算'):
                wait_for_store_rows(page, {'1'})
        self.assertEqual(page.wait_for_timeout.call_count, 30)

    def test_loading_indicator_must_finish(self):
        page = Mock()
        page.locator.return_value.count.side_effect = [1, 0]
        with patch('scripts.ensure_eleme_headquarters_context.extract_shop_ids', return_value={'2'}):
            self.assertEqual(wait_for_store_rows(page, {'1'}), {'2'})
        page.wait_for_timeout.assert_called_once_with(500)
