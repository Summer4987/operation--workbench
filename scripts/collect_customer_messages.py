#!/usr/bin/env python3
"""Mac mini only. Capture direct-store customer chats without sending/handling messages.

UI opening may update read receipts. Browser popups are dismissed only by known
informational controls, never by send/refund/confirm-action controls.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import platform
import re
import shutil
import time
from datetime import datetime,timedelta
from urllib.parse import urlparse
from customer_message_data import ROOT,TZ,OUT,WEB,stamp,normalize,scope_status,atomic_json,safe_error,media_name,media_type

MT_URL='https://e.waimai.meituan.com/imworkbench/home?appId=4&clientType=140006#/im/page/workbench/reception'
MT_ROWS="""els=>els.map(e=>{
 const txt=s=>{let n=e.querySelector(s);return (n?.innerText||n?.textContent||'').trim()};
 let nick=e.querySelector('.sender-nickname')?.cloneNode(true);nick?.querySelector('.message-formattime')?.remove();
 const card=e.querySelector('[data-card-content]')||e.querySelector('.im_card_message-container');
 let media=card&&!card.querySelector('.im-card_order-message')?Array.from(card.querySelectorAll('img,audio,video,source')).filter(x=>!x.closest('[class*=emoji]')).map(x=>({kind:x.tagName==='IMG'?'image':x.tagName==='VIDEO'?'video':'audio',url:x.src,alt:x.alt||''})):[];
 return {id:e.id,time:txt('.message-formattime'),sender:nick?.textContent?.trim()||'',role:e.querySelector('.right-message')?'merchant':e.querySelector('.left-message')?'customer':'system',content:txt('[data-card-content]')||txt('.im-card_event-message')||txt('.im-card_message-tips-container'),separator:txt('.im-card_timestamp-message'),media,required_media:__MEDIA_REQUIREMENT__(e),read_status:txt('.read-position')};})"""
EL_ROWS="""e=>{let aside='';return Array.from(e.children).flatMap(x=>{
 if(x.classList.contains('im_sdk_msg_list_item_aside_message')){aside=x.textContent.trim();return []}
 if(!x.classList.contains('imsdk_msg_list_item'))return [];
 const text=s=>{let n=x.querySelector(s);return (n?.innerText||n?.textContent||'').trim()};
 const account=text('.msg_account');const match=account.match(/((?:\\d{4}年)?\\d{1,2}月\\d{1,2}日\\s+\\d{1,2}:\\d{2}(?::\\d{2})?)/);
 const area=x.querySelector('.msg_content');
 const media=Array.from(x.querySelectorAll('img,audio,video,source')).filter(n=>!n.closest('[class*=emoji],[class*=avatar]')&&!/product|goods/i.test(n.className)).map(n=>({kind:n.tagName==='IMG'?'image':n.tagName==='VIDEO'?'video':'audio',url:n.src,alt:n.alt||''}));
 return [{id:x.getAttribute('limoo_message_id')||x.id,time:match?match[1]:aside,sender:match?account.slice(0,match.index).trim():account,role:x.querySelector('.my_msg')?'merchant':account.startsWith('顾客')?'customer':'system',content:text('.msg_content')||text('.system_content')||text('.system_prompt_plugin'),is_ai:x.textContent.includes('AI自动回复纠错'),is_auto:!!x.querySelector('[class*=auto_reply]'),media,required_media:__MEDIA_REQUIREMENT__(x),type:x.getAttribute('limoo_custom_type'),read_status:text('.read_status')}];})}"""


MEDIA_REQUIREMENT_JS="""root=>{const nodes=Array.from(root.querySelectorAll('audio,video,[class]'));const has=kind=>nodes.some(n=>n.tagName===kind.toUpperCase()||new RegExp('(?:^|[_ -])'+kind+'(?:[_ -]|$)','i').test(n.className||''));return has('audio')||has('voice')?'audio':has('video')?'video':''}"""
MT_ROWS=MT_ROWS.replace('__MEDIA_REQUIREMENT__','('+MEDIA_REQUIREMENT_JS+')')
EL_ROWS=EL_ROWS.replace('__MEDIA_REQUIREMENT__','('+MEDIA_REQUIREMENT_JS+')')


def wait(page,fn,label,seconds=35):
    until=time.monotonic()+seconds
    while time.monotonic()<until:
        if any('/_____tmd_____/punish' in f.url for f in page.frames):raise RuntimeError('平台要求人工安全验证')
        value=fn()
        if value:return value
        page.wait_for_timeout(250)
    raise RuntimeError(label+'超时，未标为无消息')


def dismiss(page):
    for name in ['跳过全部','我知道了','知道了','暂不体验']:
        for loc in page.get_by_text(name,exact=True).all():
            try:
                if loc.is_visible():loc.dispatch_event('click')
            except Exception:pass
    # The survey close icon is explicitly separate from its submit button.
    for selector in ['[aria-label="Close"]','[aria-label="关闭"]','[class*=survey] [class*=close]']:
        for loc in page.locator(selector).all():
            try:
                if loc.is_visible():loc.dispatch_event('click')
            except Exception:pass


def save_media(page,scope,session,frame=None):
    for m in session['messages']:
        if not (scope.get('window_start',scope['date'])<=m['timestamp'][:10]<=scope['date']):
            for a in m.get('media',[]):
                a.pop('url',None);a['status']='context-not-archived'
            continue
        if m.get('needs_review'):
            try:
                if scope['platform']=='淘宝闪购':
                    index=frame.locator('.imsdk_msg_list_item').evaluate_all('(es,id)=>es.findIndex(e=>e.getAttribute("limoo_message_id")===id)',m['id'])
                    if index<0:raise RuntimeError('特殊消息已不在界面，需复查')
                    loc=frame.locator('.imsdk_msg_list_item').nth(index)
                elif m['id'].startswith('group-'):
                    legacy=next(f for f in page.frames if '/wm_legacy_chat_detail' in f.url)
                    loc=legacy.locator('.wm-im-chat-body > *').nth(int(m['id'].rsplit(':',1)[1]))
                else:loc=page.locator(f'[data-message-id="{m["id"]}"]')
                visible=loc.inner_text()
                name=media_name(scope['store']+scope['platform']+m['id'])+'.png'
                path=OUT/scope['date']/'attachments'/name;path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes(loc.screenshot(timeout=10000))
                m['media'].append(dict(kind='image',status='saved',file='attachments/'+name,alt='平台特殊消息原始截图'))
                m.update(content='[特殊消息：保留平台原始截图，未转写]',capture_mode='screenshot',needs_review=bool('语音' in visible))
            except Exception as exc:m['capture_error']=safe_error(exc)
        for a in m.get('media',[]):
            if a.get('status')=='saved':continue
            url=a.pop('url','')
            a['status']='failed'
            try:
                parsed=urlparse(url)
                if parsed.scheme in ['blob','data']:
                    encoded=page.evaluate("""async url=>{const blob=await (await fetch(url)).blob();if(blob.size>30*1024*1024)throw new Error('attachment too large');return await new Promise((resolve,reject)=>{let r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=reject;r.readAsDataURL(blob)})}""",url)
                    head,body=encoded.split(',',1);mime=head.split(':',1)[1].split(';')[0];content=base64.b64decode(body)
                else:
                    if parsed.scheme not in ['http','https']:raise RuntimeError('附件地址不可下载')
                    response=page.request.get(url,timeout=20000,headers={'Referer':frame.url if frame else page.url})
                    if not response.ok:raise RuntimeError('附件读取失败')
                    mime=response.headers.get('content-type','').split(';')[0];content=response.body()
                mime=media_type(mime,content)
                if not mime:raise RuntimeError('附件类型未识别')
                a['kind']=mime.split('/')[0]
                ext={'image/jpeg':'.jpg','image/png':'.png','image/webp':'.webp','image/gif':'.gif','audio/mpeg':'.mp3','audio/amr':'.amr','video/mp4':'.mp4','audio/ogg':'.ogg','image/avif':'.avif'}.get(mime,'.bin')
                if len(content)>30*1024*1024:raise RuntimeError('附件超过30MB，需人工复查')
                name=media_name(url)+ext
                local=OUT/scope['date']/'attachments'/name
                local.parent.mkdir(parents=True,exist_ok=True);local.write_bytes(content)
                a.update(status='saved',file=f'attachments/{name}',mime=mime,bytes=len(content))
            except Exception as e:
                a['error']=safe_error(e)
                # The platform may serve an image only to its already-loaded viewer.
                # Preserve visible pixels as an explicitly labelled screenshot, never substitute error-page bytes.
                if a.get('kind')=='image':
                    try:
                        host=frame or page
                        index=host.locator('img').evaluate_all('(es,url)=>es.findIndex(e=>e.src===url&&e.complete&&e.naturalWidth>0)',url)
                        if index<0:raise RuntimeError('平台原图也未加载，保留失败状态')
                        image=host.locator('img').nth(index)
                        name=media_name('rendered:'+url)+'.png'
                        path=OUT/scope['date']/'attachments'/name;path.parent.mkdir(parents=True,exist_ok=True)
                        path.write_bytes(image.screenshot(timeout=10000))
                        a.update(status='saved',file='attachments/'+name,mime='image/png',source_mode='platform-image-screenshot',alt='图片附件（平台显示截图，原文件下载异常）',original_download_error=a.pop('error'))
                    except Exception:pass


def mt_list(page,observations,window_start):
    page.get_by_text('全部顾客消息',exact=True).dispatch_event('click')
    wait(page,lambda:observations,'美团全部顾客消息接口返回')
    page.wait_for_timeout(1000)
    wait(page,lambda:page.locator('[class*=sessionListItemContainer]').count() or '暂无消息' in page.locator('body').first.inner_text(),'美团全部会话加载')
    panel=page.locator('.infinite-scroll-component').first
    seen={};complete=False
    for _ in range(160):
        rows=page.locator('[class*=sessionListItemContainer]').evaluate_all("es=>es.map(e=>({id:e.id,label:e.innerText,latest:e.querySelector('[class*=userinfoChattime]')?.textContent?.trim()||''}))")
        for row in rows:
            if row['id'].startswith('-') or '订单完成后自动发送消息记录' in row['label']:continue
            if not row['id']:
                row['group']=True;row['id']='group-'+hashlib.sha256(row['label'].split('\n')[0].encode()).hexdigest()[:24]
            seen[row['id']]=row
        if '已经到底' in panel.inner_text():
            dates=[stamp(r.get('latest')) for r in seen.values()]
            boundary=any(d and d[:10]<window_start for d in dates)
            complete=bool(observations) and (observations[-1].get('hasNext') is False or boundary)
            break
        panel.evaluate('e=>{let n=e;while(n.parentElement&&!/auto|scroll/.test(getComputedStyle(n).overflowY))n=n.parentElement;n.scrollTop=n.scrollHeight;n.dispatchEvent(new Event("scroll"))}')
        page.wait_for_timeout(400)
    return list(seen.values()),complete


def mt_history(page,item,target,window_start=None):
    dismiss(page)
    if item.get('group'):
        return mt_group_history(page,item,target,window_start)
    panel=page.locator('[class*=sessionDetailPanel]')
    expected=item['label'].split('\n')[0]
    same=panel.count() and panel.inner_text().split('\n')[0]==expected
    previous=panel.locator('.message-item').first.get_attribute('id') if panel.count() and panel.locator('.message-item').count() else ''
    page.locator(f'[id="{item["id"]}"]').dispatch_event('click')
    wait(page,lambda:expected in panel.inner_text() and panel.locator('.message-item').count() and (same or panel.locator('.message-item').first.get_attribute('id')!=previous),'美团会话正文与切换归属')
    page.wait_for_timeout(600)
    history=panel.locator('#imMessageList')
    merged={};complete=False
    for _ in range(120):
        batch=normalize(panel.locator('.message-item').evaluate_all(MT_ROWS),target,newest_first=True)
        for row in batch:merged[row['id']]=row
        known=[m['timestamp'] for m in merged.values() if m['timestamp']]
        if known and min(known)[:10]<(window_start or target):complete=True;break
        if '没有更多历史消息' in history.inner_text():complete=True;break
        history.evaluate('e=>{e.scrollTop=-e.scrollHeight;e.dispatchEvent(new Event("scroll"))}')
        page.wait_for_timeout(400)
    # Snowflake message IDs preserve chronology; DOM is reverse chronological.
    messages=sorted(merged.values(),key=lambda m:m['timestamp'] or '9999')
    known=[m for m in messages if m['timestamp']]
    if not complete and known and min(m['timestamp'][:10] for m in known)<(window_start or target):complete=True
    return dict(**item,messages=messages,history_complete=complete,history_basis='平台历史末尾' if '没有更多历史消息' in history.inner_text() else '已越过目标日开始时间')



def mt_group_history(page,item,target,window_start=None):
    loc=page.locator('[class*=sessionListItemContainer]').filter(has_text=item['label'].split('\n')[0])
    if loc.count()!=1:raise RuntimeError('美团三方群聊无法唯一定位')
    loc.dispatch_event('click')
    frame=wait(page,lambda:next((f for f in page.frames if '/imworkbench/wm_legacy_chat_detail' in f.url),None),'美团三方群聊页面')
    group_name=re.sub(r'^#\d+\s*','',item['label'].split('\n')[0])
    wait(page,lambda:frame.locator('.wm-im-chat-item').count() and group_name in frame.locator('.wme-im-dialog-chat-window').inner_text()[:400],'美团三方群聊正文与归属')
    page.wait_for_timeout(700)
    body=frame.locator('.wm-im-chat-body');stable=0;old=''
    for _ in range(120):
        signature=body.text_content()
        stable=stable+1 if signature==old else 0;old=signature
        if stable>=4:break
        body.evaluate('e=>{e.scrollTop=1;e.dispatchEvent(new Event("scroll"));e.scrollTop=0;e.dispatchEvent(new Event("scroll"))}')
        page.wait_for_timeout(450)
    rows=body.evaluate("""(e,prefix)=>{let day='',names={};return Array.from(e.children).flatMap((x,i)=>{
        if(x.classList.contains('system-message-box')){day=x.textContent.trim();return []}
        if(!x.classList.contains('wm-im-chat-item'))return [];
        let name=x.querySelector('.user-name-box .name')?.textContent?.trim()||'';
        const avatar=x.querySelector('.avatar img')?.src||'';
        if(name)names[avatar]=name;else name=names[avatar]||'顾客/群聊参与者';
        let content=x.querySelector('.user-message')?.cloneNode(true);
        content?.querySelectorAll('.opposite-read').forEach(n=>n.remove());
        const text=(content?.innerText||content?.textContent||'').trim();
        return [{id:prefix+':'+i,time:day,time_inferred:true,sender:name,role:x.classList.contains('wm-im-chat-item-mine')?'merchant':name.startsWith('骑手')?'participant':'customer',content:text,media:Array.from(x.querySelectorAll('.user-message img,.user-message audio,.user-message video')).map(n=>({kind:n.tagName==='IMG'?'image':n.tagName==='VIDEO'?'video':'audio',url:n.src,alt:n.alt||''}))}];})}""",item['id'])
    messages=normalize(rows,target)
    for m in messages:m['time_inferred']=True
    return dict(**item,messages=messages,history_complete=stable>=4,history_basis='三方群聊已滚动到顶部连续5次复核；平台仅显示日期的消息不补造时分秒')

def meituan(pw,scope,account,keyword):
    browser=pw.chromium.connect_over_cdp(f'http://127.0.0.1:{account["port"]}',timeout=10000)
    page=browser.contexts[0].new_page();page.set_default_timeout(12000)
    observations=[]
    def response(r):
        if not urlparse(r.url).path.endswith('/dialog/group/query'):return
        try:
            query=r.request.post_data_json
            if query.get('groupCode')!='AFTER_SALE':return
            payload=r.json()
            if not payload.get('success'):return
            data=payload['data']
            observations.append(dict(total=data.get('total'),hasNext=data.get('hasNext'),count=len(data.get('data') or [])))
        except Exception:pass
    page.on('response',response)
    try:
        page.goto(MT_URL,wait_until='domcontentloaded',timeout=60000)
        wait(page,lambda:page.get_by_text('全部顾客消息',exact=True).count(),'美团客服工作台')
        dismiss(page)
        wait(page,lambda:keyword in page.locator('[class*=storeName]').first.inner_text() if page.locator('[class*=storeName]').count() else False,'美团账号身份核对')
        sessions,complete=mt_list(page,observations,scope.get('window_start',scope['date']))
        scope['list_response_checks']=observations
        scope.update(list_complete=complete,scanned_sessions=len(sessions),sessions=[],errors=[])
        for item in sessions:
            latest=stamp(item.get('latest'))
            if not latest:scope['errors'].append('无法识别会话最近日期');continue
            if latest[:10]<scope.get('window_start',scope['date']):continue
            if account.get('headquarters') and not item.get('group') and scope['store'].replace('店','') not in item['label']:continue
            try:
                session=mt_history(page,item,scope['date'],scope.get('window_start'))
                if account.get('headquarters') and item.get('group'):
                    if not any(scope['store'].replace('店','') in m['sender'] for m in session['messages'] if m['role']=='merchant'):continue
                if not any((scope.get('window_start',scope['date'])<=m['timestamp'][:10]<=scope['date']) or m['needs_review'] for m in session['messages']):
                    if not session['history_complete']:scope['errors'].append('会话历史未完整：'+item['label'].split('\n')[0])
                    continue
                save_media(page,scope,session);scope['sessions'].append(session)
            except Exception as e:scope['errors'].append(safe_error(e))
        scope['list_basis']='已核对全部顾客消息接口返回及界面分页/日期边界；总部按所属门店匹配' if complete else '未到达会话列表末尾'
    finally:
        page.close();browser.close()


def el_list(page,frame):
    tab=frame.get_by_role('tab',name='顾客消息',exact=True)
    tab.dispatch_event('click')
    wait(page,lambda:tab.get_attribute('aria-selected')=='true' and frame.locator('.custom_detail_tab').count(),'淘宝全部顾客消息筛选')
    page.wait_for_timeout(700)
    wait(page,lambda:frame.locator('.conv_item_plugin').count() or '暂无会话' in frame.locator('#root').inner_text(),'淘宝顾客消息列表')
    # Leave both 顾客单聊 / 三方群聊 unfiltered and unread-only off.
    for btn in frame.locator('.custom_detail_tab .button').all():
        if 'unClicked' not in (btn.get_attribute('class') or ''):btn.dispatch_event('click')
    unread=frame.locator('.custom_detail_tab .circle_wrapper')
    if unread.count()!=1:raise RuntimeError('淘宝未读筛选控件缺失，停止采集')
    if not unread.locator('.circle').count():unread.dispatch_event('click')
    wait(page,lambda:unread.locator('.circle').count()==1,'淘宝关闭只看未读')
    if frame.locator('.custom_detail_tab .button:not(.unClicked)').count():raise RuntimeError('淘宝单聊/三方群聊筛选未清空')
    box=frame.locator('#im_conversation_list_body')
    box.evaluate('e=>{e.scrollTop=0;e.dispatchEvent(new Event("scroll"))}')
    page.wait_for_timeout(600)
    seen={};expected=0;complete=False;position=0
    for _ in range(450):
        rows=frame.locator('.conv_item_plugin').evaluate_all("es=>es.map(e=>({id:e.getAttribute('limoo_session_id'),label:e.innerText,title:e.querySelector('.conv_item_plugin_title')?.textContent||'',latest:e.querySelector('.conv_item_default_time')?.textContent||''}))")
        for row in rows:
            if row['id']:seen[row['id']]=row
        info=box.evaluate("e=>({top:e.scrollTop,height:e.scrollHeight,client:e.clientHeight,virtual:(parseFloat(e.firstElementChild?.style.height)||0)+(parseFloat(e.firstElementChild?.style.marginTop)||0),row:e.querySelector('.imsdk_conv_item')?.getBoundingClientRect().height||0})")
        expected=round(info['virtual']/info['row']) if info['row'] else 0
        at_bottom=info['top']+info['client']>=info['height']-3
        if at_bottom and expected and len(seen)>=expected:
            page.wait_for_timeout(700)
            again=box.evaluate('e=>e.scrollHeight')
            if again==info['height']:complete=len(seen)==expected;break
        if not rows and '暂无会话' in box.inner_text():complete=True;break
        position=min(info['height'],position+max(150,info['client']*.7))
        box.evaluate('(e,y)=>{e.scrollTop=y;e.dispatchEvent(new Event("scroll"))}',position)
        page.wait_for_timeout(220)
    return list(seen.values()),complete,expected


def el_find(page,frame,item):
    box=frame.locator('#im_conversation_list_body')
    box.evaluate('e=>e.scrollTop=0');page.wait_for_timeout(220)
    for _ in range(450):
        # Attribute values are bound as data, never interpolated into JavaScript code.
        row=frame.locator('.conv_item_plugin').evaluate_all('(es,id)=>es.findIndex(e=>e.getAttribute("limoo_session_id")===id)',item['id'])
        if row>=0:
            frame.locator('.conv_item_plugin').nth(row).dispatch_event('click');return
        info=box.evaluate('e=>({top:e.scrollTop,client:e.clientHeight,height:e.scrollHeight})')
        if info['top']+info['client']>=info['height']-2:break
        box.evaluate('e=>{e.scrollTop+=Math.max(150,e.clientHeight*.7);e.dispatchEvent(new Event("scroll"))}')
        page.wait_for_timeout(180)
    raise RuntimeError('淘宝虚拟列表中未重新定位到目标会话')


def el_history(page,frame,item,target,window_start=None):
    el_find(page,frame,item)
    wait(page,lambda:frame.locator('.imsdk_msg_list_item').count(),'淘宝会话正文')
    page.wait_for_timeout(600)
    # Every rendered message carries its conversation id. Never accept previous chat contents.
    wait(page,lambda:frame.locator('.imsdk_msg_list_item').evaluate_all('(es,id)=>es.every(e=>e.getAttribute("limoo_session_id")===id)',item['id']),'淘宝会话归属')
    box=frame.locator('#im_sdk_msg_list_container');merged={};stable=0;last='';complete=False;basis=''
    for _ in range(120):
        rows=frame.locator('.msg_list').evaluate(EL_ROWS)
        if rows and not rows[-1].get('time'):
            rows[-1]['time']=stamp(item['latest']);rows[-1]['time_inferred']=True
        for row in rows:merged[row['id']]=row
        # EL rows include explicit time for each regular message and nearest preceding system-time label.
        messages=normalize(list(merged.values()),target)
        known=[m['timestamp'] for m in messages if m['timestamp']]
        if known and min(known)[:10]<(window_start or target):
            complete=True;basis='历史已越过目标日开始时间';break
        signature='|'.join(r['id'] for r in rows)
        stable=stable+1 if signature==last else 0;last=signature
        if stable>=4:
            # No explicit end marker exists in this UI: expose verification level, never claim server-total reconciliation.
            basis='已滚动到界面历史起点并连续5次复核；平台未提供消息总数'
            complete=True;break
        box.evaluate('e=>{e.scrollTop=1;e.dispatchEvent(new Event("scroll"));e.scrollTop=0;e.dispatchEvent(new Event("scroll"))}')
        page.wait_for_timeout(650)
    messages=normalize(list(merged.values()),target)
    return dict(**item,messages=messages,history_complete=complete,history_basis=basis)


def eleme(pw,scope,config):
    browser=pw.chromium.connect_over_cdp('http://127.0.0.1:9222',timeout=10000)
    # The merchant shell shares store context across tabs. Switch inside a valid existing shell.
    page=next((pg for context in browser.contexts for pg in context.pages if 'melody.shop.ele.me/app/' in pg.url and pg.locator('[data-manual-spm="a2f1q.bx798315.cx137275.dx174403"]').count()),None)
    owned=page is None
    if owned:
        page=browser.contexts[0].new_page()
        page.goto('https://melody.shop.ele.me/',wait_until='domcontentloaded',timeout=60000)
    page.set_default_timeout(12000)
    try:
        sid=config['eleme_shop_id']
        if f'/app/shop/{sid}/' not in page.url or config['eleme_keyword'] not in page.locator('body').first.inner_text()[:600]:
            header=page.locator('[data-manual-spm="a2f1q.bx798315.cx137275.dx174403"]')
            wait(page,lambda:header.count(),'淘宝原生门店选择器')
            search=page.get_by_placeholder('搜索店铺名称/ID')
            if not search.is_visible():header.dispatch_event('click')
            search.wait_for(state='visible',timeout=12000);search.fill('');search.fill(sid)
            menu=page.locator('#dropContentEl li[data-value]')
            wait(page,lambda:menu.evaluate_all('(es,id)=>es.some(e=>e.getAttribute("data-value").endsWith("/SHOP:"+id))',sid),'淘宝门店搜索结果')
            matching=menu.filter(has_text=config['eleme_keyword'])
            if matching.count()!=1:raise RuntimeError('淘宝门店搜索结果无法唯一匹配')
            if not matching.get_attribute('data-value').endswith('/SHOP:'+sid):raise RuntimeError('淘宝门店 ID 不匹配')
            matching.dispatch_event('click')
        wait(page,lambda:config['eleme_keyword'] in page.locator('body').first.inner_text()[:600],'淘宝单店身份')
        # Some versions mount the floating entry only after scrolling.
        page.mouse.wheel(0,600)
        wait(page,lambda:page.locator('[class*=imIcon__]').count(),'淘宝消息入口')
        frame=wait(page,lambda:next((f for f in page.frames if f.url.startswith('https://im.ele.me/napos') and f'shopId={sid}' in f.url),None),'淘宝单店聊天窗口')
        wait(page,lambda:frame.get_by_role('tab',name='顾客消息',exact=True).count(),'淘宝聊天组件加载')
        page.wait_for_timeout(600)
        if 'web_im_visually_hidden' in (page.locator('#web_im_iframe_container').get_attribute('class') or ''):
            page.locator('[class*=imIcon__]').dispatch_event('click')
        wait(page,lambda:frame.locator('#im_conversation_list_body').evaluate('e=>e.clientHeight>100'),'淘宝聊天窗口展开')
        sessions,complete,expected=el_list(page,frame)
        scope.update(list_complete=complete,scanned_sessions=len(sessions),expected_sessions=expected,sessions=[],errors=[],list_basis='虚拟列表逐屏去重并核对总高度/行高对应的会话数')
        for item in sessions:
            latest=stamp(item['latest'])
            if not latest:scope['errors'].append('无法识别会话日期：'+item['title']);continue
            if latest[:10]<scope.get('window_start',scope['date']):continue
            try:
                session=el_history(page,frame,item,scope['date'],scope.get('window_start'))
                if any((scope.get('window_start',scope['date'])<=m['timestamp'][:10]<=scope['date']) or m['needs_review'] for m in session['messages']):
                    save_media(page,scope,session,frame);scope['sessions'].append(session)
                elif not session['history_complete']:scope['errors'].append('会话历史未完整：'+item['title'])
            except Exception as e:scope['errors'].append(safe_error(e))
    finally:
        if owned:page.close()
        browser.close()



def restore_eleme_headquarters(pw):
    """Restore the nationwide/all-store organization token before downstream jobs."""
    from ensure_eleme_headquarters_context import choose_context,has_visible_switcher,GROUP_ID,NEUTRAL_CONTEXT_URL
    browser=pw.chromium.connect_over_cdp('http://127.0.0.1:9222',timeout=10000)
    page=next((pg for ctx in browser.contexts for pg in ctx.pages if 'melody.shop.ele.me/app' in pg.url and has_visible_switcher(pg)),None)
    owned=page is None
    try:
        if owned:
            page=browser.contexts[0].new_page();page.goto(NEUTRAL_CONTEXT_URL,wait_until='domcontentloaded',timeout=60000)
            page.wait_for_timeout(1500)
        search=page.get_by_placeholder('搜索店铺名称/ID')
        if search.count() and search.is_visible():search.fill('');page.wait_for_timeout(500)
        choose_context(page,f'{GROUP_ID}__RC_CASCADER_SPLIT__{GROUP_ID}',f'**/app/chain/{GROUP_ID}/**')
        if '/app/chain/'+GROUP_ID+'/' not in page.url:raise RuntimeError('淘宝未恢复全国全部门店范围')
        return True
    finally:
        if owned and page:page.close()
        browser.close()

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--date',default=(datetime.now(TZ).date()-timedelta(days=1)).isoformat())
    ap.add_argument('--lookback',type=int,default=3,choices=range(1,8),help='重查最近几天，补获跨天或延迟记录')
    ap.add_argument('--store',action='append')
    ap.add_argument('--platform',choices=['美团','淘宝闪购'],action='append')
    args=ap.parse_args();datetime.strptime(args.date,'%Y-%m-%d')
    if 'mini' not in platform.node().lower():raise SystemExit('仅允许在 Mac mini 生产主机采集')
    from playwright.sync_api import sync_playwright
    config=json.loads((ROOT/'config/customer_messages.json').read_text())['stores']
    accounts={a['id']:a for a in json.loads((ROOT/'config/direct_meituan_accounts.json').read_text())['accounts']}
    if args.store and set(args.store)-{c['store'] for c in config}:raise SystemExit('未知直营门店')
    snapshot=dict(schema_version=1,target_date=args.date,generated_at=datetime.now(TZ).isoformat(timespec='seconds'),scopes={})
    # Resume same-date successful scopes only when a subset is explicitly requested.
    existing=OUT/args.date/'snapshot.json'
    previous_snapshot=json.loads(existing.read_text()) if existing.exists() else {}
    run_id=datetime.now(TZ).strftime('%Y%m%dT%H%M%S%f')
    if (args.store or args.platform) and existing.exists():snapshot=json.loads(existing.read_text())
    with sync_playwright() as pw:
        for c in config:
            if args.store and c['store'] not in args.store:continue
            for plat in args.platform or ['美团','淘宝闪购']:
                key=c['store']+'|'+plat
                for attempt in range(2):
                    scope=dict(store=c['store'],platform=plat,date=args.date,window_start=(datetime.strptime(args.date,'%Y-%m-%d').date()-timedelta(days=args.lookback-1)).isoformat(),collected_at=datetime.now(TZ).isoformat(timespec='seconds'),sessions=[],errors=[],list_complete=False)
                    try:
                        if plat=='美团':
                            a=accounts.get(c['meituan_account'])
                            if a:
                                if not a.get('enabled'):raise RuntimeError('直营账号未启用')
                                meituan(pw,scope,dict(port=a['debug_port']),a['keyword'])
                            else:meituan(pw,scope,dict(port=9222,headquarters=True),'总部')
                        else:eleme(pw,scope,c)
                    except Exception as e:scope['error']=safe_error(e)
                    scope['status']=scope_status(scope)
                    scope['attempts']=attempt+1
                    if scope['status']=='ready':break
                    print(f'{key}: 第{attempt+1}次未完整；{scope.get("error","")}；{"；".join(scope.get("errors",[]))}',flush=True)
                atomic_json(OUT/args.date/'captures'/f'{c["eleme_shop_id"]}-{"meituan" if plat=="美团" else "eleme"}.json',scope)
                atomic_json(OUT/args.date/'runs'/run_id/f'{c["eleme_shop_id"]}-{"meituan" if plat=="美团" else "eleme"}.json',scope)
                from customer_message_data import project_scope,retain_previous_scope
                snapshot['scopes'][key]=retain_previous_scope(previous_snapshot.get('scopes',{}).get(key),project_scope(scope,args.date))
                scope=snapshot['scopes'][key]
                snapshot['generated_at']=datetime.now(TZ).isoformat(timespec='seconds')
                atomic_json(existing,snapshot);atomic_json(OUT/'latest.json',snapshot)
                print(f'{key}: {scope["status"]}, {len(scope["sessions"])} 段, {scope.get("error","")}',flush=True)
        if not args.platform or '淘宝闪购' in args.platform:
            try:
                snapshot['context_restored']=restore_eleme_headquarters(pw)
                snapshot.pop('context_error',None)
                print('淘宝已恢复全国全部门店范围',flush=True)
            except Exception as exc:
                snapshot['context_error']=safe_error(exc)
                print('淘宝总部范围恢复失败：'+snapshot['context_error'],flush=True)
        atomic_json(existing,snapshot);atomic_json(OUT/'latest.json',snapshot)
    from customer_message_data import project_scope
    for offset in range(1,args.lookback):
        older=(datetime.strptime(args.date,'%Y-%m-%d').date()-timedelta(days=offset)).isoformat()
        path=OUT/older/'snapshot.json'
        archive=json.loads(path.read_text()) if path.exists() else dict(schema_version=1,target_date=older,scopes={})
        archive['generated_at']=snapshot['generated_at']
        for capture in (OUT/args.date/'captures').glob('*.json'):
            raw=json.loads(capture.read_text())
            if raw.get('collected_at','')<snapshot['generated_at'][:10] or raw.get('window_start',args.date)>older:continue
            key=raw['store']+'|'+raw['platform']; projected=project_scope(raw,older)
            # Never replace a verified historical capture with a later failed read.
            if projected['status']=='ready' or archive['scopes'].get(key,{}).get('status')!='ready':archive['scopes'][key]=projected
        atomic_json(path,archive)
    from render_customer_messages import build
    build()
    failed=[k for k,v in snapshot['scopes'].items() if v['status']!='ready']
    if len(snapshot['scopes'])!=len(config)*2:failed.append('覆盖门店平台数量未满')
    if snapshot.get('context_error'):failed.append('淘宝全国全部门店范围恢复')
    if failed:raise SystemExit('客服消息采集有未完成项：'+','.join(failed))

if __name__=='__main__':main()
