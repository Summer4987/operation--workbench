import contextlib
import itertools
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'store-inspection'))
import cdp_direct_meituan_balance as balance


class DirectBalanceLoadingTests(unittest.TestCase):
    def test_attach_uses_new_tab_without_reusing_store_shell(self):
        playwright = mock.Mock()
        browser = mock.Mock()
        browser.contexts = [mock.Mock()]
        with mock.patch.object(balance, 'cdp_available', return_value=True), \
             mock.patch.object(balance, 'connect_store_browser', return_value=browser):
            mode, _, context, page = balance.connect_account(playwright, {'debug_port': 19225}, visible=False)
        self.assertEqual(mode, 'cdp')
        self.assertIs(page, context.new_page.return_value)

    def collect_with_texts(self, texts, wait_seconds):
        page = mock.Mock()
        context = mock.Mock()
        account = {'id': 'direct_wanxiangcheng', 'stores': ['万象城店']}
        manager = contextlib.nullcontext(mock.Mock())
        with mock.patch.object(balance, 'require_playwright', return_value=lambda: manager), \
             mock.patch.object(balance, 'connect_account', return_value=('cdp', mock.Mock(), context, page)), \
             mock.patch.object(balance, 'body_text', side_effect=texts) as read, \
             mock.patch.object(balance.time, 'time', side_effect=itertools.count()):
            items, _ = balance.collect_account(account, visible=False, wait_seconds=wait_seconds)
        page.close.assert_called_once()
        context.close.assert_not_called()
        return items, page, read

    def test_balance_labels_do_not_end_wait_before_amount_arrives(self):
        items, page, read = self.collect_with_texts(['账户余额 立即充值', '账户余额 19.76 元'], 20)
        self.assertEqual(items[0]['balance'], 19.76)
        self.assertNotIn('error', items[0])
        self.assertEqual(read.call_count, 2)
        page.reload.assert_not_called()

    def test_missing_promotion_app_reloads_once(self):
        items, page, _ = self.collect_with_texts(['商家首页 门店推广', '账户余额 0 元'], 2)
        self.assertEqual(items[0]['balance'], 0)
        self.assertNotIn('error', items[0])
        page.reload.assert_called_once()


if __name__ == '__main__':
    unittest.main()
