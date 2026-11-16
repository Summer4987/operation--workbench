import json
from pathlib import Path
from unittest import mock

from scripts import cdp_stalled_target_recovery as recovery
from scripts import platform_account_access as access

HOME={'id':'ABC','type':'page','title':'美团外卖商家版','url':'https://e.waimai.meituan.com/',
      'webSocketDebuggerUrl':'ws://127.0.0.1:9222/devtools/page/ABC'}


def test_only_plain_read_only_homepage_is_eligible():
    assert recovery.safe_homepage(HOME,[HOME])
    for change in [{'url':'https://verify.meituan.com/'},{'title':'安全验证'},
                   {'url':'https://e.waimai.meituan.com/#https://waimaieapp.meituan.com/ad/v1/rpc'},
                   {'url':'https://e.waimai.meituan.com/?ticket=private'},{'url':'https://r.ele.me/doujin-isv-manage/index.html'}]:
        assert not recovery.safe_homepage({**HOME,**change},[HOME])
    challenge={'type':'iframe','parentId':'ABC','url':'https://verify.meituan.com/'}
    assert not recovery.safe_homepage(HOME,[HOME,challenge])


def setup(tmp_path,monkeypatch):
    monkeypatch.setattr(recovery,'OUT',tmp_path/'recovery')
    monkeypatch.setattr(recovery.accounts,'production_enabled',lambda:True)
    c=access.Coordinator(tmp_path/'access',gap_seconds=0,notify=False)
    monkeypatch.setattr(recovery.accounts,'Coordinator',lambda:c)
    monkeypatch.setattr(recovery,'other_browser_tasks',lambda:False)
    monkeypatch.setattr(recovery,'tabs',lambda endpoint:[dict(HOME)])
    return c


def test_two_unresponsive_probes_close_only_that_homepage_and_rate_limit(tmp_path,monkeypatch):
    setup(tmp_path,monkeypatch)
    probe=mock.Mock(return_value=False);monkeypatch.setattr(recovery,'responsive',probe)
    request=mock.MagicMock();monkeypatch.setattr(recovery,'urlopen',request)
    assert recovery.recover('http://127.0.0.1:9222')
    assert probe.call_count==2
    assert request.call_args.args[0]=='http://127.0.0.1:9222/json/close/ABC'
    assert not recovery.recover('http://127.0.0.1:9222')
    assert request.call_count==1


def test_responsive_unknown_changed_or_active_pages_are_never_closed(tmp_path,monkeypatch):
    setup(tmp_path,monkeypatch)
    close=mock.MagicMock();monkeypatch.setattr(recovery,'urlopen',close)
    for values in [[True],[False,True],[None]]:
        monkeypatch.setattr(recovery,'responsive',mock.Mock(side_effect=values))
        assert not recovery.recover('http://127.0.0.1:9222')
    monkeypatch.setattr(recovery,'responsive',lambda tab:False)
    monkeypatch.setattr(recovery,'tabs',mock.Mock(side_effect=[[HOME],[{**HOME,'url':'https://verify.meituan.com/'}]]))
    assert not recovery.recover('http://127.0.0.1:9222')
    monkeypatch.setattr(recovery,'other_browser_tasks',lambda:True)
    assert not recovery.recover('http://127.0.0.1:9222')
    close.assert_not_called()


def test_verification_hold_and_other_ports_are_not_recovered(tmp_path,monkeypatch):
    c=setup(tmp_path,monkeypatch);c.block('headquarters','安全验证')
    close=mock.MagicMock();monkeypatch.setattr(recovery,'urlopen',close)
    assert not recovery.recover('http://127.0.0.1:9222')
    assert not recovery.recover('http://127.0.0.1:19223')
    close.assert_not_called()


def test_node_probe_distinguishes_renderer_stall_from_transport_and_rejects_remote():
    import subprocess
    node='/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
    script=Path(recovery.__file__).with_name('probe_cdp_target.mjs')
    for mode,expected in [('ready',True),('stalled',False),('transport',None)]:
        harness='''
const mode=process.argv[1];
global.WebSocket=class {
 constructor(){this.listeners={};setImmediate(()=>this.listeners[mode==='transport'?'error':'open']?.({}));}
 addEventListener(k,fn){this.listeners[k]=fn;}
 send(value){const d=JSON.parse(value);if(d.method!=='Page.getFrameTree')process.exit(70);if(mode==='ready')queueMicrotask(()=>this.listeners.message({data:JSON.stringify({id:1,result:{frameTree:{}}})}));}
};
process.argv=['node','probe','ws://127.0.0.1:9222/devtools/page/ABC','100'];
await import('file://'+process.argvProbe);
'''.replace("process.argvProbe",json.dumps(str(script)))
        r=subprocess.run([node,'--input-type=module','-e',harness,mode],capture_output=True,text=True,timeout=3)
        assert r.returncode==0,r.stderr
        assert json.loads(r.stdout)['responsive'] is expected
    rejected=subprocess.run([node,str(script),'ws://example.com:9222/devtools/page/ABC','100'],capture_output=True,text=True,timeout=2)
    assert rejected.returncode==64


def test_completed_verification_callback_on_readonly_business_route_is_recoverable():
    business={**HOME,'url':'https://e.waimai.meituan.com/?response_code=private&requestCode=private#https://waimaieapp.meituan.com/igate/bizdata/business'}
    assert recovery.safe_homepage(business,[business])
    for url in ['https://e.waimai.meituan.com/?response_code=private',
                'https://e.waimai.meituan.com/?ticket=private#https://waimaieapp.meituan.com/igate/bizdata/business',
                'https://e.waimai.meituan.com/?response_code=private#https://waimaieapp.meituan.com/ad/v1/rpc',
                'https://e.waimai.meituan.com/#https://verify.meituan.com/igate/bizdata/business']:
        assert not recovery.safe_homepage({**HOME,'url':url},[HOME])


def test_completed_cpc_landing_requires_today_verified_budget(tmp_path, monkeypatch):
    import json, time
    monkeypatch.setattr(recovery, 'ROOT', tmp_path)
    landing = {**HOME, 'url':'https://e.waimai.meituan.com/#https://waimaieapp.meituan.com/ad/v1/rpc?device_uuid=x&appType=pc&region_id=1&userId=2#/subapp/isomor_cpc/pages/index/index'}
    path = tmp_path/'outputs/task_runs/latest.json'
    path.parent.mkdir(parents=True)
    for status, date, expected in [('success',time.strftime('%F'),True), ('failed',time.strftime('%F'),False),('running',time.strftime('%F'),False),('success','2020-01-01',False)]:
        path.write_text(json.dumps({'tasks':{'growth.promo_budget':{'status':status,'finished_at':date+' 08:30:00'}}}))
        assert recovery.completed_promo_landing(landing,[landing]) is expected
    path.write_text(json.dumps({'tasks':{'growth.promo_budget':{'status':'success','finished_at':time.strftime('%F')+' 08:30:00'}}}))
    for suffix in ['?wmPoiId=123#/subapp/isomor_cpc/pages/index/index', '#/edit', '#/subapp/isomor_cpc/pages/recharge/index']:
        bad={**landing,'url':'https://e.waimai.meituan.com/#https://waimaieapp.meituan.com/ad/v1/rpc'+suffix}
        assert not recovery.completed_promo_landing(bad,[bad])
    child={'parentId':landing['id'],'url':'https://verify.meituan.com/'}
    assert not recovery.completed_promo_landing(landing,[landing,child])
