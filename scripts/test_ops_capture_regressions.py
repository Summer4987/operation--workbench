import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from collect_review_pages import satisfaction_response
from collect_customer_messages import save_media


class CaptureRegressionTests(unittest.TestCase):
    def test_satisfaction_wait_ignores_inflight_all_and_other_star_pages(self):
        def response(kind, score='SERVICE_SCORES', page=1):
            return ({'params': {'rateQuery': dict(rateType=kind, scoreType=score, currentPage=page)}}, {})
        self.assertIsNone(satisfaction_response(response('ALL'), 'BAD_REVIEW'))
        self.assertIsNone(satisfaction_response(response('BAD_REVIEW', 'TASTE_SCORES'), 'BAD_REVIEW'))
        self.assertIsNone(satisfaction_response(response('MEDIUM_REVIEW'), 'BAD_REVIEW'))
        self.assertIsNone(satisfaction_response(response('BAD_REVIEW', page=2), 'BAD_REVIEW'))
        expected = response('BAD_REVIEW')
        self.assertIs(satisfaction_response(expected, 'BAD_REVIEW'), expected)
        self.assertIsNotNone(satisfaction_response(response('MEDIUM_REVIEW'), 'MEDIUM_REVIEW'))

    def test_meituan_special_card_uses_actual_message_dom_id(self):
        page = Mock()
        card = page.locator.return_value
        card.inner_text.return_value = '平台特殊卡片'
        card.screenshot.return_value = b'png-evidence'
        message = dict(id='1806546406103781378', timestamp='2026-10-20 11:46:08', needs_review=True, media=[])
        scope = dict(store='保利中心店', platform='美团', date='2026-10-20')
        with tempfile.TemporaryDirectory() as tmp, patch('collect_customer_messages.OUT', Path(tmp)):
            save_media(page, scope, dict(messages=[message]))
            page.locator.assert_called_once_with('.message-item[id="1806546406103781378"]')
            self.assertEqual(message['capture_mode'], 'screenshot')
            self.assertFalse(message['needs_review'])
            self.assertTrue((Path(tmp)/scope['date']/message['media'][0]['file']).is_file())

    def test_missing_special_card_stays_incomplete(self):
        page = Mock()
        page.locator.return_value.inner_text.side_effect = TimeoutError()
        message = dict(id='missing', timestamp='2026-10-20 11:46:08', needs_review=True, media=[])
        save_media(page, dict(store='保利中心店', platform='美团', date='2026-10-20'), dict(messages=[message]))
        self.assertTrue(message['needs_review'])
        self.assertIn('capture_error', message)
        self.assertEqual(message['media'], [])


if __name__ == '__main__':
    unittest.main()
