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

def collect(page, key, platform, dates):
    mt = platform == 'mt'
    target = STORES[key][0 if mt else 1]
    current = page.locator('body').first.inner_text().splitlines()[0 if mt else 2]
    if current != target:
        if not page.get_by_text(target, exact=True).count():
            page.get_by_text(current, exact=True).first.evaluate('(e)=>e.click()')
            if not mt:
                page.get_by_text(STORES[key][2], exact=True).first.evaluate('(e)=>e.click()')
        page.get_by_text(target, exact=True).first.evaluate('(e)=>e.click()')
        page.wait_for_timeout(1200)
    if mt:
        page.goto('https://e.waimai.meituan.com/#/new_fe/orderbusiness#/order/history', wait_until='domcontentloaded')
    else:
        if '/order__querying' not in page.url:
            page.get_by_text('订单管理', exact=True).first.click()
            page.get_by_text('订单查询', exact=True).first.click()
        page.reload(wait_until='domcontentloaded')
    for _ in range(100):
        candidates = [f for f in page.frames if '/orderbusiness#' in f.url] if mt else [page]
        if candidates and candidates[0].get_by_placeholder('开始时间' if mt else '开始日期').count():
            view = candidates[0]
            break
        page.wait_for_timeout(400)
    else:
        raise RuntimeError('Order view not ready: '+key)
    if view.get_by_text('我知道了',exact=True).count():
        view.get_by_text('我知道了',exact=True).first.evaluate('(e)=>e.click()')
    assert page.locator('body').first.inner_text().splitlines()[0 if mt else 2] == target
    for date in dates:
        view.get_by_placeholder('开始时间' if mt else '开始日期').click()
        if mt:
            for _ in range(2):
                view.locator('td:not(.disabled)').get_by_text(str(int(date[-2:])),exact=True).first.click()
        else:
            for _ in range(2):
                view.locator(f'[title="{date}"]').first.click()
        text = wait_snapshot(page,view,platform,date)
        page.wait_for_timeout(600)
        text = view.locator('body').last.inner_text()
        total = int(re.search(r'共\s*(\d+)\s*单',text)[1]) if mt else int(re.search(r'\d+',view.locator('.ant-pagination-total-text').inner_text())[0])
        size = 10 if mt else 20
        rec = dict(store=key,platform='美团' if mt else '饿了么',date=date,captured_at=dt.datetime.now().isoformat(),store_header=target,total=total,pages=[])
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
