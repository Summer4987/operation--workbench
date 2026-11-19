"""Wake the existing Longxia app and wait for current-day account snapshots."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import socket
import subprocess
import time

from longxia_promo_snapshot import read_balance_items, SNAPSHOT_PATH

APP = Path.home() / 'Applications/龙虾店长16店测试.app'


def readiness(*, path=None, config_path=None, now=None):
    now = int(time.time()*1000) if now is None else now
    path = Path(path or SNAPSHOT_PATH)
    items, issues = read_balance_items(path=path, config_path=config_path, now=now)
    try:
        data = json.loads(path.read_text())
        at = data.get('generatedAt')
        fresh = type(at) is int and -60000 <= now-at <= 90000
        paused = {r['name'] for r in data.get('stores', []) if r.get('paused')} if fresh else set()
    except (OSError, ValueError, TypeError, KeyError):
        paused = set()
    pending = [r for r in issues if r.get('store_name') not in paused]
    return {'ready': bool(items) and not pending, 'confirmed_count': len(items),
            'pending': pending, 'paused': [r for r in issues if r.get('store_name') in paused]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start-only', action='store_true')
    parser.add_argument('--check', action='store_true', help='Read snapshots only; do not launch anything')
    parser.add_argument('--timeout', type=int, default=600)
    args = parser.parse_args()
    if not args.check:
        if 'mini' not in socket.gethostname().lower():
            raise SystemExit('余额预读仅允许在 Mac mini 生产主机执行。')
        if not APP.is_dir():
            raise SystemExit('未安装龙虾店长，无法完成上午余额预读。')
        subprocess.run(['/usr/bin/open', '-g', str(APP)], check=True, timeout=15)
        if args.start_only:
            print('已唤起现有龙虾店长；由原有轮询只读预读余额，未启动预算或出价任务。')
            return 0
    deadline = time.monotonic() + (0 if args.check else args.timeout)
    while True:
        result = readiness()
        if result['ready'] or time.monotonic() >= deadline:
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result['ready'] else 1
        time.sleep(5)


if __name__ == '__main__':
    raise SystemExit(main())
