#!/usr/bin/env python3
"""Bounded, local ADB/OCR customer collection. Production Mac mini only.

No model service or MacBook connection is needed. All clicks follow a freshly
observed screen; ambiguous UI and challenges fail closed. Runtime stays private.
"""
import argparse
from datetime import date, datetime
import fcntl
import hashlib
import json
import os
import re
from pathlib import Path
import signal
import subprocess
import time
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from customer_inspection_capture import Capture, PACKAGES, compact, header_valid, category_target
from customer_inspection_results import write_json, publish, RUNTIME

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'config/customer-inspection-rotation.json'
ACCEPTED = {'visually_accepted', 'ocr_verified'}


def plan(day, config):
    groups = config['groups']
    names = [s['name'] for g in groups for s in g['stores']]
    if len(groups) != 4 or any(len(g['stores']) != 4 for g in groups) or len(set(names)) != 16:
        raise ValueError('Rotation must contain exactly 16 distinct stores in four groups')
    offset = (date.fromisoformat(day) - date.fromisoformat(config['anchor_date'])).days
    if offset < 0:
        raise ValueError('Date precedes rotation anchor')
    return groups[offset % 4]


def identity(text, store, platform):
    aliases = {'朝阳门店': ['朝阳门', '第B2档口'],
               '中关村店': ['中关村', '第3档口'] if platform == 'meituan' else ['中关村', '第2号档口'],
               '清河店': ['清河', '第4号档口'], '丽泽店': ['丽泽', '第13档口']}
    return any(compact(a) in compact(text) for a in aliases.get(store, [store.removesuffix('店')]))


def location_control(rows, platform):
    control = next((r for r in rows if r['y'] < 450 and any(w in compact(r['text'])
                    for w in ('切换地址','收货地址','配送至'))),None)
    if control: return control
    # MT renders this two-line control as two independent OCR boxes.
    switch = next((r for r in rows if compact(r['text']) == '切换' and r['x'] > 850 and r['y'] < 300),None)
    if switch and any(compact(r['text']) == '地址' and abs(r['x']-switch['x']) < 60
                      and abs(r['y']-switch['y']) < 100 for r in rows): return switch
    if platform == 'taobao-shangou':
        return next((r for r in rows if 870 < r['x'] < 1070 and 100 < r['y'] < 220
                     and len(compact(r['text'])) >= 2 and '搜索' not in r['text']),None)
    return None


