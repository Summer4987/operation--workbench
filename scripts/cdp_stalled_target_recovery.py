"""Bounded recovery of an unresponsive read-only HQ homepage, never a browser restart."""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import shlex
import subprocess
import time
from urllib.parse import urlsplit, quote, parse_qsl
from urllib.request import urlopen

try:
    from . import platform_account_access as accounts
except ImportError:
    import platform_account_access as accounts

ROOT = Path(__file__).resolve().parents[1]
NODE = Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
OUT = ROOT/'outputs/cdp_recovery'
COOLDOWN = 300


def tabs(endpoint):
    with urlopen(endpoint+'/json/list', timeout=3) as r:
        return json.load(r)


def safe_homepage(tab, all_tabs):
    u=urlsplit(tab.get('url',''))
    if tab.get('type')!='page' or u.scheme!='https' or u.hostname!='e.waimai.meituan.com' or u.path not in ('','/'):
        return False
    # Completed verification can leave callback codes on a read-only business URL.
    # Values are never logged; editors and login routes remain excluded.
    fragment=urlsplit(u.fragment)
    readonly_business=(fragment.scheme=='https' and fragment.hostname=='waimaieapp.meituan.com'
                       and fragment.path=='/igate/bizdata/business' and not fragment.query and not fragment.fragment)
    callback_keys={key for key,value in parse_qsl(u.query,keep_blank_values=True)}
    known_callback={'response_code','request_code','responseCode','requestCode'}
    if u.fragment and not readonly_business:return False
    if u.query and (not readonly_business or not callback_keys.issubset(known_callback)):return False
    if any(x in str(tab.get('title','')) for x in ('验证','登录')):
        return False
    # An embedded challenge or editor must remain available to the person using it.
    for child in all_tabs:
        if child.get('parentId')!=tab.get('id'):
            continue
        url=str(child.get('url',''))
        if 'verify.meituan.com' in url or '/ad/' in url or 'login' in url:
            return False
    return True


def completed_promo_landing(tab, all_tabs):
    """Only the known CPC index after today's budget is fully verified."""
    u = urlsplit(tab.get('url', ''))
    inner = urlsplit(u.fragment)
    if (tab.get('type') != 'page' or u.scheme != 'https'
        or u.hostname != 'e.waimai.meituan.com' or u.path not in ('', '/') or u.query
        or inner.scheme != 'https' or inner.hostname != 'waimaieapp.meituan.com'
        or inner.path != '/ad/v1/rpc'
        or inner.fragment != '/subapp/isomor_cpc/pages/index/index'):
        return False
    if not {k for k, v in parse_qsl(inner.query, keep_blank_values=True)}.issubset(
        {'device_uuid', 'bsid', 'appType', 'topOrigin', 'region_id', 'userId'}
    ):
        return False
    if any(x in str(tab.get('title', '')) for x in ('验证', '登录')):
        return False
    for child in all_tabs:
        if child.get('parentId') == tab.get('id'):
            url = str(child.get('url', '')).lower()
            if any(x in url for x in ('verify.', 'login', 'edit', 'recharge', 'payment')):
                return False
    try:
        state = json.loads((ROOT/'outputs/task_runs/latest.json').read_text())
        budget = state.get('tasks', {}).get('growth.promo_budget', {})
        return (budget.get('status') == 'success'
                and str(budget.get('finished_at', '')).startswith(time.strftime('%F')))
    except (OSError, ValueError, TypeError):
        return False


def safe_recoverable(tab, all_tabs):
    return safe_homepage(tab, all_tabs) or completed_promo_landing(tab, all_tabs)


def other_browser_tasks():
    out=subprocess.check_output(['ps','-axo','pid=,args='],text=True,timeout=3)
    protected={'meituan_budget_cdp.py','eleme_dianjin_adapter.mjs','realtime_order_income.py',
               'collect_review_pages.py','collect_customer_messages.py','download_direct_meituan_daily.py'}
    for line in out.splitlines():
        parts=line.strip().split(None,1)
        if len(parts)!=2 or int(parts[0])==os.getpid():continue
        try:args=shlex.split(parts[1])
        except ValueError:continue
        if any(Path(arg).name in protected for arg in args):return True
    return False


def responsive(tab):
    endpoint=tab.get('webSocketDebuggerUrl','')
    r=subprocess.run([str(NODE),str(ROOT/'scripts/probe_cdp_target.mjs'),endpoint,'1800'],
                     capture_output=True,text=True,timeout=4)
    if r.returncode:return None
    d=json.loads(r.stdout)
    return d.get('responsive') if d.get('phase')=='renderer' else None


def recover(endpoint):
    if endpoint!='http://127.0.0.1:9222' or not accounts.production_enabled():
        return False
    OUT.mkdir(parents=True,exist_ok=True)
    with (OUT/'recovery.lock').open('a+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return False
        prior=OUT/'latest.json'
        if prior.exists() and time.time()-prior.stat().st_mtime<COOLDOWN:return False
        if other_browser_tasks() or accounts.Coordinator().pending('headquarters'):return False
        original=tabs(endpoint)
        for tab in original:
            if not safe_recoverable(tab,original):continue
            # Closing a stalled read-only Chrome tab makes no merchant request
            # and must not wait for Longxia's separate Electron account lease.
            lane=(accounts.optional_readonly_lease('headquarters') if safe_homepage(tab,original)
                  else accounts.optional_lease('headquarters'))
            with lane:
                if responsive(tab) is not False or responsive(tab) is not False:continue
                current=tabs(endpoint)
                same=next((t for t in current if t.get('id')==tab.get('id')),None)
                if not same or same.get('url')!=tab.get('url') or not safe_recoverable(same,current):continue
                if other_browser_tasks() or accounts.Coordinator().pending('headquarters'):return False
                with urlopen(endpoint+'/json/close/'+quote(str(tab['id']),safe=''),timeout=3) as r:
                    r.read()
                accounts.Coordinator().write(prior,{'recovered_at':time.strftime('%F %T'),
                    'target_id':tab['id'],'reason':('read_only_page_unresponsive_twice' if safe_homepage(same,current) else 'completed_budget_landing_unresponsive_twice'),
                    'closed_count':1,'browser_restarted':False})
                print('已恢复 Chrome 接入：仅关闭连续两次不响应且符合安全恢复条件的旧美团页面；登录会话保留。',flush=True)
                return True
    return False
