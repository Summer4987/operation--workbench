import unittest
from contextlib import ExitStack
from unittest import mock
from test_meituan_budget_cdp import load_module, FakeContext


class MinimumBudgetTest(unittest.TestCase):
    def setUp(self):
        self.module = load_module()

    def execute(self, target, *, commit=True, preflight=False):
        module = self.module
        context = FakeContext([])
        page = context.new_page()
        page.url = 'https://example.test/'
        task = {'targetBudget': target, 'store': '五一广场店', 'keyword': '五一广场', 'wmPoiId': '32744963'}
        with ExitStack() as stack:
            for name, value in {
                'task_paused': False, 'task_control': {},
                'open_headquarters_budget_page': (page, False, page.url),
                'enter_dianjin_with_recovery': None, 'close_budget_modal': None,
                'wait_setting_ready': {'rangeMax': 1}, 'read_budget': 120,
                'assert_promo_page_targets_task': None, 'wait_budget': 120,
                'spent_exceeds_target': (False, 0), 'open_budget_modal': None,
                'budget_input_locator': mock.Mock(input_value=mock.Mock(return_value='120')),
                'confirm_button_locator': object(),
            }.items():
                stack.enter_context(mock.patch.object(module, name, return_value=value))
            prepare = stack.enter_context(mock.patch.object(module, 'prepare_budget_form', return_value=('120', str(max(50, target)), 1)))
            save = stack.enter_context(mock.patch.object(module, 'confirm_budget_with_recovery', return_value=(max(50, target), '已保存并读回确认')))
            result = module.execute_task(context, page.url, task, commit=commit, preflight=preflight)
        return result, prepare, save

    def test_below_minimum_is_saved_and_verified_at_minimum(self):
        for requested in [35, 42, 48, 49, 50, 56]:
            with self.subTest(requested=requested):
                result, prepare, save = self.execute(requested)
                self.assertTrue(result['ok'], result)
                self.assertFalse(result.get('skipped', False))
                self.assertEqual(result['requestedTargetBudget'], requested)
                self.assertEqual(result['targetBudget'], max(50, requested))
                self.assertEqual(result['afterBudget'], max(50, requested))
                self.assertEqual(result['minimumBudgetApplied'], requested < 50)
                self.assertEqual(prepare.call_args.args[1], max(50, requested))
                self.assertEqual(save.call_args.args[1], max(50, requested))

    def test_preview_and_preflight_never_save(self):
        for preflight in [False, True]:
            result, prepare, save = self.execute(48, commit=False, preflight=preflight)
            self.assertTrue(result['ok'], result)
            self.assertEqual(result['targetBudget'], 50)
            save.assert_not_called()
            self.assertEqual(prepare.called, preflight)

    def test_invalid_target_never_opens_platform(self):
        for requested in [0, -1, float('nan'), float('inf')]:
            with self.subTest(requested=requested), mock.patch.object(self.module, 'task_paused', return_value=False), mock.patch.object(self.module, 'task_control', return_value={}), mock.patch.object(self.module, 'open_headquarters_budget_page') as open_page:
                with self.assertRaises(ValueError):
                    self.module.execute_task(None, '', {'targetBudget': requested}, commit=True)
                open_page.assert_not_called()
