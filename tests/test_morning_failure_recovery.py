import contextlib
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.morning_recovery_state import RecoveryState

ROOT = Path(__file__).resolve().parents[1]


def test_checkpoints_never_reuse_yesterday_or_another_budget_period(tmp_path):
    path = tmp_path/'state.json'
    state = RecoveryState(path, day='2026-11-02', period='午餐', mode='commit', started=1)
    state.record('美团午餐预算真实提交', True)
    same = RecoveryState(path, day='2026-11-02', period='午餐', mode='commit', started=2, resume=True)
    assert same.completed('美团午餐预算真实提交')
    assert same.data['started'] == 1
    assert not same.completed('美团预算提交前登录态复核')
    next_day = RecoveryState(path, day='2026-11-03', period='午餐', mode='commit', started=3, resume=True)
    assert not next_day.completed('美团午餐预算真实提交')


def test_preview_checkpoint_never_authorizes_commit(tmp_path):
    path = tmp_path/'state.json'
    state = RecoveryState(path, day='2026-11-02', period='午餐', mode='preview', started=1)
    state.record('美团午餐预算真实提交', True)
    commit = RecoveryState(path, day='2026-11-02', period='午餐', mode='commit', started=2, resume=True)
    assert not commit.completed('美团午餐预算真实提交')


def test_headquarters_failure_does_not_abort_healthy_collection_or_eleme_budget(tmp_path):
    spec = importlib.util.spec_from_file_location('morning_failure_recovery', ROOT/'morning-ops/run_morning_ops.py')
    ops = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = ops
    spec.loader.exec_module(ops)
    calls = []
    formal = []
    def result(name, rc=0):
        return SimpleNamespace(name=name, returncode=rc, output='平台访问超时' if rc else '', log_path=tmp_path/'run.log')
    def run(name, *a, **kw):
        calls.append(name)
        return result(name, 66 if name in ['总部平台登录态预检','美团预算提交前登录态复核'] else 0)
    def submit(name, *a, **kw):
        formal.append(name)
        return result(name)
    with contextlib.ExitStack() as stack:
        stack.enter_context(patch.object(sys, 'argv', ['run','--mode','commit']))
        stack.enter_context(patch.object(ops, 'WORKSPACE', tmp_path))
        stack.enter_context(patch.object(ops, 'morning_ops_lock', return_value=contextlib.nullcontext()))
        for name in ['cleanup_chrome_sessions','refresh_final_status','ensure_backend_chrome','record_task_run','flush_result_notifications','publish_budget_result','publish_final_status']:
            stack.enter_context(patch.object(ops, name))
        stack.enter_context(patch.object(ops, 'run_step', side_effect=run))
        stack.enter_context(patch.object(ops, 'run_step_with_pause', side_effect=submit))
        assert ops.main() == 1
    assert '直营双平台客服消息采集' in calls
    assert '运营总看板发布腾讯云' in calls
    assert any(name.startswith('饿了么') and '预算真实提交' in name for name in formal)
    assert not any(name.startswith('美团') and '预算真实提交' in name for name in formal)


def test_resume_does_not_repeat_a_successful_real_budget_submission(tmp_path):
    spec = importlib.util.spec_from_file_location('morning_resume_execution', ROOT/'morning-ops/run_morning_ops.py')
    ops = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = ops
    spec.loader.exec_module(ops)
    state = RecoveryState(tmp_path/'state.json', day='2026-11-02', period='午餐', mode='commit', started=1)
    state.record('美团午餐预算真实提交', True)
    with patch.object(ops, 'RECOVERY', state), patch.object(ops, 'LOG_DIR', tmp_path), \
         patch.object(ops, 'record_task_run'), patch.object(ops.subprocess, 'run') as execute:
        result = ops.run_step('美团午餐预算真实提交', ['would-submit'])
    assert result.returncode == 0
    execute.assert_not_called()
