import json
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from scripts import platform_account_access as access

HELPER = Path(access.__file__)


def start(root, account='headquarters', wait=1):
    return subprocess.Popen([sys.executable, str(HELPER), 'lease', '--account', account,
        '--state-root', str(root), '--gap-seconds', '0', '--wait-seconds', str(wait)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)


def test_cross_process_account_serialization_and_exit_releases_lock(tmp_path):
    root = tmp_path/'access'
    first = start(root)
    try:
        assert json.loads(first.stdout.readline())['acquired']
        same = start(root, wait=.15)
        try:
            busy=json.loads(same.stdout.readline())
            assert '队列忙' in busy['error'] and busy['code']=='queue_busy'
            assert same.wait(timeout=2) == 73
        finally:
            same.stdin.close()
        independent = start(root, access.account_key('independent'))
        assert json.loads(independent.stdout.readline())['acquired']
        independent.stdin.close(); assert independent.wait(timeout=2) == 0
        first.terminate();first.wait(timeout=2)
        after = start(root)
        assert json.loads(after.stdout.readline())['acquired']
        after.stdin.close();assert after.wait(timeout=2) == 0
    finally:
        if first.poll() is None:
            first.kill();first.wait()


def test_shared_hold_blocks_headquarters_but_not_other_account_and_needs_confirmation(tmp_path):
    c = access.Coordinator(tmp_path/'access', gap_seconds=0, notify=False)
    c.block('headquarters', '安全验证 https://verify.meituan.com/?token=secret')
    assert 'secret' not in c.paths('headquarters')[2].read_text()
    with pytest.raises(access.AccountAccessError), c.lease('headquarters'):
        pass
    with c.lease(access.account_key('independent')):
        pass
    with pytest.raises(ValueError):
        c.release('headquarters', confirmed=False)
    c.release('headquarters', confirmed=True)
    with c.lease('headquarters'):
        pass


def test_existing_chrome_hold_is_the_same_file_read_by_fleet_helper(tmp_path):
    root = tmp_path/'account_access'
    hold = tmp_path/'platform_auth_guard/meituan.json'
    hold.parent.mkdir();hold.write_text(json.dumps({'status':'blocked','reason':'安全验证'}))
    c = access.Coordinator(root, notify=False)
    assert c.pending('headquarters')['reason'] == '安全验证'
    c.release('headquarters', confirmed=True)
    assert json.loads(hold.read_text())['status'] == 'released'


def test_nested_operations_share_one_lease_and_return_exceptions_release(tmp_path):
    c = access.Coordinator(tmp_path/'access', gap_seconds=0, notify=False)
    with pytest.raises(RuntimeError):
        with c.lease('headquarters'):
            with c.lease('headquarters'):
                raise RuntimeError('selector failure')
    assert not c.pending('headquarters')
    with c.lease('headquarters'):
        pass


def test_decorator_does_not_enter_page_while_account_is_blocked(tmp_path):
    c = access.Coordinator(tmp_path/'access', gap_seconds=0, notify=False)
    c.block('headquarters', '安全验证')
    visited=[]
    @access.serialized(lambda: 'headquarters')
    def visit():visited.append(True)
    with patch.object(access,'production_enabled',return_value=True), patch.object(access,'Coordinator',return_value=c):
        with pytest.raises(access.AccountAccessError):visit()
    assert visited == []


def test_queue_wait_is_distinct_from_verification_and_never_creates_auth_hold(tmp_path):
    assert access.AccountQueueBusy.code == 'queue_busy'
    assert access.AccountVerificationRequired.code == 'auth_block'
    c=access.Coordinator(tmp_path/'access',gap_seconds=0,notify=False)
    assert c.pending('headquarters') is None


def test_longxia_waiter_goes_before_ordinary_collector(tmp_path):
    import os
    root=tmp_path/'access'
    first=start(root)
    workers=[]
    try:
        assert json.loads(first.stdout.readline())['acquired']
        ordinary=start(root,wait=3);workers.append(ordinary)
        high=subprocess.Popen([sys.executable,str(HELPER),'lease','--account','headquarters','--state-root',str(root),'--gap-seconds','0','--wait-seconds','3','--priority','longxia'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True);workers.append(high)
        deadline=time.monotonic()+2
        while not list(root.glob('*.longxia.*.json')) and time.monotonic()<deadline:time.sleep(.01)
        assert list(root.glob('*.longxia.*.json'))
        first.stdin.close();first.wait(timeout=2)
        assert json.loads(high.stdout.readline())['acquired']
        state=json.loads((root/'headquarters.access.json').read_text());assert state['priority']=='longxia'
        high.stdin.close();high.wait(timeout=2)
        assert json.loads(ordinary.stdout.readline())['acquired']
        ordinary.stdin.close();ordinary.wait(timeout=2)
        assert not list(root.glob('*.longxia.*.json'))
    finally:
        for p in [first,*workers]:
            if p.poll() is None:p.kill();p.wait()


def test_priority_ticket_does_not_override_verification_hold(tmp_path):
    c=access.Coordinator(tmp_path/'access',gap_seconds=0,notify=False)
    c.block('headquarters','安全验证')
    with pytest.raises(access.AccountVerificationRequired),c.lease('headquarters',priority='longxia'):
        pass
    assert not list(c.root.glob('*.longxia.*.json'))
