"""Cross-process Meituan account leases shared by Chrome jobs and Longxia.

The lock covers the entire read/write/verification operation, never credentials.
Kernel locks are released on process exit. Verification holds require confirmation.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import functools
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
import threading
from datetime import datetime
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
STATE_ROOT = ROOT / 'outputs/account_access'
FLEET_ROOT = Path.home() / 'Library/Application Support/xiong-dianjin-fleet-test'
HEADQUARTERS = 'headquarters'
_HELD = {}


class AccountAccessError(RuntimeError):
    code = 'coordination_error'


class AccountQueueBusy(AccountAccessError):
    code = 'queue_busy'


class AccountVerificationRequired(AccountAccessError):
    code = 'auth_block'


def production_enabled():
    return (sys.platform == 'darwin' and 'mini' in socket.gethostname().lower()
            and ROOT.resolve() == (Path.home() / 'Library/Application Support/xiong-operation/production').resolve())


def account_key(value):
    return 'account-' + hashlib.sha256(str(value).encode()).hexdigest()[:24]


def for_port(port):
    if int(port) == 9222:
        return HEADQUARTERS
    accounts = json.loads((ROOT / 'config/direct_meituan_accounts.json').read_text())['accounts']
    account = next(a for a in accounts if int(a.get('debug_port', 0)) == int(port))
    profiles = json.loads((FLEET_ROOT / 'profiles.json').read_text())['profiles']
    matches = [p for p in profiles if p['name'] in account.get('stores', [])]
    keys = set()
    for p in matches:
        binding = json.loads((FLEET_ROOT / p['stateFile']).read_text())['config']['fleet']['binding']['key']
        keys.add(account_key(binding.split('|')[0]))
    if len(keys) != 1:
        raise AccountAccessError('美团账号身份未唯一匹配，停止访问')
    return keys.pop()


def for_direct(account_id):
    accounts = json.loads((ROOT / 'config/direct_meituan_accounts.json').read_text())['accounts']
    return for_port(next(a['debug_port'] for a in accounts if a['id'] == account_id))


def for_task(task):
    return for_direct(task['directMeituanAccountId']) if task.get('directMeituanAccountId') else HEADQUARTERS


class Coordinator:
    def __init__(self, root=STATE_ROOT, *, gap_seconds=20, notify=None):
        self.root = Path(root)
        self.gap = gap_seconds
        self.notify = production_enabled() if notify is None else notify

    def paths(self, account):
        if not re.fullmatch(r'headquarters|account-[a-f0-9]{24}', account):
            raise ValueError('Invalid account key')
        hold = self.root.parent / 'platform_auth_guard/meituan.json' if account == HEADQUARTERS else self.root / (account + '.hold.json')
        return self.root / (account + '.lock'), self.root / (account + '.access.json'), hold

    def pending(self, account):
        p = self.paths(account)[2]
        if not p.exists():
            return None
        d = json.loads(p.read_text())
        return d if d.get('status') == 'blocked' else None

    def require(self, account):
        if self.pending(account):
            raise AccountVerificationRequired('美团同账号安全验证待人工确认；所有程序暂停该账号，不自动重试')

    @staticmethod
    def write(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + f'.{os.getpid()}.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        os.chmod(tmp, 0o600)
        tmp.replace(path)

    def block(self, account, reason):
        _, _, path = self.paths(account)
        reason = re.sub(r'https?://\S+', '[平台链接]', str(reason))[:500]
        data = self.pending(account) or dict(status='blocked', detected_at=datetime.now().isoformat(timespec='seconds'),
            reason=reason, resume_requires='manual_verification_confirmation')
        self.write(path, data)
        if self.notify and not data.get('notified_at'):
            text = ('【美团｜同账号安全验证暂停】\n' + reason + '\n龙虾店长与采集任务已共同暂停该账号；独立账号不受影响。'
                    '\n请在 Mac mini 完成验证，再确认恢复该账号。')
            try:
                r = subprocess.run([sys.executable, str(ROOT/'scripts/ops_notify.py'), text], capture_output=True, timeout=15)
                if r.returncode == 0:
                    data['notified_at'] = datetime.now().isoformat(timespec='seconds')
                    self.write(path, data)
            except (OSError, subprocess.TimeoutExpired):
                pass
        return data

    def release(self, account, *, confirmed):
        if not confirmed:
            raise ValueError('必须明确确认人工验证完成')
        self.write(self.paths(account)[2], dict(status='released', confirmed_at=datetime.now().isoformat(timespec='seconds')))

    @contextlib.contextmanager
    def priority_request(self, account, priority):
        if priority != 'longxia':
            yield
            return
        path = self.root / f'{account}.longxia.{os.getpid()}.{threading.get_ident()}.json'
        self.write(path, dict(pid=os.getpid(), requested_at=time.time()))
        try:
            yield
        finally:
            path.unlink(missing_ok=True)

    def longxia_waiting(self, account):
        for path in self.root.glob(account + '.longxia.*.json'):
            try:
                pid = json.loads(path.read_text())['pid']
                os.kill(int(pid), 0)
                return True
            except ProcessLookupError:
                path.unlink(missing_ok=True)
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return False

    @contextlib.contextmanager
    def lease(self, account, *, wait_seconds=120, check_auth=True, priority="normal"):
        token = (os.getpid(), threading.get_ident(), str(self.root.resolve()), account)
        if token in _HELD:
            if check_auth:
                self.require(account)
            yield
            return
        lockpath, accesspath, _ = self.paths(account)
        lockpath.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + wait_seconds
        with self.priority_request(account, priority), lockpath.open('a+') as lock:
            while True:
                if check_auth:
                    self.require(account)
                acquired = False
                if priority == 'longxia' or not self.longxia_waiting(account):
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        acquired = True
                    except BlockingIOError:
                        pass
                if acquired:
                    last = json.loads(accesspath.read_text()) if accesspath.exists() else {}
                    delay = max(0, min(self.gap, last.get('finished_at', 0) + self.gap - time.time()))
                    # Never occupy the account while cooling down. A Longxia
                    # request may arrive during that wait and must go first.
                    if delay or (priority != 'longxia' and self.longxia_waiting(account)):
                        fcntl.flock(lock, fcntl.LOCK_UN)
                    else:
                        break
                if time.monotonic() >= deadline:
                    raise AccountQueueBusy('美团同账号访问队列忙，龙虾店长优先，其他任务等待空闲后执行')
                time.sleep(.1)
            try:
                if check_auth:
                    self.require(account)
                self.write(accesspath, dict(pid=os.getpid(), priority=priority, started_at=time.time(), finished_at=last.get('finished_at', 0)))
                _HELD[token] = True
                try:
                    yield
                finally:
                    _HELD.pop(token, None)
                    self.write(accesspath, dict(pid=None, priority=priority, finished_at=time.time()))
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)



@contextlib.contextmanager
def optional_lease(account):
    if account is None or not production_enabled():
        yield
    else:
        with Coordinator().lease(account):
            yield


def serialized(resolve):
    """Protect the complete business operation; nested calls share its lease."""
    def decorate(fn):
        @functools.wraps(fn)
        def run(*args, **kwargs):
            if not production_enabled():
                return fn(*args, **kwargs)
            account = resolve(*args, **kwargs)
            if account is None:
                return fn(*args, **kwargs)
            coordinator = Coordinator()
            with coordinator.lease(account):
                try:
                    return fn(*args, **kwargs)
                except Exception as exc:
                    # Transport and selectors must not be misclassified as verification.
                    from platform_auth_guard import is_auth_failure
                    if is_auth_failure(exc) and not isinstance(exc, AccountAccessError):
                        coordinator.block(account, str(exc))
                    raise
        return run
    return decorate


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action', choices=['lease', 'status', 'block', 'release'])
    ap.add_argument('--account', default=HEADQUARTERS)
    ap.add_argument('--state-root', type=Path, default=STATE_ROOT)
    ap.add_argument('--wait-seconds', type=float, default=120)
    ap.add_argument('--gap-seconds', type=float, default=20)
    ap.add_argument('--priority', choices=['normal', 'longxia'], default='normal')
    ap.add_argument('--reason', default='美团安全验证')
    ap.add_argument('--confirmed', action='store_true')
    args = ap.parse_args()
    c = Coordinator(args.state_root, gap_seconds=args.gap_seconds,
                    notify=production_enabled() and args.state_root == STATE_ROOT)
    try:
        if args.action == 'lease':
            with c.lease(args.account, wait_seconds=args.wait_seconds, priority=args.priority):
                print(json.dumps({'acquired': True}), flush=True)
                # EOF on the parent's pipe or process exit releases the kernel lock.
                sys.stdin.buffer.read()
        elif args.action == 'block':
            c.block(args.account, args.reason)
        elif args.action == 'release':
            c.release(args.account, confirmed=args.confirmed)
        else:
            print(json.dumps(c.pending(args.account) or {'status': 'released'}, ensure_ascii=False))
    except (AccountAccessError, ValueError) as exc:
        print(json.dumps({'error': str(exc), 'code': getattr(exc, 'code', 'coordination_error')}), flush=True)
        return 73
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
