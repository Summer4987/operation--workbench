"""Read-only paginated order snapshots using existing Mac mini browser sessions.

No browser is launched and no order, price, budget or account setting is changed.
Raw snapshots contain private operational data and must stay outside Git.
"""
import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

STORES = {
    '安贞店': ('熊小小牛排饭POKEBEAR（安贞店）','熊小小牛排饭POKEBEAR(安贞店)','北京区域'),
    '中关村店': ('熊小小牛排饭POKEBEAR（第3档口吉祥美食城店）','熊小小牛排饭POKEBEAR(第2号档口利康金桥美食城)','北京区域'),
    '清河店': ('熊小小牛排饭POKEBEAR(第4号档口川湘府美食城店)','熊小小牛排饭POKEBEAR(第4号档口川湘府美食城店)','北京区域'),
    '双井店': ('熊小小牛排饭POKEBEAR（双井店）','熊小小牛排饭POKEBEAR(双井店)','北京区域'),
    '金融街店': ('熊小小牛排饭POKEBEAR（金融街店）','熊小小牛排饭POKEBEAR(金融街店)','北京区域'),
    '滨江店': ('熊小小牛排饭POKEBEAR(滨江店)','熊小小牛排饭POKEBEAR(滨江店)','杭州区域'),
    '望京店': ('熊小小牛排饭POKEBEAR（望京店）','熊小小牛排饭POKEBEAR(望京店)','北京区域'),
    '保利中心店': ('熊小小牛排饭POKEBEAR（保利中心店）','熊小小牛排饭POKEBEAR(保利中心店)','成都区域'),
    '银泰城店': ('熊小小牛排饭POKEBEAR（银泰城店）','熊小小牛排饭POKEBEAR(银泰城店)','成都区域'),
    '万象城店': ('熊小小牛排饭POKEBEAR(万象城店)','熊小小牛排饭POKEBEAR(万象城店)','成都区域'),
    '金融城店': ('熊小小牛排饭POKEBEAR(金融城店)','熊小小牛排饭POKEBEAR(金融城店)','成都区域'),
}

def identifiers(text, platform):
    return re.findall(r'订单编号：(\d+)' if platform == 'mt' else r'单号:\n(\d+)', text)

def check_dates(text, platform, date):
    times = re.findall(r'(\d\d-\d\d) [\d:]+下单' if platform == 'mt' else r'下单时间: (\d\d-\d\d) ', text)
    return bool(times) and all(t == date[5:] for t in times)

def wait_snapshot(page, target, platform, date, count=None, previous=None):
    for _ in range(100):
        text = target.locator('body').last.inner_text()
        ids = identifiers(text, platform)
        if ids and check_dates(text, platform, date) and (count is None or len(ids) == count) and (previous is None or ids[0] != previous):
            return text
        page.wait_for_timeout(400)
    raise RuntimeError(f'Stale/incomplete order page: {platform} {date}')

def open_meituan_order_calendar(view):
    from playwright.sync_api import TimeoutError, expect

    control = view.get_by_placeholder('开始时间')
    guide = view.locator('[class*="guideModal_"]').get_by_text('我知道了', exact=True)
    expect(control).to_be_enabled(timeout=11000)
    for timeout in (2500, 4500):
        if guide.is_visible():
            guide.click(timeout=6000)
        try:
            control.click(timeout=timeout)
            return
        except TimeoutError:
            if not guide.is_visible():
                raise
    raise RuntimeError('订单日期筛选仍被页面引导挡住')


def wait_order_total(page, view, platform, date):
    mt = platform == 'mt'
    fields = ('开始时间', '结束时间') if mt else ('开始日期', '结束日期')
    for _ in range(75):
        text = view.locator('body').last.inner_text()
        count_text = text if mt else view.locator('.ant-pagination-total-text').first
        if not mt:
            count_text = count_text.inner_text() if count_text.count() else ''
        count = re.search(r'共\s*(\d+)\s*单' if mt else r'\d+', count_text)
        ids = identifiers(text, platform)
        verified = all(view.get_by_placeholder(label).first.input_value(timeout=2000)[:10] == date
                       for label in fields if view.get_by_placeholder(label).count())
        if count and ids and check_dates(text, platform, date):
            return text, int(count[1] if mt else count[0])
        if verified and not ids and (not count or int(count[1] if mt else count[0]) == 0):
            controls_present = all(view.get_by_placeholder(label).count() for label in fields)
            if controls_present and re.search(r'(?m)^(暂无订单|暂无数据|没有符合条件的订单)$', text):
                return text, 0
        page.wait_for_timeout(400)
    raise RuntimeError(f'无法核对订单数：{platform} {date}')


