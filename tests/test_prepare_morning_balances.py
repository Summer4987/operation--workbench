import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from prepare_morning_balances import readiness

NOW=1795132800000  # 2026-11-20 08:00 China time


def test_morning_requires_today_balances_but_paused_store_is_reported_not_waited(tmp_path):
    path,config=tmp_path/'fleet.json',tmp_path/'config.json'
    config.write_text(json.dumps({'longxia':{'stores':[{'profileId':'a','name':'正常店'},{'profileId':'b','name':'暂停店'}]}}))
    data={'schema':1,'generatedAt':NOW,'stores':[
        {'id':'a','name':'正常店','day':'2026-11-20','accountBalanceDay':'2026-11-20','accountBalanceAt':NOW,'accountBalance':0},
        {'id':'b','name':'暂停店','paused':True}]}
    def read():
        path.write_text(json.dumps(data));return readiness(path=path,config_path=config,now=NOW)
    result=read();assert result['ready'] and result['confirmed_count']==1 and len(result['paused'])==1
    data['stores'][0]['accountBalanceDay']='2026-11-19'
    assert not read()['ready']
    data['stores'][0]['accountBalanceDay']='2026-11-20';data['generatedAt']=NOW-90001
    assert not read()['ready']


def test_morning_flow_starts_prefetch_early_and_delivers_before_budget():
    text=(Path(__file__).resolve().parents[1]/'morning-ops/run_morning_ops.py').read_text()
    assert text.index('"启动上午余额预读"') < text.index('"总部平台登录态预检",\n                    budget_preflight_args')
    assert text.index('"上午美团余额预读"') < text.index('balance_result = run_step_with_pause')
    assert text.index('"上午推广低余额通知"') < text.index('f"美团{budget_period}预算真实提交"')

    assert text.index('"上午推广低余额通知"') < text.index('"直营双平台客服消息采集"')


def test_todays_delivery_does_not_suppress_tomorrow_morning(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import patch
    import agent_task_notifier as notifier
    state=tmp_path/'state.json';state.write_text(json.dumps({'sent':{'growth.promo_balance.low_balance':'notification_slot|2026-11-19|上午'}}))
    args=SimpleNamespace(runs=str(tmp_path/'runs.json'),state=str(state),log=str(tmp_path/'log.json'),target='weixin',hermes_bin='',seed=False,dry_run=True,no_write=True,include_unconfigured=False,promo_balance_period='上午')
    tasks={'growth.promo_balance.low_balance':{'status':'warning','message':'中关村 0 元','finished_at':'2026-11-20 08:05:00'}}
    with patch.object(notifier,'load_promo_balance_alert_tasks',return_value=tasks),patch.object(notifier,'load_policy_rows',return_value=notifier.DIRECT_TASK_ROWS),patch.object(notifier.time,'strftime',return_value='2026-11-20'):
        payload=notifier.notify(args)
    assert payload['notification_count']==1
    assert payload['sent']['growth.promo_balance.low_balance']=='notification_slot|2026-11-20|上午'
