"""Read-only, one-store Meituan customer-message pilot. Never sends messages.

Run only on the Mac mini. Requires the logged-in customer workbench already open.
Opening a conversation may update the platform's read receipt. Raw data is local.
"""
import argparse
import json
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXTRACT = """els => els.map(e => {
 const text = s => {const n=e.querySelector(s);return (n?.innerText || n?.textContent || '').trim()};
 const nick = e.querySelector('.sender-nickname')?.cloneNode(true);
 nick?.querySelector('.message-formattime')?.remove();
 return {id:e.id, time:text('.message-formattime'), sender:nick?.textContent?.trim() || '',
 role:e.querySelector('.right-message') ? 'merchant' : e.querySelector('.left-message') ? 'customer' : 'system',
 content:text('[data-card-content]') || text('.im-card_event-message'),
 separator:text('.im-card_timestamp-message'),
 media:Array.from(e.querySelectorAll('[data-card-content] img')).map(i=>({alt:i.alt || '图片',src:i.src})),
 read_status:text('.read-position')};
})"""


def normalize_messages(rows, target):
    """DOM is newest first; retain all messages and date separators in original order."""
    result, seen = [], set()
    for row in reversed(rows):
        if row['id'] in seen or not (row.get('content') or row.get('separator') or row.get('media')):
            continue
        seen.add(row['id'])
        row = dict(row)
        if not row.get('content') and row.get('media'):
            row['content'] = '[图片消息：原图待核验]'
        stamp = row.get('time', '')
        if stamp:
            if len(stamp) == 14:  # MM-DD HH:MM:SS
                stamp = f'{target[:4]}-{stamp}'
            elif len(stamp) == 8:  # today, not target date
                stamp = f'{date.today().isoformat()} {stamp}'
        row['timestamp'] = stamp
        row['on_target_date'] = stamp.startswith(target)
        if row['role'] == 'merchant':
            row['reply_type'] = 'AI回复' if '[AI客服]' in row['sender'] else '自动回复' if '[自动回复]' in row['sender'] else '门店回复'
        else:
            row['reply_type'] = '顾客' if row['role'] == 'customer' else '系统提示'
        result.append(row)
    return result


def main():
    from playwright.sync_api import sync_playwright
    ap = argparse.ArgumentParser()
    ap.add_argument('--date', default=(date.today()-timedelta(days=1)).isoformat())
    ap.add_argument('--port', type=int, default=19223)
    ap.add_argument('--store', default='朝阳门店')
    ap.add_argument('--identity-keyword', default='雅宝食堂')
    args = ap.parse_args()
    date.fromisoformat(args.date)
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f'http://127.0.0.1:{args.port}')
        pages = [pg for c in browser.contexts for pg in c.pages if 'e.waimai.meituan.com/imworkbench/home' in pg.url]
        if not pages:
            raise RuntimeError('请先在生产浏览器打开顾客消息工作台；本试采不自动切换账号')
        page = pages[0]
        if args.identity_keyword not in page.locator('body').inner_text():
            raise RuntimeError('门店身份不匹配，停止采集')
        page.get_by_text('全部顾客消息', exact=True).dispatch_event('click')
        page.wait_for_timeout(1200)
        # Exhaust the session list using its actual scroll container, then verify footer.
        session_list = page.locator('.infinite-scroll-component').first
        for _ in range(12):
            before = page.locator('[class*=sessionListItemContainer]').count()
            session_list.evaluate('e=>{e.scrollTop=e.scrollHeight}')
            page.wait_for_timeout(350)
            if page.locator('[class*=sessionListItemContainer]').count() == before and '已经到底' in session_list.inner_text():
                break
        list_end = '已经到底' in session_list.inner_text()
        sessions = page.locator('[class*=sessionListItemContainer]').evaluate_all('es=>es.map(e=>({id:e.id,label:e.innerText}))')
        results, errors = [], []
        for item in sessions:
            if not item['id'] or item['id'].startswith('-'):
                continue  # automated outbound campaign log, not a customer conversation
            try:
                page.locator(f'[id="{item["id"]}"]').dispatch_event('click')
                panel = page.locator('[class*=sessionDetailPanel]')
                panel.locator('.message-item').first.wait_for(state='attached', timeout=10000)
                page.wait_for_timeout(550)
                if item['label'].split('\n')[0] not in panel.inner_text():
                    raise RuntimeError('会话标题未匹配')
                history = panel.locator('.infinite-scroll-component').first
                for _ in range(15):
                    if '没有更多历史消息' in history.inner_text():
                        break
                    history.evaluate('e=>{e.scrollTop=-e.scrollHeight;e.dispatchEvent(new Event("scroll"))}')
                    page.wait_for_timeout(400)
                messages = normalize_messages(panel.locator('.message-item').evaluate_all(EXTRACT), args.date)
                if not any(m['on_target_date'] for m in messages):
                    continue
                results.append({**item, 'history_complete': '没有更多历史消息' in history.inner_text(), 'messages': messages})
            except Exception as exc:
                errors.append({'session': item['label'].split('\n')[0], 'error': str(exc)[:200]})
        payload = {'store':args.store,'platform':'美团','date':args.date,'collected_at':datetime.now().isoformat(timespec='seconds'),
                   'source':'美团客服工作台 / 全部顾客消息','identity_keyword':args.identity_keyword,
                   'session_list_complete':list_end,'scanned_sessions':len([s for s in sessions if s['id'] and not s['id'].startswith('-')]),
                   'sessions':results,'errors':errors,
                   'coverage_note':'仅此门店美团试采；淘宝闪购尚未接入。检查全部可见顾客会话，不包含营销群发记录。聊天记录不等于退款或开票成功凭证。'}
        out = ROOT/'outputs/customer_messages_sample'/f'{args.date}.json'
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'output':str(out),'sessions':len(results),'scanned':payload['scanned_sessions'],'list_complete':list_end,'errors':len(errors)}, ensure_ascii=False))

if __name__ == '__main__':
    main()
