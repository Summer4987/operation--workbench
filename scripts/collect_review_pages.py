#!/usr/bin/env python3
"""Read-only collection from authenticated review pages, on the production Mac mini only.

Requests are captured from the UI first. Eleme uses native filters and paging;
only observed Meituan score/list query methods are replayed. Cookies, tokens, headers and request URLs are never persisted.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import platform
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from review_page_data import (ROOT, SNAPSHOT, TZ, eleme_reviews, match_store,
                              meituan_review, read_snapshot, refresh_payloads, score_value, store_aliases, verify_all_store_scope)

MT_URL = 'https://waimaieapp.meituan.com/frontweb/ffw/userComment_gw#/user_comment/home'
ELE_URL = 'https://melody.shop.ele.me/app/unit/comments#app.unit.comments'
MAX_PAGES = 100


def await_value(page, fn, label, seconds=30):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if any('/_____tmd_____/punish' in frame.url for frame in page.frames):
            raise RuntimeError('淘宝闪购要求人工安全验证，请在 Mac mini 完成后重试')
        value = fn()
        if value is not None:
            return value
        page.wait_for_timeout(200)
    raise RuntimeError(f'{label}未返回；请检查生产登录态或页面结构')


def paged(fetch, items_key, total_key='total', first=1):
    """Verify exhaustion and unique IDs; a truncated/capped query must not mean zero."""
    rows = []
    total = None
    for page_num in range(first, first + MAX_PAGES):
        data = fetch(page_num)
        batch = data.get(items_key)
        if not isinstance(batch, list):
            raise RuntimeError('分页列表字段缺失')
        if total_key:
            current_total = data.get(total_key)
            if not isinstance(current_total, int) or current_total < 0:
                raise RuntimeError('分页总数缺失')
            if total is not None and current_total != total:
                raise RuntimeError('采集过程中总数变化，请重试')
            total = current_total
        rows.extend(batch)
        if total is not None and len(rows) >= total:
            if len(rows) != total:
                raise RuntimeError('分页条数与总数不一致')
            return rows
        if not batch:
            if total is not None:
                raise RuntimeError('分页提前结束')
            return rows
    raise RuntimeError('超过分页上限，结果不完整')


class Collector:
    def __init__(self, playwright, old, start, end):
        self.pw, self.old, self.start, self.end = playwright, old, start, end
        self.aliases = store_aliases()
        self.now = datetime.now(TZ).isoformat(timespec='seconds')

    def rating(self, store, value, source_date, old_scope):
        previous = (old_scope.get('ratings') or {}).get(store) or {}
        value = score_value(value)
        if value is None:
            return None
        previous_value = previous.get('value')
        # Repeat runs on the same day retain the last distinct daily snapshot.
        if previous.get('collected_at', '')[:10] == self.now[:10]:
            previous_at = previous.get('previous_at', '')
            baseline = previous_value - previous['delta'] if previous.get('delta') is not None and previous_value is not None else None
            delta = round(value - baseline, 2) if baseline is not None else None
        else:
            delta = round(value - previous_value, 2) if previous_value is not None else None
            previous_at = previous.get('collected_at', '')
        return dict(value=value, delta=delta, previous_at=previous_at,
                    collected_at=self.now, source_date=source_date)

    def run(self, account, fn):
        key = account['id']
        old = self.old.get('scopes', {}).get(key, {})
        scope = dict(platform=account['platform'], account_type=account['type'], stores=account['stores'],
                     start_date=self.start, end_date=self.end, collected_at=self.now,
                     ratings_status='failed', reviews_status='failed', ratings=old.get('ratings', {}), records=[])
        browser = page = None
        try:
            browser = self.pw.chromium.connect_over_cdp(f"http://127.0.0.1:{account['port']}", timeout=10000)
            if account['type'] == 'single':
                identities = []
                for existing in browser.contexts[0].pages:
                    if existing.url.startswith('https://e.waimai.meituan.com/'):
                        identities.append(match_store(existing.locator('body').inner_text(timeout=3000)[:300], '美团', self.aliases))
                if not any(store in account['stores'] for store in identities):
                    raise RuntimeError('美团独立账号的当前门店与配置不一致，已停止采集')
            page = browser.contexts[0].new_page()
            page.set_default_timeout(10000)
            fn(page, account, scope, old)
        except Exception as e:
            # Playwright exceptions contain signed URLs. Persist only our safe messages.
            scope['message'] = str(e) if type(e) is RuntimeError else f'{type(e).__name__}：页面读取失败，请检查 Mac mini 登录态/浏览器'
        finally:
            if page:
                try: page.close()
                except Exception: pass
            if browser:
                browser.close()
        print(f"{key}: 评分 {scope['ratings_status']}，评价 {scope['reviews_status']}，{len(scope['records'])} 条差评", flush=True)
        return scope

    def eleme(self, page, account, scope, old):
        captured = {}
        def receive(response):
            if '/ugc/invoke/' not in response.url:
                return
            try:
                body = response.request.post_data_json
                key = (body.get('service'), body.get('method'))
                if key in [('ChainRatingService', 'pageShopDetail'), ('ShopRatingService', 'getRateResult'), ('ShopRatingService', 'countRateResult')]:
                    data = response.json()
                    if not data.get('error') and data.get('result') is not None:
                        captured[key] = (body, data['result'])
            except Exception:
                pass
        page.on('response', receive)
        page.goto(ELE_URL, wait_until='domcontentloaded', timeout=60000)
        frame = await_value(page, lambda: next((f for f in page.frames if f.url.startswith('https://melody-comment.faas.ele.me/')), None), '淘宝评价页面')
        score_key = ('ChainRatingService', 'pageShopDetail')
        # Clear the native shop filter: [] is the platform's all-stores scope.
        # Selecting the company/organization node is not equivalent to all shops.
        frame.get_by_placeholder('按组织/城市查找').click()
        frame.get_by_text('清空已选', exact=True).click()
        captured.pop(score_key, None)
        frame.get_by_role('button', name='确 定', exact=True).click()
        initial = await_value(page, lambda: captured.get(score_key), '淘宝全部门店评分')
        verify_all_store_scope(initial[0]['params']['request'].get('shopIds'))
        score_query = initial[0]['params']['request']
        def next_ui_page():
            next_button = frame.locator('li.comment-melody-antd-pagination-next:visible, li.kw-pager-next:visible')
            if next_button.count() != 1 or 'disabled' in (next_button.get_attribute('class') or ''):
                raise RuntimeError('淘宝评价分页提前结束')
            next_button.click()
        def score_page(n):
            if n > 1:
                next_ui_page()
            value = await_value(page, lambda: captured.get(score_key) if captured.get(score_key, ({},))[0].get('params', {}).get('request', {}).get('pageNum') == n else None, '淘宝评分翻页')
            return value[1]
        score_rows = paged(score_page, 'data')
        leaf_ids = {str(r['shopId']) for r in score_rows}
        names = [match_store(r.get('shopName',''), '饿了么', self.aliases) for r in score_rows]
        if len({str(r['shopId']) for r in score_rows}) != len(score_rows):
            raise RuntimeError('淘宝评分分页出现重复门店')
        ratings = {}
        for row, store in zip(score_rows, names):
            if store:
                rating = self.rating(store,row.get('shopScore'),score_query.get('bizDate',''),old)
                if rating:ratings[store]=rating
        scope['ratings'] = ratings
        scope['ratings_status'] = 'ready'
        scope['stores'] = sorted(set(names) - {''})
        frame.get_by_text('评价内容', exact=True).click()
        list_key = ('ShopRatingService', 'getRateResult')
        count_key = ('ShopRatingService', 'countRateResult')
        await_value(page, lambda: captured.get(list_key), '淘宝评价列表')
        records = {}
        for label in ['满意度差评(1-2星)', '满意度中评(3星)']:
            captured.pop(list_key, None)
            captured.pop(count_key, None)
            if label == '满意度差评(1-2星)':
                frame.get_by_text('满意度评分',exact=True).click()
            else:
                frame.get_by_text(label,exact=True).click()
            body, data = await_value(page, lambda: captured.get(list_key), '淘宝满意度筛选')
            query = body['params']['rateQuery']
            verify_all_store_scope(query.get('shopIds'), leaf_ids)
            kind = query.get('rateType')
            if query.get('scoreType') != 'SERVICE_SCORES' or kind == 'ALL':
                raise RuntimeError('淘宝满意度筛选未生效')
            if query.get('startTime','9999')[:10] > self.start or query.get('endTime','')[:10] < self.end:
                raise RuntimeError('淘宝评价页面日期范围未覆盖最近7天')
            def current_count():
                value = captured.get(count_key)
                if value and value[0]['params']['rateQuery'].get('rateType') == kind:
                    return value
                return None
            _, total = await_value(page, current_count, '淘宝筛选总数')
            if not isinstance(total, int):
                raise RuntimeError('淘宝评价总数无效')
            def reviews_page(n):
                if n > 1:
                    next_ui_page()
                def current_page():
                    value = captured.get(list_key)
                    if value:
                        q = value[0]['params']['rateQuery']
                        if q.get('currentPage') == n and q.get('rateType') == kind:
                            verify_all_store_scope(q.get('shopIds'), leaf_ids)
                            return value
                    return None
                _, result = await_value(page, current_page, '淘宝评价翻页')
                return dict(result, total=total)
            raw = paged(reviews_page,'rateInfos')
            ids = [str(r.get('rateId') or '') for item in raw for r in item.get('orderRateInfos', [])]
            if len(set(ids)) != total or '' in ids:
                raise RuntimeError('淘宝评价分页重复或评价ID缺失')
            for item in raw:
                for row in eleme_reviews(item,self.aliases):
                    if not row['negative']:
                        raise RuntimeError('淘宝满意度星级与筛选不一致')
                    if self.start <= row['date'] <= self.end:
                        records[row['review_id']]=row
        scope['store_scope']='all_stores'
        scope['records']=list(records.values())
        scope['reviews_status']='ready'

    def meituan(self,page,account,scope,old):
        captured={}
        def receive(response):
            path=urlparse(response.url).path
            if path in ['/gw/customer/comment/list','/gw/customer/comment/chain/scores','/gw/customer/comment/poi/scores']:
                try:
                    data=response.json()
                    if data.get('code') == 0 and isinstance(data.get('data'),dict):
                        captured[path.rsplit('/',1)[-1] if '/chain/' not in path and '/poi/' not in path else 'chain' if '/chain/' in path else 'poi']=(response.request.url,data['data'])
                except Exception:pass
        page.on('response',receive)
        page.goto(account.get('url',MT_URL),wait_until='domcontentloaded',timeout=60000)
        frame=await_value(page,lambda:next((f for f in page.frames if f.url.startswith('https://waimaieapp.meituan.com/frontweb/ffw/userComment')),None),'美团评价页面')
        key='chain' if account['type']=='headquarters' else 'poi'
        await_value(page,lambda:captured.get(key),'美团门店评分')
        def query(key,**changes):
            url=captured[key][0];u=urlparse(url);params=dict(parse_qsl(u.query));params.pop('mtgsig',None);params.update({k:str(v) for k,v in changes.items()})
            url=urlunparse(u._replace(query=urlencode(params)))
            data=frame.evaluate('async url => (await fetch(url,{credentials:"include"})).json()',url)
            if data.get('code') != 0 or not isinstance(data.get('data'),dict):raise RuntimeError('美团评价查询失败或登录失效')
            return data['data']
        if key=='chain':
            score_rows=paged(lambda n:query('chain',pageNum=n,pageSize=100),'list')
            if len({str(r.get('wmPoiId')) for r in score_rows}) != len(score_rows):raise RuntimeError('美团评分分页重复')
        else:
            score_rows=[dict(captured['poi'][1],poiName=account['store_name'])]
        ratings={}
        for row in score_rows:
            store=match_store(row.get('poiName',''),'美团',self.aliases)
            # Explicit modern total score; never use qualityScore/serviceScore.
            value=row.get('poiScoreNew') if row.get('poiScoreNew') is not None else row.get('poiScoreOld')
            rating=self.rating(store,value,self.now[:10],old)
            if store and rating:ratings[store]=rating
        scope['ratings']=ratings;scope['ratings_status']='ready'
        if 'list' not in captured:
            # Single-store Flutter UI. A new isolated page has a fixed viewport;
            # read tab labels from the screenshot-confirmed header position.
            page.set_viewport_size({'width':1440,'height':1000})
            page.wait_for_timeout(1800)  # Flutter renders after the score response and viewport resize.
            page.mouse.click(455,242)
        await_value(page,lambda:captured.get('list'),'美团评价列表')
        begin=int(datetime.fromisoformat(self.start).replace(tzinfo=TZ).timestamp())
        end=int(datetime.fromisoformat(self.end+'T23:59:59').replace(tzinfo=TZ).timestamp())
        raw=paged(lambda n:query('list',pageNum=n,pageSize=20,commScore=0,beginTime=begin,endTime=end),'list')
        if len({str(r.get('id')) for r in raw}) != len(raw):raise RuntimeError('美团评价分页出现重复记录')
        records=[]
        for item in raw:
            row=meituan_review(item,account,self.aliases)
            if not row['review_id'] or not re_date(row['date']) or row['rating'] is None:raise RuntimeError('美团评价缺少有效日期、ID或星级')
            if account['type']=='single' and row['store'] not in account['stores']:
                raise RuntimeError('美团评价所属门店与独立账号不一致')
            if row['negative'] and self.start <= row['date'] <= self.end:records.append(row)
        scope['records']=records;scope['reviews_status']='ready'


def re_date(value):
    try:datetime.strptime(value,'%Y-%m-%d');return True
    except ValueError:return False


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--account',action='append',help='只重试指定账号；默认全部')
    args=parser.parse_args()
    if 'mini' not in platform.node().lower():
        raise SystemExit('只允许在 Mac mini 生产主机读取平台登录态')
    from playwright.sync_api import sync_playwright
    now=datetime.now(TZ);end=(now.date()-timedelta(days=1)).isoformat();start=(now.date()-timedelta(days=7)).isoformat()
    old=read_snapshot();scopes=copy.deepcopy(old.get('scopes',{}))
    config=json.loads((ROOT/'config/direct_meituan_accounts.json').read_text())
    direct=[a for a in config['accounts'] if a.get('enabled')]
    franchise=json.loads((ROOT/'business-report-dashboard/config.json').read_text())['target_stores']
    all_stores=franchise+json.loads((ROOT/'business-report-dashboard/direct_config.json').read_text())['target_stores']
    direct_stores={s for a in direct for s in a['stores']}
    accounts=[dict(id='eleme_headquarters',platform='饿了么',type='headquarters',port=9222,stores=all_stores),
              dict(id='meituan_headquarters',platform='美团',type='headquarters',port=9222,stores=[s for s in all_stores if s not in direct_stores],url='https://e.waimai.meituan.com/#https://waimaieapp.meituan.com/frontweb/ffw/userComment_gw')]
    accounts += [dict(id=a['id'],platform='美团',type='single',port=a['debug_port'],stores=a['stores'],store_name=a['meituan_store_name'],url=a['pages']['reviews']) for a in direct]
    if args.account:
        unknown=set(args.account)-{a['id'] for a in accounts}
        if unknown:raise SystemExit('未知账号：'+','.join(sorted(unknown)))
        accounts=[a for a in accounts if a['id'] in args.account]
    with sync_playwright() as pw:
        collector=Collector(pw,old,start,end)
        for account in accounts:
            scopes[account['id']]=collector.run(account,collector.eleme if account['platform']=='饿了么' else collector.meituan)
            payload=dict(schema_version=1,generated_at=datetime.now(TZ).isoformat(timespec='seconds'),start_date=start,target_date=end,scopes=scopes)
            SNAPSHOT.parent.mkdir(parents=True,exist_ok=True)
            tmp=SNAPSHOT.with_suffix('.tmp');tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');os.replace(tmp,SNAPSHOT)
    refresh_payloads()
    failures=[a['id'] for a in accounts if any(scopes[a['id']][k]!='ready' for k in ['reviews_status','ratings_status'])]
    if failures:raise SystemExit('部分账号采集失败：'+','.join(failures))

if __name__=='__main__':main()
