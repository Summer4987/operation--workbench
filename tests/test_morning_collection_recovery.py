import contextlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from collect_customer_messages import read_session_with_retry
from scripts import sync_promo_budget_overrides as sync


class MessageRecoveryTests(unittest.TestCase):
    def test_conversation_timeout_retries_without_losing_completed_sessions(self):
        page = Mock()
        read = Mock(side_effect=[TimeoutError('signed URL omitted'), {'history_complete': True, 'messages': []}])
        self.assertTrue(read_session_with_retry(page, read)['history_complete'])
        self.assertEqual(read.call_count, 2)

    def test_incomplete_history_is_retried_but_still_not_marked_complete(self):
        read = Mock(return_value={'history_complete': False})
        self.assertFalse(read_session_with_retry(Mock(), read)['history_complete'])
        self.assertEqual(read.call_count, 2)

    def test_authentication_failure_is_not_retried(self):
        read = Mock(side_effect=RuntimeError('平台要求人工安全验证'))
        with self.assertRaises(RuntimeError):
            read_session_with_retry(Mock(), read)
        read.assert_called_once()


class BudgetConfigurationTests(unittest.TestCase):
    def test_unattended_sync_uses_ssh_without_web_login(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(sync, 'TARGET', Path(tmp)/'budget.json'), \
             patch.object(sync, 'COPY_PATH', ''), patch.object(sync, 'AUTH_PASSWORD', 'configured-without-web-session'), \
             patch.dict(sync.os.environ, {}, clear=True), \
             patch.object(sync, 'read_remote_ssh', return_value={'stores': {'丽泽': {'美团': {'lunchBudget': 120}}}}) as ssh, \
             patch.object(sync, 'read_remote_http') as http:
            self.assertEqual(sync.main(), 0)
            self.assertEqual(json.loads(sync.TARGET.read_text())['stores']['丽泽门店']['美团']['lunchBudget'], 120)
            ssh.assert_called_once()
            http.assert_not_called()

    def test_failed_sync_keeps_last_config_and_reports_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)/'budget.json'
            original = '{"stores":{"old":{"美团":{"lunchBudget":5}}}}'
            target.write_text(original)
            with patch.object(sync, 'TARGET', target), patch.object(sync, 'read_remote_ssh', side_effect=RuntimeError('unavailable')), \
                 patch.object(sync, 'read_remote_http', return_value={'stores': {}}):
                self.assertEqual(sync.main(), 1)
                self.assertEqual(target.read_text(), original)

    def test_morning_sync_failure_blocks_budget_but_allows_collection(self):
        spec = importlib.util.spec_from_file_location('morning_recovery_test', ROOT/'morning-ops/run_morning_ops.py')
        ops = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = ops
        spec.loader.exec_module(ops)
        ok = SimpleNamespace(name='测试步骤', returncode=0, output='', log_path=Path('test.log'))
        failed = SimpleNamespace(name='同步云端预算配置', returncode=1, output='配置同步失败', log_path=Path('test.log'))
        calls = []
        def run(name, *args, **kwargs):
            calls.append(name)
            return failed if name == '同步云端预算配置' else ok
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(sys, 'argv', ['test', '--mode', 'commit']))
            stack.enter_context(patch.object(ops, 'morning_ops_lock', return_value=contextlib.nullcontext()))
            for name in ['cleanup_chrome_sessions', 'refresh_final_status', 'ensure_backend_chrome', 'record_task_run', 'flush_result_notifications', 'publish_budget_result']:
                stack.enter_context(patch.object(ops, name))
            stack.enter_context(patch.object(ops, 'run_step', side_effect=run))
            pause = stack.enter_context(patch.object(ops, 'run_step_with_pause', return_value=ok))
            self.assertEqual(ops.main(), 1)
        self.assertIn('直营双平台客服消息采集', calls)
        self.assertIn('运营总看板数据更新', calls)
        self.assertFalse(any('预算真实提交' in call.args[0] for call in pause.call_args_list))


if __name__ == '__main__':
    unittest.main()
