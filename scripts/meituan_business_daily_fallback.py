"""Read-only backup for single-store Meituan report failures.

Capture the historical business page, never today's realtime panel. Runtime JSON
contains normalized metrics only; signed requests/cookies are never persisted.
"""
from __future__ import annotations

import json
import math
import platform
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / 'business-report-dashboard/data/direct/business_fallback'
STATUS_DIR = ROOT / 'outputs/direct_meituan_daily'
TZ = ZoneInfo('Asia/Shanghai')
BUSINESS_URL = 'https://e.waimai.meituan.com/#https://waimaieapp.meituan.com/igate/bizdata/home'
PATHS = {
    'identity': '/gw/bizdata/chain/common/common/poi/info',
    'income': '/gw/bizdata/renew/business/overview/panel',
    'flow': '/gw/bizdata/renew/overview/history/flow/convert/v2',
    'customer': '/gw/growth/metrics/api/callMetricApi/customerOrderOverview',
}


def number(value):
    if value is None or value == '':
        return None
    try:
        n = float(str(value).replace(',', ''))
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def normalized_name(name):
    import re
    return re.sub(r'[\s（）()]', '', name).lower()


def parse_business_daily(account, target_date, captured):
    target = datetime.strptime(target_date, '%Y%m%d').date().isoformat()
    identity = captured.get('identity', {}).get('data') or {}
    name = identity.get('wmPoiName') or ''
    keyword = account.get('keyword')
    if not name or not identity.get('wmPoiId'):
        raise RuntimeError('经营数据页缺少实际门店身份')
    if keyword:
        matches = normalized_name(keyword) in normalized_name(name)
    else:
        matches = normalized_name(account.get('meituan_store_name', '')) == normalized_name(name)
    if not matches or len(account.get('stores') or []) != 1:
        raise RuntimeError('经营数据页实际门店与独立账号不一致')
    def section(key):
        value = captured.get(key)
        if not value:
            return None
        params = value.get('params') or {}
        if params.get('beginDate') != target_date or params.get('endDate') != target_date or str(params.get('durationType')) != '1':
            raise RuntimeError('经营数据日期不是目标单日，拒绝使用实时或其它日期数据')
        if str(params.get('wmPoiId')) != str(identity['wmPoiId']):
            raise RuntimeError('经营数据请求门店与页面身份不一致')
        return value['data']
    income = section('income')
    if income is None:
        raise RuntimeError('经营数据页未取得目标日期历史收益')
    values = {r.get('field'):number(r.get('current')) for r in income.get('list', [])}
    if values.get('settleAmount') is None or values.get('orderCnt') is None:
        raise RuntimeError('经营数据页缺少有效营业收入或订单量')
    if values['orderCnt'] < 0 or not values['orderCnt'].is_integer():
        raise RuntimeError('经营数据订单量无效')
    flow = section('flow') or {}
    customer = section('customer') or {}
    left = flow.get('left') or {}
    layers = {r.get('field'):number(r.get('base')) for r in left.get('layers', [])}
    conversions = {r.get('title'):number(r.get('base')) for r in left.get('conversion', [])}
    customers = {r.get('field'):number(r.get('base')) for r in customer.get('list', [])}
    record = dict(date=target, platform='美团', store=account['stores'][0], store_raw=name,
        orders=int(values['orderCnt']), income=values['settleAmount'], customer_paid=values.get('cusPayment'),
        customer_paid_available=values.get('cusPayment') is not None,
        customer_paid_orders=int(values['orderCnt']) if values.get('cusPayment') is not None else 0,
        impressions=layers.get('exposeUv'), visit_conversion=conversions.get('进店转化率'),
        order_conversion=conversions.get('下单转化率'), old_customer_orders=customers.get('old_fin_usr_num'),
        new_customer_orders=customers.get('new_fin_usr_num'), old_customer_order_conversion=None,
        new_customer_order_conversion=None, source='business_page_fallback',
        collected_at=datetime.now(TZ).isoformat(timespec='seconds'))
    for metric in ['visit_conversion', 'order_conversion']:
        if record[metric] is not None and not 0 <= record[metric] <= 1:
            raise RuntimeError('经营数据转化率不在0到1范围内')
    missing = [k for k in ['customer_paid','impressions','visit_conversion','order_conversion','old_customer_orders','new_customer_orders','old_customer_order_conversion','new_customer_order_conversion'] if record[k] is None]
    record['missing_metrics'] = json.dumps(missing,ensure_ascii=False)
    record['source_note'] = '经营数据页兜底；新老客各自下单转化率未提供，不按0处理'
    return record


def collect(account, target_date, reason='报表下载失败'):
    if 'mini' not in platform.node().lower():
        raise RuntimeError('经营数据生产采集只允许在 Mac mini 执行')
    from playwright.sync_api import sync_playwright
    captured = {}
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{account['debug_port']}",timeout=12000)
        page = browser.contexts[0].new_page()
        def receive(response):
            key = next((k for k,path in PATHS.items() if urlparse(response.url).path == path), None)
            if key is None:
                return
            try:
                body = response.json()
                if body.get('code') != 0 or not isinstance(body.get('data'),dict):
                    return
                params = response.request.post_data_json or {}
                captured[key] = dict(data=body['data'],params=params)
            except Exception:
                pass
        page.on('response',receive)
        try:
            page.goto((account.get('pages') or {}).get('business_daily') or BUSINESS_URL,wait_until='domcontentloaded',timeout=60000)
            deadline=time.monotonic()+35
            while time.monotonic()<deadline and not all(k in captured for k in PATHS):
                page.wait_for_timeout(200)
            # Default history is yesterday. Explicit historical backfills must not
            # silently reuse the default date; the parser rejects mismatches.
            record=parse_business_daily(account,target_date,captured)
        finally:
            page.close()
            browser.close()
    DATA_DIR.mkdir(parents=True,exist_ok=True)
    path=DATA_DIR/f"{account['id']}_{target_date}.json"
    payload=dict(account_id=account['id'],target_date=record['date'],status='fallback_ready',
        reason=reason,source='business_page_fallback',record=record)
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');tmp.replace(path)
    STATUS_DIR.mkdir(parents=True,exist_ok=True)
    (STATUS_DIR/f"{account['id']}.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return path
