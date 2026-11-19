import copy
import json
from pathlib import Path
from unittest.mock import patch

from scripts import longxia_promo_snapshot as reader

NOW = 1794702000000

def test_snapshot_only_reads_fresh_identity_matched_values_in_cents(tmp_path):
    path, config = tmp_path / 'fleet.json', tmp_path / 'config.json'
    config.write_text(json.dumps({'longxia': {'stores': [{'profileId': 'profile1', 'name': '甲店', 'sourceStore': '甲'}]}}))
    row = {'id': 'profile1', 'name': '甲店', 'day': '2026-11-15', 'snapshotAt': NOW, 'spend': 1234, 'platformBudget': 5000}
    data = {'schema': 1, 'generatedAt': NOW, 'stores': [row]}
    def read(payload):
        path.write_text(json.dumps(payload))
        return reader.read_records([{'sourceStore': '甲'}], path=path, config_path=config, now=NOW)[0]
    record = read(data)
    assert record['ok'] and record['today_spend'] == 12.34 and record['budget'] == 50
    assert record['remaining_budget'] == 37.66
    for changes in [{'day': '2026-11-14'}, {'snapshotAt': NOW - 1800001}, {'spend': None}, {'spend': True}, {'paused': True}, {'id': 'wrong'}]:
        payload = copy.deepcopy(data); payload['stores'][0].update(changes)
        record = read(payload)
        assert not record['ok'] and record['today_spend'] is None
    stale = copy.deepcopy(data); stale['generatedAt'] = NOW - 90001
    assert not read(stale)['ok']
    assert not reader.read_records([{'sourceStore': '甲'}], path=tmp_path/'missing', config_path=config, now=NOW)[0]['ok']


def test_spend_consumer_never_starts_browser_or_workers_even_without_snapshot(tmp_path):
    from scripts import meituan_promo_spend_query as query
    with patch.object(query, 'load_meituan_tasks', return_value=[{'sourceStore': '甲'}]), \
         patch.object(query, 'require_helpers', side_effect=AssertionError('must not browse')), \
         patch.object(query, 'build_payload_parallel', side_effect=AssertionError('must not start workers')), \
         patch.object(reader, 'SNAPSHOT_PATH', tmp_path/'missing'):
        payload = query.build_payload('all', [], None, workers=4)
    assert payload['source'] == 'longxia_snapshot'
    assert payload['status'] == 'failed'
    assert payload['items'][0]['today_spend'] is None


def test_missing_snapshot_totals_are_unknown_instead_of_zero():
    from scripts import meituan_promo_spend_query as query
    payload = query.payload_from_results('all', [{'ok': False, 'error': '等待快照', 'today_spend': None}])
    assert payload['summary']['today_spend_total'] is None
    assert '消耗 未知' in payload['message']
    assert '预算 未知' in payload['message']


def test_balance_snapshot_missing_stale_boolean_zero_negative_and_paused(tmp_path):
    path, config = tmp_path/'fleet.json', tmp_path/'config.json'
    config.write_text(json.dumps({'longxia': {'stores': [{'profileId':'p1','name':'望京'}]}}))
    row = {'id':'p1','day':'2026-11-15','snapshotAt':NOW,'accountBalanceAt':NOW,'accountBalance':1234}
    def read(changes=None):
        data={'schema':1,'generatedAt':NOW,'stores':[{**row, **(changes or {})}]}
        path.write_text(json.dumps(data))
        return reader.read_balance_items(path=path,config_path=config,now=NOW)
    for value in [0, -235, 1234]:
        items,issues=read({'accountBalance':value})
        assert not issues and items[0]['balance']==value/100
        assert items[0]['confirmed_zero']==(value==0)
    for changes in [{'accountBalance':None},{'accountBalance':True},{'paused':True},{'status':'pending'},
                    {'accountBalanceAt':NOW-1800001},{'id':'wrong'},{'day':'2026-11-14'}]:
        items,issues=read(changes)
        assert not items and len(issues)==1
    path.unlink()
    items,issues=reader.read_balance_items(path=path,config_path=config,now=NOW)
    assert not items and issues


def test_balance_missing_is_a_warning_and_still_notified_without_low_stores(tmp_path):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
    from scripts import build_promo_balance_status as builder
    from scripts import agent_task_notifier as notifier
    payload = {'generated_at': reader.datetime.now().strftime('%F %T'), 'status':'partial',
               'items': [], 'balance_collection_issues':[{'platform':'美团','store_name':'望京','message':'余额未采到'}]}
    status = builder.build_status(payload)
    assert status['status'] == 'warning'
    path=tmp_path/'status.json';path.write_text(json.dumps(status))
    task=notifier.load_promo_balance_alert_tasks(path)['growth.promo_balance.low_balance']
    assert '望京' in task['message'] and '不能视为余额充足' in task['message']


def test_refresh_notice_deduplicates_amount_changes_but_sends_new_low_stores(tmp_path):
    import sys
    from types import SimpleNamespace
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
    from scripts import agent_task_notifier as notifier
    path=tmp_path/'status.json'
    payload={'status':'warning','summary':{},'source_generated_at':'2026-11-19 19:15:00',
             'low_balance_items':[{'platform':'美团','store_name':'望京','balance':10,'threshold':200}]}
    args=SimpleNamespace(runs=str(tmp_path/'runs.json'),state=str(tmp_path/'state.json'),log=str(tmp_path/'log.json'),
                         seed=False,dry_run=False,no_write=False,include_unconfigured=False,promo_balance_refresh=True,
                         promo_balance_period='',target='weixin',hermes_bin='')
    loader=notifier.load_promo_balance_alert_tasks
    with patch.object(notifier,'DEFAULT_PROMO_BALANCE_STATUS_PATH',path), \
         patch.object(notifier,'load_promo_balance_alert_tasks',side_effect=lambda:loader(path)), \
         patch.object(notifier,'load_policy_rows',return_value=notifier.DIRECT_TASK_ROWS), \
         patch.object(notifier,'send_weixin',return_value=(True,'wecom errcode=0')) as send:
        path.write_text(json.dumps(payload));assert notifier.notify(args)['notification_count']==1
        payload['low_balance_items'][0]['balance']=9
        path.write_text(json.dumps(payload));assert notifier.notify(args)['notification_count']==0
        payload['low_balance_items'].append({'platform':'美团','store_name':'清河','balance':3,'threshold':200})
        path.write_text(json.dumps(payload));assert notifier.notify(args)['notification_count']==1
        assert send.call_count==2