class Navigator(Capture):
    def __init__(self, args, store):
        super().__init__(args)
        self.store = store
        self.sequence = 0
        self.proof = None

    def observe(self):
        self.sequence += 1
        path, rows = self.screen(f'nav-{self.sequence:02d}.png')
        # OCR and challenge checks happen before any next action.
        return path, rows

    def pause(self, seconds=1):
        if time.monotonic() - self.started + seconds >= self.args.timeout:
            raise TimeoutError('门店时间上限，跳过继续')
        time.sleep(seconds)

    def click(self, row):
        self.tap(row['x'], row['y']); self.pause()

    def back(self):
        self.foreground()
        self.command(self.adb + ['shell', 'input', 'keyevent', '4']); self.pause()

    def swipe(self):
        self.foreground()
        self.command(self.adb + ['shell', 'input', 'swipe', '350', '2100', '350', '850', '450'])
        self.pause()

    def type_text(self, value):
        self.foreground()
        self.command(self.adb + ['shell', 'ime', 'set', 'com.android.adbkeyboard/.AdbIME'])
        self.pause()
        self.command(self.adb + ['shell', 'am', 'broadcast', '-a', 'ADB_CLEAR_TEXT'])
        self.command(self.adb + ['shell', 'am', 'broadcast', '-a', 'ADB_INPUT_TEXT', '--es', 'msg', value])
        self.command(self.adb + ['shell', 'input', 'keyevent', '66'])
        self.pause(2)

    @staticmethod
    def find(rows, words, predicate=lambda r: True):
        return next((r for r in rows if predicate(r) and any(w in compact(r['text']) for w in words)), None)

    def search_results(self):
        # Return to an observed search input; never type into an unconfirmed page.
        for _ in range(7):
            _, rows = self.observe()
            if header_valid(rows):
                self.back(); continue
            if self.find(rows,['选择收货地址','搜索地址','热门城市']):
                self.back(); continue
            field = self.find(rows, ['搜索', '搜一搜'], lambda r: 90 < r['y'] < 380 and 180 < r['x'] < 1080)
            if field is not None and field['x'] > 900:
                # MT homepage OCR labels the right-hand submit button, while
                # the input contains a changing promoted query. Focus the
                # observed text in that same row instead of submitting it.
                field = next((r for r in rows if 100 < r['x'] < 850
                              and abs(r['y']-field['y']) < 60), field)
            if field is None:
                field = self.find(rows, ['熊小小'], lambda r: 90 < r['y'] < 220 and 300 < r['x'] < 850)
            if field:
                self.click(field)
                _, focused = self.observe()
                query = next((r for r in focused if 110 < r['y'] < 380 and 130 < r['x'] < 850
                              and not any(w in r['text'] for w in ('历史','热门','首页','收货地址'))),None)
                if query is None: raise RuntimeError('搜索输入框打开后未确认，不输入关键词')
                self.click(query); self.type_text('熊小小'); return
            self.back()
        raise RuntimeError('无法定位已核实的商家搜索入口')

    def address(self):
        # Search-result location controls are safer than a guessed homepage tap.
        _, rows = self.observe()
        switch = location_control(rows,self.args.platform)
        if switch is None:
            raise RuntimeError('搜索结果没有可确认的地址切换入口')
        self.click(switch)
        _, rows = self.observe()
        if not self.find(rows, ['选择收货地址', '选择地址', '新增地址', '搜索地址']):
            raise RuntimeError('地址选择页未确认')
        city = next((r for r in rows if r['x'] < 210 and 200 < r['y'] < 410
                     and any(compact(r['text']).startswith(c) for c in ['成都','北京','武汉','杭州','长沙'])), None)
        if city is None:
            raise RuntimeError('地址页城市控件无法确认')
        if self.store['city'] not in city['text']:
            self.click(city)
            _, rows = self.observe()
            target = next((r for r in rows if compact(r['text']).rstrip('市') == self.store['city'] and r['y'] > 300), None)
            if target is None:
                raise RuntimeError('城市选择页没有目标城市；不盲点')
            self.click(target)
            _, rows = self.observe()
        field = self.find(rows, ['搜索', '输入地址', '小区', '写字楼'], lambda r: 190 < r['y'] < 420 and r['x'] > 220)
        if field is None:
            raise RuntimeError('地址搜索框无法确认')
        self.click(field)
        # MT opens a separate address-search page; focus its observed field.
        _, rows = self.observe()
        field = self.find(rows, ['搜索', '输入', '小区', '写字楼'], lambda r: 180 < r['y'] < 420 and r['x'] > 220)
        if field: self.click(field)
        self.type_text(self.store['address'])
        _, rows = self.observe()
        target = self.find(rows, [compact(self.store['address'])], lambda r: 430 < r['y'] < 1800)
        if target is None:
            raise RuntimeError('地址搜索结果不匹配目标地标')
        self.click(target)
        # A selected POI is only a delivery reference, not proof of store identity.
        self.search_results()

    def merchant(self):
        for _ in range(4):
            path, rows = self.observe()
            row = next((r for r in rows if 300 < r['y'] < 2100 and '熊小小牛排饭' in compact(r['text'])
                        and identity(r['text'], self.args.store, self.args.platform)), None)
            if row:
                self.proof = dict(text=row['text'], screenshot=path.name)
                self.click(row); self.pause(2)
                return
            self.swipe()
        raise RuntimeError('有限搜索内没有找到准确门店，未使用其他门店替代')

    def collect(self):
        self.command(self.adb + ['shell', 'monkey', '-p', PACKAGES[self.args.platform], '-c', 'android.intent.category.LAUNCHER', '1'])
        self.pause(2)
        self.search_results()
        # First try the current location, reducing address changes. One location retry.
        try:
            self.merchant()
        except RuntimeError as exc:
            if '有限搜索' not in str(exc): raise
            self.address(); self.merchant()
        first, rows = self.observe()
        if not header_valid(rows):
            expand = self.find(rows, ['点餐', '点菜'], lambda r: r['x'] < 210 and r['y'] < 650)
            if expand is None: raise RuntimeError('进店顶部满减未确认')
            self.click(expand)
            first, rows = self.observe()
        if not header_valid(rows): raise RuntimeError('店名/顶部红包满减不完整，未通过核验')
        # Reject an explicitly different visible suffix even if search entry was correct.
        headings = [r['text'] for r in rows if '熊小小牛排饭' in compact(r['text'])]
        for heading in headings:
            if ('店)' in compact(heading) or '店）' in compact(heading)) and not identity(heading, self.args.store, self.args.platform):
                raise RuntimeError('店头与搜索结果身份不一致')
        first_bytes = first.read_bytes()
        category = category_target(rows)
        if category is None:
            self.swipe(); _, rows = self.observe(); category = category_target(rows)
        if category is None: raise RuntimeError('牛排饭STEAK分类未找到')
        self.click(category)
        second, rows = self.observe()
        text = compact(' '.join(r['text'] for r in rows))
        if not category_target(rows) or not any(v in text for v in ('五花','板腱','嫩肩','选购指南')) or not (any(v in text for v in ('¥','￥')) or re.search(r'\d+\.\d',text)):
            raise RuntimeError('分类商品/价格无法核验')
        files = []
        for name, data in [('01-first-screen.png', first_bytes), ('02-steak-category.png', second.read_bytes())]:
            target = self.directory / name; target.write_bytes(data)
            files.append(dict(path=str(target.relative_to(Path(self.args.output))), sha256=hashlib.sha256(data).hexdigest()))
        write_json(self.directory / 'identity-evidence.json', self.proof)
        return dict(status='ocr_verified', files=files, note='本机OCR自动核验；具名搜索入口、店头优惠、分类点击及商品价格。未人工逐图复核。')