def collect(page, key, platform, dates):
    mt = platform == 'mt'
    target = STORES[key][0 if mt else 1]
    current = page.locator('body').first.inner_text().splitlines()[0 if mt else 2]
    if current != target:
        if not page.get_by_text(target, exact=True).count():
            page.get_by_text(current, exact=True).first.click()
            if not mt:
                page.get_by_text(STORES[key][2], exact=True).first.evaluate('(e)=>e.click()')
        if mt:
            page.get_by_text(target,exact=True).first.click()
        else:
            page.get_by_text(target,exact=True).first.evaluate('(e)=>e.click()')
        page.wait_for_timeout(1200)
    if mt:
        all_orders = page.get_by_text('全部订单', exact=True).first
        if not all_orders.count():
            page.get_by_text('订单管理', exact=False).first.click()
        all_orders.evaluate('(e) => e.click()')
    else:
        if '/order__querying' not in page.url:
            page.get_by_text('订单管理', exact=True).first.click()
            page.get_by_text('订单查询', exact=True).first.click()
        # The order view is checked below. Waiting for the whole document can
        # stall on unrelated merchant console resources.
        page.reload(wait_until='commit', timeout=25000)
    for _ in range(100):
        candidates = [f for f in page.frames if f != page.main_frame and '/orderbusiness' in f.url] if mt else [page]
        view = next((frame for frame in candidates if frame.get_by_placeholder('开始时间' if mt else '开始日期').count()), None)
        if view is not None:
            break
        page.wait_for_timeout(400)
    else:
        raise RuntimeError('Order view not ready: '+key)
    if view.get_by_text('我知道了',exact=True).count():
        view.get_by_text('我知道了',exact=True).first.evaluate('(e)=>e.click()')
    assert page.locator('body').first.inner_text().splitlines()[0 if mt else 2] == target
    for date in dates:
        if mt:
            open_meituan_order_calendar(view)
        else:
            view.get_by_placeholder('开始日期').click()
        if mt:
            for _ in range(2):
                view.locator('td:not(.disabled)').get_by_text(str(int(date[-2:])),exact=True).first.click()
        else:
            for _ in range(2):
                view.locator(f'[title="{date}"]').first.click()
        page.wait_for_timeout(2000)
        if mt:
            first=view.locator('.roo-pagination a').get_by_text('1',exact=True)
            if first.count():
                first.click()
        else:
            first=view.locator('.ant-pagination-item-1')
            if first.count() and 'ant-pagination-item-active' not in (first.get_attribute('class') or ''):
                first.click()
        _, total = wait_order_total(page, view, platform, date)
        size = 10 if mt else 20
        rec = dict(store=key,platform='美团' if mt else '饿了么',date=date,captured_at=dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(timespec='seconds'),store_header=target,total=total,pages=[])
        seen = set()
        print(key, date, platform, 'total', total, file=sys.stderr, flush=True)
        previous = None
        for number in range(1,(total+size-1)//size+1):
            if number > 1:
                view.locator('a[aria-label="Next"]' if mt else '.ant-pagination-next button').click()
            text = wait_snapshot(page,view,platform,date,min(size,total-size*(number-1)),previous)
            ids = identifiers(text,platform)
            assert not seen.intersection(ids), 'Duplicate pagination IDs'
            seen.update(ids)
            previous = ids[0]
            rec['pages'].append(dict(page=number,text=text))
        assert len(seen) == total
        yield rec

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,required=True)
    parser.add_argument('--platform',choices=['mt','ele'],required=True)
    parser.add_argument('--stores',nargs='+',choices=STORES,required=True)
    parser.add_argument('--dates',nargs='+',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    for date in args.dates:
        dt.date.fromisoformat(date)
        if date[:7] != dt.date.today().isoformat()[:7]:
            parser.error('Only current-calendar-month date selection is supported')
    from playwright.sync_api import sync_playwright
    args.output.parent.mkdir(parents=True,exist_ok=True)
    done=set()
    if args.output.exists():
        for line in args.output.read_text().splitlines():
            r=json.loads(line);done.add((r['store'],r['date']))
    with sync_playwright() as p:
        browser=p.chromium.connect_over_cdp(f'http://127.0.0.1:{args.port}')
        marker='e.waimai.meituan.com' if args.platform=='mt' else 'melody.shop.ele.me/'
        page=next(x for x in browser.contexts[0].pages if marker in x.url)
        for store in args.stores:
            dates=[d for d in args.dates if (store,d) not in done]
            if not dates:continue
            for rec in collect(page,store,args.platform,dates):
                with args.output.open('a') as f:f.write(json.dumps(rec,ensure_ascii=False)+'\n')
                print(store,rec['date'],'saved',file=sys.stderr,flush=True)

if __name__=='__main__':main()
