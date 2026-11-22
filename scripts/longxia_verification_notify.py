"""Notify the existing WeCom channel from local fleet status; never touch merchant pages."""
from __future__ import annotations

import contextlib
import fcntl
import io
import json
import os
import socket
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

FLEET_ROOT = Path.home() / 'Library/Application Support/xiong-dianjin-fleet-test'
BOARD_URL = 'https://139.155.148.169/operation-workbench/#bidding'


def verification_stores(status, now):
    if not isinstance(status, dict) or status.get('schema') != 1:
        raise ValueError('Invalid fleet status')
    generated = status.get('generatedAt')
    if type(generated) is not int or not -60000 <= now - generated <= 90000:
        raise ValueError('Stale fleet status')
    stores = status.get('stores')
    if not isinstance(stores, list) or not 1 <= len(stores) <= 16 or any(not isinstance(s, dict) or not s.get('id') for s in stores):
        raise ValueError('Invalid store list')
    if len({s['id'] for s in stores}) != len(stores):
        raise ValueError('Duplicate store identity')
    def requires_verification(store):
        reason = str(store.get('message', ''))
        # Account coordinator owns notification/deduplication for these holds.
        if reason.startswith('同账号安全验证暂停'):
            return False
        verification = any(text in reason for text in ('安全验证', '验证码', '页面出现验证或访问限制'))
        offline = any(text in reason for text in ('掉线', '未登录', '重新登录', '登录失效', '登录过期'))
        return ((verification or offline) and (store.get('paused') is True or store.get('status') == 'error')) or store.get('status') in {'error', 'offline', 'login_required', 'auth_required'}
    return {s['id']: s for s in stores if requires_verification(s)}


def incident_kind(store):
    reason = str(store.get('message') or '')
    if any(word in reason for word in ('验证码', '安全验证', '访问限制')):
        return 'verification'
    if store.get('status') in {'offline', 'login_required', 'auth_required'} or any(word in reason for word in ('掉线', '未登录', '重新登录', '登录失效', '登录过期')):
        return 'login'
    return 'fault'


def message(stores, now):
    clock = lambda at: datetime.fromtimestamp(at / 1000, timezone(timedelta(hours=8))).strftime('%m-%d %H:%M:%S')
    lines = ['【龙虾店长｜门店故障/登录验证需处理】']
    for store in stores:
        name = str(store.get('name') or '未命名门店').replace('\n', ' ').replace('\r', ' ')[:40]
        current = '当前显示安全验证' in str(store.get('message', '')) or '当前显示美团安全验证' in str(store.get('message', ''))
        at = store.get('resultAt')
        at = at if type(at) is int and 0 < at <= now else now
        kind = incident_kind(store)
        if kind == 'login':
            detail = '门店掉线或登录失效，请重新登录'
        elif kind == 'fault':
            detail = '门店运行故障：'+str(store.get('message') or '未知故障').replace('\n', ' ')[:160]
        elif current:
            detail = '当前显示验证码'
        elif '曾发生' in str(store.get('message', '')):
            detail = '曾发生验证跳转，需检查当前页面'
        else:
            detail = '检测到验证或访问限制，需人工检查'
        lines.append(f"门店：{name}｜{detail}｜{clock(at)}")
    lines += ['以上门店的自动任务发生故障或受登录验证影响，需要人工处理；其他门店继续运行。',
              '处理：Mac mini → 龙虾店长 → 对应门店「登录 / 设置」，手动完成验证，再点「恢复本店」。',
              '无需停止全部门店巡检。', f'看板：{BOARD_URL}']
    return '\n'.join(lines)


def save_state(path, state):
    temporary = path.with_name(path.name + f'.{os.getpid()}.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        os.chmod(temporary, 0o600)
        json.dump(state, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def process_status(status, state_path, sender, now=None):
    now = int(time.time() * 1000) if now is None else now
    active = verification_stores(status, now)
    state_path = Path(state_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with state_path.with_suffix('.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'checked': False, 'reason': 'busy'}
        state = json.loads(state_path.read_text()) if state_path.exists() else {'schema': 1, 'incidents': {}}
        if state.get('schema') != 1 or not isinstance(state.get('incidents'), dict):
            raise ValueError('Invalid notification state')
        # Only a fresh healthy/resumed status rearms a store. Old snapshots never clear deduplication.
        state['incidents'] = {key: value for key, value in state['incidents'].items() if key in active}
        due = []
        for key, store in active.items():
            kind = incident_kind(store)
            if key in state['incidents'] and state['incidents'][key].get('kind', 'verification') != kind:
                del state['incidents'][key]
            incident = state['incidents'].setdefault(key, {'firstSeenAt': now, 'attempts': 0, 'sentAt': None, 'nextAttemptAt': now})
            incident['kind'] = kind
            if incident['sentAt'] is None and incident['nextAttemptAt'] <= now:
                due.append(store)
        delivered = None
        if due:
            try:
                delivered = sender(message(due, now)) is True
            except Exception:
                delivered = False
            for store in due:
                incident = state['incidents'][store['id']]
                incident['attempts'] += 1
                if delivered:
                    incident['sentAt'] = now
                else:
                    delay = min(300, 30 * 2 ** min(incident['attempts'] - 1, 4))
                    incident['nextAttemptAt'] = now + delay * 1000
            state['lastDelivery'] = {'at': now, 'ok': delivered, 'storeCount': len(due)}
        state['checkedAt'] = now
        save_state(state_path, state)
        return {'checked': True, 'active': len(active), 'attempted': len(due), 'delivered': delivered}


def send_wecom(text):
    import ops_notify
    # Transport exceptions can contain signed webhook URLs; log only our safe receipt below.
    with contextlib.redirect_stderr(io.StringIO()):
        delivered, _ = ops_notify.notify_with_result(text)
    return delivered is True


def check():
    # Retry delivery from the shared account hold even while browser access is paused.
    import platform_account_access as accounts
    if accounts.production_enabled():
        coordinator = accounts.Coordinator()
        keys = ['headquarters'] + [p.name[:-len('.hold.json')] for p in coordinator.root.glob('account-*.hold.json')]
        for key in keys:
            hold = coordinator.pending(key)
            if hold and not hold.get('notified_at'):
                coordinator.block(key, hold.get('reason') or '美团安全验证')
    status = json.loads((FLEET_ROOT / 'fleet-public-status.json').read_text())
    result = process_status(status, FLEET_ROOT / 'fleet-verification-notify.json', send_wecom)
    if result.get('attempted'):
        print(datetime.now().isoformat(timespec='seconds'), '龙虾安全验证企微提醒', json.dumps(result, ensure_ascii=False), flush=True)
    return result


if __name__ == '__main__':
    if 'mini' not in socket.gethostname().lower():
        raise RuntimeError('正式通知只允许在 Mac mini 执行')
    if '--test-notification' in sys.argv:
        delivered = send_wecom('【龙虾店长｜验证码提醒测试】\n企微提醒通道已接通。此消息是通知测试，不代表当前有门店出现验证码。\n今后门店因安全验证暂停时，将自动发送店名和处理步骤；同一次暂停不重复通知。\n看板：' + BOARD_URL)
        print(json.dumps({'testNotification': True, 'delivered': delivered}))
        raise SystemExit(0 if delivered else 1)
    check()