def preflight(config):
    adb = Path.home() / 'Library/Android/sdk/platform-tools/adb'
    result = subprocess.run([str(adb), '-s', config['serial'], 'get-state'], capture_output=True, timeout=15)
    if result.returncode or result.stdout.strip() != b'device': raise RuntimeError('安卓手机离线或未授权')
    processes = subprocess.run(['/bin/ps','-axo','command='],capture_output=True,text=True,check=True,timeout=10).stdout.splitlines()
    if any(('cainiao_logistics' in p or 'cainiao-logistics' in p) and not any(x in p for x in ('launchctl','install_','grep','ps -')) for p in processes):
        raise RuntimeError('手机正被菜鸟采集占用，跳过本次以避免跨任务点击')
    return adb


def execute(day, config, retry_failed=False):
    group = plan(day, config)
    expected = {(p,s['name']) for s in group['stores'] for p in PACKAGES}
    existing = set()
    for prior in RUNTIME.glob(f'{day}*/reviewed-progress.json'):
        data = json.loads(prior.read_text())
        existing.update((r['platform'],r['store']) for r in data['records'] if r['status'] in ACCEPTED)
    if expected <= existing:
        print('当天4店双平台已有完整结果，不重复采集'); return
    source = RUNTIME / f'{day}-daily-four'
    source.mkdir(parents=True, exist_ok=True)
    manifest = source / 'reviewed-progress.json'
    # Calendar retries never replay an already attempted batch, including partials.
    if manifest.exists() and not retry_failed:
        print('今日批次已执行，不自动重复换地址；补采使用 --retry-failed'); publish(source); return
    prior_records = {}
    if manifest.exists():
        prior = json.loads(manifest.read_text())
        archive = source / ('attempt-' + datetime.now().strftime('%H%M%S%f') + '.json')
        write_json(archive, prior)
        prior_records = {(r['platform'], r['store']): r for r in prior['records']}
    records = [dict(platform=p,store=s['name'],status='not_attempted',note='计划内，尚未采集') for s in group['stores'] for p in PACKAGES]
    for i, record in enumerate(records):
        previous = prior_records.get((record['platform'], record['store']))
        if previous and previous['status'] in ACCEPTED:
            records[i] = previous
    report = dict(date=day, records=records, limitations=['每日4店轮换；每店双平台最多5分钟，重试最多一次。', '验证码停止该平台；轮换覆盖不代表全部采集成功。', 'OCR自动核验记录没有人工逐图复核；地址仅为配送参考位置。'])
    def save():
        report['updated_at'] = datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
        write_json(source/'progress.json', report)
    blocked = {}
    try:
        adb = preflight(config)
        for store in group['stores']:
            remaining = config['store_budget_seconds']
            for platform in PACKAGES:
                record = next(r for r in records if r['store'] == store['name'] and r['platform'] == platform)
                if record['status'] in ACCEPTED:
                    continue
                if platform in blocked:
                    record.update(status='blocked_human_verification', note=blocked[platform]); continue
                started = time.monotonic()
                args = SimpleNamespace(adb=str(adb),serial=config['serial'],platform=platform,store=store['name'],output=str(source),timeout=min(config['pair_budget_seconds'],remaining))
                collector = Navigator(args, store)
                try:
                    # OS alarm also enforces the deadline during hung OCR/ADB/sleeps.
                    signal.alarm(max(1, int(args.timeout)))
                    record.update(collector.collect())
                except (RuntimeError,TimeoutError,ValueError,subprocess.SubprocessError,OSError) as exc:
                    text = str(exc)
                    if 'verification required' in text:
                        blocked[platform] = '验证码/账户保护暂停该平台，未绕过验证'
                        record.update(status='blocked_human_verification',note=blocked[platform])
                    else: record.update(status='recapture_needed',note=text[:240])
                finally:
                    signal.alarm(0)
                    if record['status'] in ACCEPTED:
                        for temporary in collector.directory.glob('nav-*.png'):
                            temporary.unlink(missing_ok=True)
                    record['elapsed_seconds'] = round(time.monotonic()-started,1)
                    remaining = max(0,remaining-record['elapsed_seconds'])
                    save()
    except (RuntimeError,subprocess.SubprocessError,OSError) as exc:
        for record in records:
            if record['status'] == 'not_attempted': record.update(status='recapture_needed',note=str(exc)[:240])
    save()
    write_json(manifest, report)
    write_json(source/'finished.json',dict(date=day,completed=sum(r['status'] in ACCEPTED for r in records),planned=8))
    publish(source)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--retry-failed', action='store_true', help='补采当天未成功项，保留成功项和旧批次记录')
    parser.add_argument('--plan', action='store_true')
    parser.add_argument('--preflight', action='store_true')
    parser.add_argument('--date', default=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat())
    args = parser.parse_args()
    config = json.loads(CONFIG.read_text()); group = plan(args.date,config)
    if args.plan:
        print(json.dumps(dict(date=args.date,time=config['time'],group=group),ensure_ascii=False,indent=2)); return
    if args.preflight:
        preflight(config); print('设备已授权；轮换配置有效；未操作平台'); return
    if args.date != datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat():
        parser.error('生产采集仅允许当天；历史日期只能查看 --plan')
    RUNTIME.mkdir(parents=True,exist_ok=True)
    with (RUNTIME/'daily-four.lock').open('w') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: print('巡查任务正在运行'); return
        def timeout(signum,frame): raise TimeoutError('每店双平台5分钟硬上限；该平台未完成')
        signal.signal(signal.SIGALRM,timeout)
        execute(args.date,config,retry_failed=args.retry_failed)


if __name__ == '__main__': main()
