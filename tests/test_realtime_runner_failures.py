"""Run both realtime entry points with isolated collectors and publishers."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RealtimeRunnerFailureTests(unittest.TestCase):
    def test_terminal_state_uses_current_failure(self):
        for installed in [False, True]:
            for collection_rc, deploy_failure, expected_step in [
                (0, 0, None),
                (1, 0, '采集平台实时单量'),
                (0, 1, '发布工作台云端数据'),
                (0, 2, '发布最终工作台状态'),
            ]:
                with self.subTest(installed=installed, collection_rc=collection_rc, deploy_failure=deploy_failure):
                    with tempfile.TemporaryDirectory() as directory:
                        self.check_runner(Path(directory), installed, collection_rc, deploy_failure, expected_step)

    def check_runner(self, tmp_path, installed, collection_rc, deploy_failure, expected_step):
        scripts = tmp_path / 'scripts'
        scripts.mkdir()
        (tmp_path / 'outputs/realtime_order_income').mkdir(parents=True)
        # Deliberately leave a stale collection failure, as on the production host.
        (tmp_path / 'outputs/realtime_order_income/last_failed.json').write_text(json.dumps({
            'summary': {'platform_store_count': 17, 'missing_count': 5},
            'errors': ['饿了么采集不完整：仅完成 6/11 个目标门店'],
        }, ensure_ascii=False))
        for name in ['cleanup_chrome_tabs', 'check_platform_login_preflight', 'build_realtime_collection_status',
                     'build_task_health', 'build_workbench_data', 'ops_notify']:
            (scripts / f'{name}.py').write_text('pass\n')
        (scripts / 'realtime_order_income.py').write_text(f'raise SystemExit({collection_rc})\n')
        records = tmp_path / 'records.jsonl'
        (scripts / 'record_task_run.py').write_text(
            'import json,sys\nfrom pathlib import Path\n'
            f'with Path({str(records)!r}).open("a") as f: f.write(json.dumps(sys.argv[1:])+"\\n")\n'
        )
        deploy = scripts / 'deploy_workbench_to_cloud.zsh'
        deploy.write_text(f'''#!/bin/zsh
    count=0
    [[ ! -f '{tmp_path}/deploy-count' ]] || count=$(cat '{tmp_path}/deploy-count')
    count=$((count + 1))
    echo "$count" > '{tmp_path}/deploy-count'
    [[ "$count" -ne "{deploy_failure}" ]]
    ''')
        user_scripts = tmp_path / 'Library/Scripts/xiong-operation'
        user_scripts.mkdir(parents=True)
        shutil.copy2(deploy, user_scripts / deploy.name)
        if installed:
            source = (ROOT / 'scripts/install_macmini_operation_launchd.zsh').read_text()
            runner = source.split('cat > "$SCRIPT_DIR/run_realtime_order_income.zsh" <<EOF\n', 1)[1].split('\nEOF\n', 1)[0]
            runner = runner.replace('ROOT="${ROOT}"', f'ROOT="{tmp_path}"', 1).replace('\\$', '$')
        else:
            runner = (ROOT / 'scripts/run_realtime_order_income.zsh').read_text()
        # Use the test interpreter and no project-specific PYTHONPATH.
        import sys
        start = runner.index('PYTHON=')
        end = runner.index('TASK_ID=') if not installed else runner.index('export PYTHONUNBUFFERED=')
        runner = runner[:start] + f'PYTHON="{sys.executable}"\n' + runner[end:]
        path = scripts / 'run_realtime_order_income.zsh'
        path.write_text(runner)
        result = subprocess.run(['/bin/zsh', str(path)], env={**os.environ, 'HOME': str(tmp_path),
            'REALTIME_COLLECT_RETRY_ATTEMPTS': '0', 'ALLOW_VPN_PLATFORM_ROUTE': '1'}, capture_output=True, timeout=30)
        events = [json.loads(line) for line in records.read_text().splitlines()]
        terminal = events[-1]
        assert result.returncode == (1 if expected_step else 0), result.stderr.decode()
        assert terminal[1] == ('failed' if expected_step else 'success')
        if expected_step:
            assert terminal[terminal.index('--step') + 1] == expected_step
            message = terminal[terminal.index('--message') + 1]
            if collection_rc:
                assert '6/11' in message
            else:
                assert expected_step in message
                assert '6/11' not in message
                assert '保留上一份成功数据' not in message


if __name__ == "__main__":
    unittest.main()
