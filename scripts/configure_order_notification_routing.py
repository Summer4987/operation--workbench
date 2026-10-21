#!/usr/bin/env python3
"""Preview/apply cloud order routing using the existing daily-supply notifier.

Run from the Mac mini checkout pulled from GitHub main. No webhook is printed
or stored in Git; the cloud reads its existing running-service configuration.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess

REMOTE_SCRIPT = r'''
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime

apply = '--apply' in sys.argv

def service_env(service):
    pid = subprocess.check_output(['systemctl', 'show', service, '-p', 'MainPID', '--value'], text=True).strip()
    if not pid or pid == '0':
        raise SystemExit(service + ' is not running; no changes made')
    return dict(entry.split('=', 1) for entry in Path('/proc/' + pid + '/environ').read_text().split('\0') if '=' in entry)

def fingerprint(value):
    return hashlib.sha256(value.encode()).hexdigest()[:12] if value else ''

source = service_env('inventory-board.service')
before = service_env('daily-order.service')
target = source.get('ORDER_NOTIFY_WEBHOOK', '').strip()
if source.get('ORDER_NOTIFY_TYPE', '').lower() != 'wecom' or not target.startswith('https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key='):
    raise SystemExit('Daily-supply WeCom target is unavailable; no changes made')
# systemd Environment= supports quoted strings; reject unexpected control syntax.
if any(c in target for c in '\n\r"\\%'):
    raise SystemExit('Unsupported target format; no changes made')

result = {
    'mode': 'apply' if apply else 'preview',
    'store_order_notifications': 'disabled',
    'digest_target': 'existing daily-supply order notification group',
    'target_fingerprint': fingerprint(target),
    'previous_store_target_fingerprint': fingerprint(before.get('DAILY_ORDER_NOTIFY_WEBHOOK', '')),
    'schedule': '18:00 Asia/Shanghai (unchanged)',
}
if apply:
    directory = Path('/etc/systemd/system/daily-order.service.d')
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'zzz-order-notification-routing.conf'
    content = ('# Managed by GitHub main: configure_order_notification_routing.py\n'
               '[Service]\n'
               'UnsetEnvironment=DAILY_ORDER_NOTIFY_WEBHOOK\n'
               'Environment="DAILY_ORDER_WECHAT_NOTIFY_TYPE=wecom"\n'
               'Environment="DAILY_ORDER_WECHAT_NOTIFY_WEBHOOK=' + target + '"\n')
    if path.exists() and path.read_text() != content:
        backup = Path('/var/backups/xiong-operation')
        backup.mkdir(parents=True, exist_ok=True, mode=0o700)
        saved = backup / ('order-notification-routing-' + datetime.now().strftime('%Y%m%d%H%M%S') + '.conf')
        saved.write_bytes(path.read_bytes())
        saved.chmod(0o600)
    # Create with restrictive permissions before writing the secret.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(content)
    path.chmod(0o600)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'restart', 'daily-order.service'], check=True)
    after = service_env('daily-order.service')
    assert not after.get('DAILY_ORDER_NOTIFY_WEBHOOK'), 'Store notifications remain enabled'
    assert after.get('DAILY_ORDER_WECHAT_NOTIFY_WEBHOOK') == target, 'Digest target mismatch'
    assert after.get('DAILY_ORDER_WECHAT_NOTIFY_TYPE') == 'wecom'
    result['running_service_verified'] = True
    result['digest_timer'] = subprocess.check_output(['systemctl', 'is-active', 'daily-order-wechat-digest.timer'], text=True).strip()
print(json.dumps(result, ensure_ascii=False))
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='ubuntu@139.155.148.169')
    parser.add_argument('--apply', action='store_true', help='Persist routing and restart only daily-order.service')
    args = parser.parse_args()
    command = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=12']
    key = Path.home() / '.ssh/xiong_operation_cloud_ed25519'
    if key.exists():
        command.extend(['-i', str(key)])
    command.extend([args.host, 'sudo', 'python3', '-'])
    if args.apply:
        command.append('--apply')
    return subprocess.run(command, input=REMOTE_SCRIPT, text=True, timeout=90).returncode


if __name__ == '__main__':
    raise SystemExit(main())
