import importlib.util
import sys
import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'store-inspection'))
spec=importlib.util.spec_from_file_location('balance_retry_test',ROOT/'store-inspection/cdp_meituan_balance.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class BalanceRetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        guard_patch = patch.object(module.cdp.auth_guard, 'STATE_DIR', Path(self.temp.name))
        guard_patch.start()
        self.addCleanup(guard_patch.stop)

    def test_only_failed_store_retries_in_new_tab(self):
        context=Mock(); main_page=Mock(url='https://e.waimai.meituan.com/'); fresh_page=Mock(url='https://e.waimai.meituan.com/')
        context.new_page.side_effect=[main_page,fresh_page]
        with patch.object(module,'STORES',[{'name':'甲'},{'name':'乙'}]), \
             patch.object(module,'recent_meituan_promo_url',return_value='https://example.test'), \
             patch.object(module.cdp,'load_config',return_value={}), \
             patch.object(module.cdp,'connect_browser',return_value=(Mock(),Mock())), \
             patch.object(module.cdp,'first_context',return_value=context), \
             patch.object(module.cdp,'reusable_page',return_value=main_page), \
             patch.object(module.cdp,'disconnect_browser'), \
             patch.object(module,'collect_store',side_effect=[({'balance':10},[]),({'error':'unavailable'},[]),({'balance':20},[])]) as collect:
            items,_,_=module.collect_balances()
        self.assertEqual([x['balance'] for x in items],[10,20])
        self.assertEqual(collect.call_count,3)
        self.assertIs(collect.call_args.args[0],fresh_page)
        fresh_page.close.assert_called_once()
        main_page.close.assert_called_once()

    def test_pending_verification_skips_browser_and_all_stores(self):
        module.cdp.auth_guard.block('美团', '安全验证')
        with patch.object(module.cdp, 'connect_browser') as connect, patch.object(module, 'collect_store') as collect:
            with self.assertRaises(module.cdp.auth_guard.PlatformAuthBlocked):
                module.collect_balances()
        connect.assert_not_called()
        collect.assert_not_called()
