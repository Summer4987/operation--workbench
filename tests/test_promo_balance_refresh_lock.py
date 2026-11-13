import fcntl
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


RUNNER = Path(__file__).resolve().parents[1] / 'scripts/run_promo_balance_refresh.zsh'


class PromoBalanceLockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.root = self.home / 'production'
        python = self.root / 'business-report-dashboard/.venv/bin/python'
        python.parent.mkdir(parents=True)
        python.symlink_to(sys.executable)
        self.lock_path = self.root / 'outputs/locks/morning-ops.lock'
        self.lock_path.parent.mkdir(parents=True)
        self.marker = self.root / 'collected'
        for script in ['store-inspection/run_all_balances.py', 'scripts/build_promo_balance_status.py',
                       'scripts/build_task_health.py', 'scripts/build_workbench_data.py']:
            path = self.root / script
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("from pathlib import Path\nPath('collected').touch()\n")
        deploy = self.home / 'Library/Scripts/xiong-operation/deploy_workbench_to_cloud.zsh'
        deploy.parent.mkdir(parents=True)
        deploy.write_text('#!/bin/zsh\nexit 0\n')

    def run_refresh(self):
        env = dict(os.environ, HOME=str(self.home), OPERATION_ROOT=str(self.root))
        return subprocess.run(['/bin/zsh', str(RUNNER)], env=env, capture_output=True,
                              text=True, timeout=10)

    def test_morning_lock_skips_browser_access_and_publication(self):
        with self.lock_path.open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.run_refresh()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.marker.exists())
        logs = list((self.home / 'Library/Logs/xiong-operation/promo_balance_refresh').glob('*.log'))
        self.assertIn('本轮独立余额刷新跳过', logs[0].read_text())

    def test_realtime_collection_uses_the_same_browser_lock(self):
        runner = RUNNER.with_name('run_realtime_order_income.zsh')
        env = dict(os.environ, HOME=str(self.home), OPERATION_ROOT=str(self.root))
        env.pop('OPERATION_REALTIME_LOCK_HELD', None)
        with self.lock_path.open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = subprocess.run(['/bin/zsh', str(runner)], env=env,
                                    capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('本轮实时采集跳过', result.stdout)
        self.assertFalse(self.marker.exists())

    def test_free_lock_runs_refresh_and_releases_both_locks(self):
        result = self.run_refresh()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.marker.exists())
        with self.lock_path.open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.assertFalse((self.home / 'Library/Caches/xiong-operation/promo_balance_refresh.lock').exists())


if __name__ == '__main__':
    unittest.main()
