import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'store-inspection'))
spec=importlib.util.spec_from_file_location('balance_retry_test',ROOT/'store-inspection/cdp_meituan_balance.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class BalanceRetryTests(unittest.TestCase):
    def test_only_failed_store_retries_in_new_tab(self):
        context=Mock(); main_page=Mock(); fresh_page=context.new_page.return_value
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
